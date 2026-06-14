"""
AI Suite — Agent Core (v4.0)
ReAct 循环：思考→工具调用→观察→重复
支持 Ollama 本地 / DeepSeek V4 / OpenRouter 云端
v4.0: RAG 记忆 + 插件系统 + MCP 客户端 + 邮件工具
"""
import json, time
import urllib.request as ur
from typing import Generator, Dict, Any, List, Optional
import tools
import hw_monitor

# v4.0 modules (optional)
try:
    from rag_memory import rag as rag_mem
    HAS_RAG = True
except ImportError:
    HAS_RAG = False
    rag_mem = None

try:
    from plugin_manager import pm
    HAS_PLUGINS = True
except ImportError:
    HAS_PLUGINS = False
    pm = None

try:
    from mcp_client import mcp as mcp_client
    HAS_MCP_CLIENT = True
except ImportError:
    HAS_MCP_CLIENT = False
    mcp_client = None

try:
    from email_tools import register_email_tools, HAS_OUTLOOK
    if HAS_OUTLOOK:
        register_email_tools()
except ImportError:
    pass

# ═══════ 工具格式转换 ═══════

def _tools_to_openai():
    """tools.py → OpenAI function-calling 格式"""
    result = []
    for t in tools.list_tools():
        props = {}
        req = []
        for pname, pinfo in t.get("schema", {}).items():
            prop = {"type": pinfo.get("type", "string")}
            if "description" in pinfo:
                prop["description"] = pinfo["description"]
            props[pname] = prop
            if not pinfo.get("optional"):
                req.append(pname)
        result.append({"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": {"type": "object", "properties": props, "required": req}
        }})
    return result

def _tools_to_anthropic():
    """tools.py → Anthropic tool_use 格式"""
    result = []
    for t in tools.list_tools():
        props = {}
        req = []
        for pname, pinfo in t.get("schema", {}).items():
            prop = {"type": pinfo.get("type", "string")}
            if "description" in pinfo:
                prop["description"] = pinfo["description"]
            props[pname] = prop
            if not pinfo.get("optional"):
                req.append(pname)
        result.append({
            "name": t["name"], "description": t["description"],
            "input_schema": {"type": "object", "properties": props, "required": req}
        })
    return result

def _tools_markdown():
    """工具列表 → Markdown 文本（给不支持 tool calling 的模型用）"""
    lines = ["可用工具："]
    for t in tools.list_tools():
        schema = t.get("schema", {})
        params = ", ".join(f"{k}({v.get('type','str')})" for k, v in schema.items())
        lines.append(f"- **{t['name']}**({params}): {t['description']}")
    lines.append("\n调用工具时，输出 JSON 块：```tool\n{\"name\": \"工具名\", \"args\": {...}}\n```")
    return "\n".join(lines)

# ═══════ Agent 系统提示 ═══════

AGENT_SYSTEM = """你是 g0dness Agent，运行在用户电脑上的自主桌面助手。

## 工作流程
1. 理解用户任务，规划步骤
2. 调用工具执行操作
3. 观察结果，调整计划
4. 完成后汇报

## 行为准则
- 一次调用一个工具，等待结果后再决定下一步
- 文件操作前先 list_dir 确认路径
- 写入文件前确认不会覆盖重要内容
- shell 命令只做必要操作，避免破坏性命令
- 遇到错误分析原因，尝试修复
- 完成所有步骤后，总结你做了什么、结果如何

## 回复风格
用中文回复。简洁、直接、可操作。不要角色扮演。"""

AGENT_SYSTEM_FALLBACK = AGENT_SYSTEM + "\n\n" + _tools_markdown()

# ═══════ DeepSeek V4 Config ═══════

import os as _os
import subprocess

def _load_deepseek_config():
    """Load DeepSeek config from model_keys.json"""
    key_path = _os.path.expanduser("~/.model_keys.json")
    try:
        with open(key_path, "r") as f:
            keys = json.load(f)
        return {
            "base_url": "https://api.deepseek.com/anthropic",
            "api_key": keys.get("deepseek_key", ""),
            "model": "deepseek-v4-pro",
        }
    except Exception:
        return {"base_url": "https://api.deepseek.com/anthropic", "api_key": "", "model": "deepseek-v4-pro"}

DEEPSEEK_CONFIG = _load_deepseek_config()

# ═══════ Agent 核心 ═══════

class Agent:
    def __init__(self, model_key: str = "deepseek"):
        """
        model_key:
          - "deepseek" → DeepSeek V4 (Anthropic tool use)
          - "ollama:qwen3:8b" → Ollama 本地 (native tool calling)
          - "ollama:deepseek-r1:14b" → Ollama (fallback prompt)
          - "claude" / "gemini" → OpenRouter
        """
        self.model_key = model_key
        self.messages: list = []
        self.max_turns = 15
        self._tool_id_counter = 0

    @property
    def _model_type(self):
        if self.model_key.startswith("ollama:"):
            return "ollama"
        if self.model_key == "deepseek":
            return "deepseek"
        return "openrouter"

    @property
    def _ollama_model(self):
        if ":" in self.model_key:
            return self.model_key.split(":", 1)[1]
        return "deepseek-r1:14b"

    # ─── LLM 调用 ───

    def _call_ollama(self, use_tools=True) -> dict:
        """调用 Ollama /api/chat。use_tools=False 走 fallback 文本模式"""
        body = {
            "model": self._ollama_model,
            "messages": self.messages,
            "stream": False,
            "options": {"temperature": 0.7}
        }
        if use_tools:
            body["tools"] = _tools_to_openai()
        req = ur.Request("http://localhost:11434/api/chat",
                        json.dumps(body).encode(),
                        headers={"Content-Type": "application/json"})
        return json.loads(ur.urlopen(req, timeout=180).read())

    def _call_ollama_stream(self, use_tools=True):
        """流式调用 Ollama，yield (token_text, final_message) — final_message 在最后"""
        body = {
            "model": self._ollama_model,
            "messages": self.messages,
            "stream": True,
            "options": {"temperature": 0.7}
        }
        if use_tools:
            body["tools"] = _tools_to_openai()
        req = ur.Request("http://localhost:11434/api/chat",
                        json.dumps(body).encode(),
                        headers={"Content-Type": "application/json"})
        resp = ur.urlopen(req, timeout=180)
        accumulated = {"content": "", "tool_calls": {}}
        for line_bytes in resp:
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line: continue
            try:
                chunk = json.loads(line)
                msg = chunk.get("message", {})
                token = msg.get("content", "")
                if token:
                    accumulated["content"] += token
                    yield (token, None)
                # Merge tool calls by index to avoid duplicates from progressive streaming
                for tc in msg.get("tool_calls", []):
                    idx = tc.get("index", len(accumulated["tool_calls"]))
                    accumulated["tool_calls"][idx] = tc
                if chunk.get("done"):
                    final_tools = [accumulated["tool_calls"][k]
                                   for k in sorted(accumulated["tool_calls"])]
                    yield (None, {"content": accumulated["content"], "tool_calls": final_tools})
                    return
            except json.JSONDecodeError:
                pass
        final_tools = [accumulated["tool_calls"][k]
                       for k in sorted(accumulated["tool_calls"])]
        yield (None, {"content": accumulated["content"], "tool_calls": final_tools})

    def _call_deepseek(self) -> dict:
        """调用 DeepSeek V4 Anthropic Messages API"""
        # 构建 Anthropic 消息格式
        anthropic_msgs = []
        for msg in self.messages:
            role = msg["role"]
            if role == "system":
                continue
            elif role == "tool":
                anthropic_msgs.append({"role": "user", "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": msg["content"]
                }]})
            elif role == "assistant":
                blocks = []
                if msg.get("content"):
                    blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    args = tc["function"].get("arguments", {})
                    if isinstance(args, str):
                        try: args = json.loads(args)
                        except: args = {"raw": args}
                    blocks.append({"type": "tool_use", "id": tc.get("id", ""),
                                   "name": tc["function"]["name"], "input": args})
                anthropic_msgs.append({"role": "assistant", "content": blocks})
            else:
                anthropic_msgs.append({"role": "user", "content": msg["content"]})

        # Extract system message (may include custom context from run/stream)
        sys_msg = AGENT_SYSTEM
        for msg in self.messages:
            if msg["role"] == "system":
                sys_msg = msg["content"]
                break

        body = json.dumps({
            "model": DEEPSEEK_CONFIG["model"],
            "max_tokens": 8192,
            "system": sys_msg,
            "messages": anthropic_msgs,
            "tools": _tools_to_anthropic(),
            "stream": False
        }).encode()
        req = ur.Request(f"{DEEPSEEK_CONFIG['base_url']}/v1/messages", body,
                        headers={"Content-Type": "application/json",
                                "x-api-key": DEEPSEEK_CONFIG["api_key"],
                                "anthropic-version": "2023-06-01"})
        return json.loads(ur.urlopen(req, timeout=180).read())

    def _call_openrouter(self) -> dict:
        """调用 OpenRouter (OpenAI tool format)"""
        from model_orchestrator import load_keys, OPENROUTER_MODELS, CACHE_SYSTEM_PROMPT
        keys = load_keys()
        api_key = keys.get("openrouter_key", "")
        if not api_key:
            raise RuntimeError("OpenRouter key not set")
        model_id = OPENROUTER_MODELS.get(self.model_key, OPENROUTER_MODELS["claude"])
        # Build messages — use system prompt from self.messages (includes persona)
        sys_content = CACHE_SYSTEM_PROMPT + "\n" + AGENT_SYSTEM
        for m in self.messages:
            if m["role"] == "system":
                sys_content = m["content"]
                break
        msgs = [{"role": "system", "content": sys_content}]
        for m in self.messages:
            if m["role"] != "system":
                msgs.append(m)
        body = json.dumps({
            "model": model_id,
            "messages": msgs,
            "tools": _tools_to_openai(),
            "tool_choice": "auto"
        }).encode()
        req = ur.Request("https://openrouter.ai/api/v1/chat/completions", body,
                        headers={"Content-Type": "application/json",
                                "Authorization": f"Bearer {api_key}",
                                "HTTP-Referer": "http://localhost:5001"})
        return json.loads(ur.urlopen(req, timeout=120).read())

    def _call_ollama_fallback(self) -> dict:
        """Fallback: 用文本 prompt 模拟 tool calling"""
        body = {
            "model": self._ollama_model,
            "messages": self.messages,
            "stream": False,
            "options": {"temperature": 0.7}
        }
        req = ur.Request("http://localhost:11434/api/chat",
                        json.dumps(body).encode(),
                        headers={"Content-Type": "application/json"})
        return json.loads(ur.urlopen(req, timeout=180).read())

    # ─── 响应解析 ───

    def _parse_ollama(self, response: dict) -> tuple:
        """解析 Ollama 响应 → (text, tool_calls)"""
        msg = response.get("message", {})
        text = msg.get("content", "") or ""
        tool_calls = []
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try: args = json.loads(args)
                except: args = {}
            tool_calls.append({
                "id": f"tc_{self._tool_id_counter}",
                "function": {"name": fn.get("name", ""), "arguments": args}
            })
            self._tool_id_counter += 1
        return text, tool_calls

    def _parse_deepseek(self, response: dict) -> tuple:
        """解析 DeepSeek (Anthropic) 响应 → (text, tool_calls)"""
        text = ""
        tool_calls = []
        for block in response.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", f"tc_{self._tool_id_counter}"),
                    "function": {"name": block.get("name", ""), "input": block.get("input", {})}
                })
                self._tool_id_counter += 1
        # Normalize: Anthropic uses "input", OpenAI format uses "arguments"
        for tc in tool_calls:
            if "input" in tc["function"] and "arguments" not in tc["function"]:
                tc["function"]["arguments"] = tc["function"]["input"]
        return text, tool_calls

    def _parse_openrouter(self, response: dict) -> tuple:
        """解析 OpenRouter (OpenAI) 响应 → (text, tool_calls)"""
        msg = response.get("choices", [{}])[0].get("message", {})
        text = msg.get("content", "") or ""
        tool_calls = []
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            args = fn.get("arguments", "{}")
            if isinstance(args, str):
                try: args = json.loads(args)
                except: args = {}
            tool_calls.append({
                "id": tc.get("id", f"tc_{self._tool_id_counter}"),
                "function": {"name": fn.get("name", ""), "arguments": args}
            })
            self._tool_id_counter += 1
        return text, tool_calls

    def _parse_fallback(self, response: dict) -> tuple:
        """从文本回复中提取 ```tool JSON 块"""
        msg = response.get("message", {})
        text = msg.get("content", "") or ""
        tool_calls = []
        # 查找 ```tool ... ``` 代码块
        import re
        pattern = r'```tool\s*\n(.*?)\n```'
        matches = re.findall(pattern, text, re.DOTALL)
        for m in matches:
            try:
                data = json.loads(m.strip())
                tool_calls.append({
                    "id": f"tc_{self._tool_id_counter}",
                    "function": {"name": data["name"], "arguments": data.get("args", {})}
                })
                self._tool_id_counter += 1
            except (json.JSONDecodeError, KeyError):
                pass
        # 也尝试 ```json
        pattern2 = r'```json\s*\n(.*?)\n```'
        matches2 = re.findall(pattern2, text, re.DOTALL)
        for m in matches2:
            try:
                data = json.loads(m.strip())
                if "name" in data and "args" in data:
                    tool_calls.append({
                        "id": f"tc_{self._tool_id_counter}",
                        "function": {"name": data["name"], "arguments": data["args"]}
                    })
                    self._tool_id_counter += 1
            except (json.JSONDecodeError, KeyError):
                pass
        # 去掉 tool 块，保留纯文本
        clean_text = re.sub(r'```(tool|json)\s*\n.*?\n```', '', text, flags=re.DOTALL).strip()
        return clean_text, tool_calls

    # ─── 工具执行 ───

    def _execute_tools(self, tool_calls: list) -> list:
        """批量执行工具，返回结果列表"""
        results = []
        for tc in tool_calls:
            fn = tc["function"]
            name = fn["name"]
            args = fn.get("arguments", fn.get("input", {}))
            if isinstance(args, str):
                try: args = json.loads(args)
                except: args = {}
            result = tools.execute(name, args)
            results.append({"tool_call_id": tc["id"], "name": name, "args": args, "result": result})
        return results

    def _chain_hints(self, exec_results: list) -> str:
        """v4.1+: 工具链 + 错误恢复 — 分析结果，生成下一步提示"""
        hints = []
        for er in exec_results:
            name = er["name"]
            res = er.get("result", {})
            if not res.get("ok"):
                err = res.get('error','')[:100]
                hints.append(f"❌ {name} 失败: {err}")
                # Error recovery hints — suggest concrete fixes
                if "not found" in err.lower() or "不存在" in err or "ENOENT" in err:
                    hints.append(f"→ 建议: 用 list_dir 确认路径是否存在，或尝试其他路径")
                elif "permission" in err.lower() or "denied" in err or "拒绝" in err:
                    hints.append(f"→ 建议: 尝试其他目录（如 ~/Desktop 或 ~/Downloads），或跳过此文件")
                elif "timeout" in err.lower() or "超时" in err:
                    hints.append(f"→ 建议: 简化操作重试，或分割成更小步骤")
                elif "ffmpeg" in err.lower() and "not found" in err.lower():
                    hints.append(f"→ 建议: 视频工具需要 ffmpeg，尝试用 shell 安装或跳过视频处理")
                else:
                    hints.append(f"→ 建议: 分析错误原因，尝试替代方案或跳过此步骤")
                continue
            # Auto-chain patterns
            if name == "list_dir" and res.get("items"):
                files = [i["name"] for i in res["items"][:5] if i["type"] == "file"]
                if files:
                    hints.append(f"list_dir 返回了文件: {', '.join(files)}，可以 read_file 查看内容")
            elif name == "find_files" and res.get("files"):
                hints.append(f"找到 {len(res['files'])} 个文件，可以 read_file 或继续筛选")
            elif name == "web_search" and res.get("results"):
                hints.append(f"搜索完成，可以 web_fetch 打开链接获取详情")
            elif name == "screenshot_find" and res.get("matches"):
                hints.append(f"定位到 {len(res['matches'])} 处文字，可以 click_text 自动点击")
            elif name == "system_info" and res.get("info"):
                info = res["info"]
                if info.get("disk_free_gb", 999) < 10:
                    hints.append("磁盘空间不足，建议清理临时文件")
                if info.get("ram_used_pct", 0) > 80:
                    hints.append("内存占用高，检查 list_processes 找大内存进程")
        return "\n".join(hints) if hints else ""

    # ─── Plan Mode ───

    def plan(self, task: str, system: str = "") -> dict:
        """生成执行计划后暂停，等待用户确认"""
        plan_prompt = f"""分析以下任务，生成逐步执行计划。只输出计划，不执行。

任务: {task}

输出格式（JSON 数组）:
[{{"step": 1, "action": "描述动作", "tools": ["需要的工具"], "reason": "为什么需要这步"}}]

规则:
- 3-6 步，每步明确可操作
- 先探索/调查，再修改/操作
- 有依赖关系的步骤按顺序排列
"""
        try:
            import urllib.request as _ur2
            body = json.dumps({
                "model": "qwen3:8b",
                "messages": [
                    {"role": "system", "content": "你是任务规划专家。输出纯 JSON 数组。"},
                    {"role": "user", "content": plan_prompt}
                ],
                "stream": False,
                "options": {"temperature": 0.3}
            }).encode()
            req = _ur2.Request("http://localhost:11434/api/chat", body,
                              headers={"Content-Type": "application/json"})
            resp = json.loads(_ur2.urlopen(req, timeout=30).read())
            content = resp.get("message", {}).get("content", "")
            import re
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                plan = json.loads(json_match.group())
                return {"ok": True, "plan": plan, "task": task}
        except Exception as e:
            return {"ok": False, "error": f"Plan generation failed: {e}"}

    # ─── Goal Check ───

    GOAL_CHECK_PROMPT = """检查任务是否真正完成。不要假装完成——如果还有未做的事，诚实说 NO。

原始任务: {task}

Agent 的最后回复: {last_text}

已完成的操作步骤（摘要）: {steps_summary}

只回复 YES 或 NO，然后一行简短理由。"""

    def _check_goal(self, task: str, last_text: str, steps_summary: str) -> bool:
        """用廉价模型检查任务是否真正完成"""
        try:
            import urllib.request as _ur3
            body = json.dumps({
                "model": "qwen3:8b",
                "messages": [
                    {"role": "system", "content": "你只回复 YES 或 NO，然后简短理由。不要废话。"},
                    {"role": "user", "content": self.GOAL_CHECK_PROMPT.format(
                        task=task, last_text=last_text[:2000], steps_summary=steps_summary[:500])}
                ],
                "stream": False,
                "options": {"temperature": 0.1}
            }).encode()
            req = _ur3.Request("http://localhost:11434/api/chat", body,
                              headers={"Content-Type": "application/json"})
            resp = json.loads(_ur3.urlopen(req, timeout=15).read())
            answer = resp.get("message", {}).get("content", "YES").strip().upper()
            return answer.startswith("YES")
        except Exception:
            return False  # Checker failure — don't trust, let agent continue

    def review(self, task: str, agent_output: str, steps: list = None) -> dict:
        """对抗审查 — 用第二个模型审查 Agent 输出"""
        steps_text = ""
        if steps:
            steps_text = "操作步骤:\n" + "\n".join(
                f"- turn {s.get('turn', '?')}: {str(s.get('final', ''))[:200] if s.get('final') else str([t.get('name','') for t in s.get('tools',[])])}"
                for s in steps[-5:]
            )
        try:
            import urllib.request as _ur4
            body = json.dumps({
                "model": "qwen3:8b",
                "messages": [
                    {"role": "system", "content": """你是严格的质量审查员。审查 Agent 输出，找出:
1. 是否遗漏了任务要求
2. 是否有事实错误或幻觉
3. 操作是否安全（没有删除重要文件等）
4. 建议改进的地方
输出 JSON: {"pass": true/false, "score": 1-10, "issues": ["问题1"], "suggestions": ["建议1"]}"""},
                    {"role": "user", "content": f"任务: {task}\n\nAgent 输出:\n{agent_output[:3000]}\n\n{steps_text}"}
                ],
                "stream": False,
                "options": {"temperature": 0.2}
            }).encode()
            req = _ur4.Request("http://localhost:11434/api/chat", body,
                              headers={"Content-Type": "application/json"})
            resp = json.loads(_ur4.urlopen(req, timeout=30).read())
            content = resp.get("message", {}).get("content", "")
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                review = json.loads(json_match.group())
                return {"ok": True, "review": review}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "Review parsing failed"}

    # ─── 主循环 ───

    def run(self, task: str, system: str = "") -> dict:
        """
        同步运行 Agent
        Returns: {success, result, turns, steps, model}
        """
        mt = self._model_type
        # 检测 Ollama 模型是否支持原生 tool calling
        use_ollama_tools = mt == "ollama" and "deepseek-r1" not in self._ollama_model
        is_fallback = (mt == "ollama" and not use_ollama_tools)

        # 初始化消息
        sys_content = AGENT_SYSTEM_FALLBACK if is_fallback else AGENT_SYSTEM
        if system:
            sys_content = sys_content + "\n\n用户上下文: " + system
        if HAS_RAG:
            try:
                rag_ctx = rag_mem.build_context(task, max_tokens=1500)
                if rag_ctx:
                    sys_content = sys_content + "\n\n" + rag_ctx
            except:
                pass

        self.messages = [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": task}
        ]

        steps = []

        for turn in range(self.max_turns):
            # 1. 调用 LLM
            try:
                if is_fallback:
                    resp = self._call_ollama_fallback()
                    text, tool_calls = self._parse_fallback(resp)
                elif mt == "ollama":
                    resp = self._call_ollama(use_tools=True)
                    text, tool_calls = self._parse_ollama(resp)
                elif mt == "deepseek":
                    resp = self._call_deepseek()
                    text, tool_calls = self._parse_deepseek(resp)
                elif mt == "openrouter":
                    resp = self._call_openrouter()
                    text, tool_calls = self._parse_openrouter(resp)
            except Exception as e:
                # LLM 调用失败
                steps.append({"turn": turn, "error": str(e)})
                err_msg = f"模型调用失败: {e}"
                # 尝试降级到 Ollama (更换 system prompt 以支持 tool markdown)
                if mt != "ollama":
                    try:
                        self.messages[0] = {"role": "system", "content": AGENT_SYSTEM_FALLBACK}
                        resp = self._call_ollama(use_tools=False)
                        text, tool_calls = self._parse_fallback(resp)
                    except:
                        return {"success": False, "result": err_msg, "turns": turn+1, "steps": steps}
                else:
                    return {"success": False, "result": err_msg, "turns": turn+1, "steps": steps}

            # 2. 有工具调用 → 执行
            if tool_calls:
                exec_results = self._execute_tools(tool_calls)
                steps.append({"turn": turn, "thinking": text[:200], "tools": exec_results})

                # 添加 assistant 消息（含 tool_calls）
                self.messages.append({
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": tool_calls
                })
                # 添加 tool 结果消息
                for er in exec_results:
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": er["tool_call_id"],
                        "content": json.dumps(er["result"], ensure_ascii=False)
                    })
                hint = self._chain_hints(exec_results)
                if hint:
                    self.messages.append({"role": "user", "content": f"[系统提示] {hint}"})
                continue

            # 3. 无工具调用 → 目标检测后决定是否完成
            if not text and not tool_calls:
                # Empty response — avoid infinite loop
                steps.append({"turn": turn, "final": True, "text": "(empty response)"})
                return {"success": False, "result": "Agent returned empty response", "turns": turn+1, "steps": steps}
            steps_summary = " · ".join(
                f"step{s.get('turn',0)}: {str(s.get('final',''))[:80] if s.get('final') else str([t['name'] for t in s.get('tools',[])])}"
                for s in steps[-3:]
            )
            if self._check_goal(task, text, steps_summary):
                steps.append({"turn": turn, "final": True, "text": text})
                return {
                    "success": True,
                    "result": text,
                    "turns": turn + 1,
                    "steps": steps,
                    "model": self.model_key
                }
            # Not done yet — push feedback and continue
            self.messages.append({"role": "assistant", "content": text})
            self.messages.append({"role": "user",
                "content": "[系统提示] 目标检测器认为任务未完成。请继续执行未完成的部分，不要重复已完成的工作。"})
            continue

        # 超过最大轮次
        return {
            "success": False,
            "result": f"达到最大轮次 ({self.max_turns})，任务未完成。已完成 {len(steps)} 步。",
            "turns": self.max_turns,
            "steps": steps,
            "model": self.model_key
        }

    def stream(self, task: str, system: str = ""):
        """
        流式运行 Agent — 生成事件流
        yield: {type: "thinking"|"tool_call"|"tool_result"|"text"|"done"|"error", ...}
        """
        mt = self._model_type
        use_ollama_tools = mt == "ollama" and "deepseek-r1" not in self._ollama_model
        is_fallback = (mt == "ollama" and not use_ollama_tools)

        sys_content = AGENT_SYSTEM_FALLBACK if is_fallback else AGENT_SYSTEM
        if system:
            sys_content = sys_content + "\n\n用户上下文: " + system
        if HAS_RAG:
            try:
                rag_ctx = rag_mem.build_context(task, max_tokens=1500)
                if rag_ctx:
                    sys_content = sys_content + "\n\n" + rag_ctx
            except:
                pass

        self.messages = [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": task}
        ]

        for turn in range(self.max_turns):
            yield {"type": "turn", "turn": turn}

            try:
                if is_fallback:
                    resp = self._call_ollama_fallback()
                    text, tool_calls = self._parse_fallback(resp)
                elif mt == "ollama":
                    text = ""
                    tool_calls = []
                    for token, final in self._call_ollama_stream(use_tools=True):
                        if token:
                            text += token
                            yield {"type": "token", "token": token, "turn": turn}
                        if final:
                            _, tool_calls = self._parse_ollama({"message": final})
                elif mt == "deepseek":
                    resp = self._call_deepseek()
                    text, tool_calls = self._parse_deepseek(resp)
                elif mt == "openrouter":
                    resp = self._call_openrouter()
                    text, tool_calls = self._parse_openrouter(resp)
            except Exception as e:
                yield {"type": "error", "error": f"模型调用失败: {e}", "turn": turn}
                return

            if text:
                yield {"type": "thinking", "text": text, "turn": turn}

            if tool_calls:
                exec_results = self._execute_tools(tool_calls)
                for er in exec_results:
                    yield {"type": "tool_call", "tool": er["name"], "args": er["args"]}
                    yield {"type": "tool_result", "tool": er["name"], "result": er["result"]}

                self.messages.append({
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": tool_calls
                })
                for er in exec_results:
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": er["tool_call_id"],
                        "content": json.dumps(er["result"], ensure_ascii=False)
                    })
                hint = self._chain_hints(exec_results)
                if hint:
                    self.messages.append({"role": "user", "content": f"[系统提示] {hint}"})
                continue

            # Goal check before declaring done
            if not text and not tool_calls:
                yield {"type": "error", "error": "Agent returned empty response"}
                return
            steps_summary = " · ".join(
                f"step{s.get('turn',0)}: {str(s.get('final',''))[:80] if s.get('final') else ''}"
                for s in [{"turn": turn, "final": text[:80]}]
            )
            if self._check_goal(task, text, steps_summary):
                yield {"type": "done", "text": text, "turns": turn + 1}
                return
            yield {"type": "goal_check", "msg": "目标未完成，继续..."}
            self.messages.append({"role": "assistant", "content": text})
            self.messages.append({"role": "user",
                "content": "[系统提示] 目标检测器认为任务未完成。请继续执行未完成的部分，不要重复已完成的工作。"})
            continue

        yield {"type": "error", "error": f"达到最大轮次 ({self.max_turns})"}


# ═══════ 便捷函数 ═══════

def run_agent(task: str, model: str = "deepseek", system: str = "") -> dict:
    """快速运行 Agent"""
    return Agent(model_key=model).run(task, system=system)

def stream_agent(task: str, model: str = "deepseek", system: str = ""):
    """快速流式运行 Agent"""
    return Agent(model_key=model).stream(task, system=system)


# ═══════ FastAPI 路由 ═══════

agent_router = None  # 由 model_orchestrator.py 挂载

def register_routes(app):
    """向 FastAPI app 注册 Agent 路由"""
    from fastapi.responses import JSONResponse, StreamingResponse
    from fastapi import Request

    @app.post("/api/agent/run")
    async def api_agent_run(request: Request):
        try:
            raw = await request.body()
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            data = {}
        task = data.get("task", "").strip()
        if not task:
            return JSONResponse({"error": "empty task"}, 400)
        model = data.get("model", "deepseek")
        system = data.get("system", "")
        agent = Agent(model_key=model)
        result = agent.run(task, system=system)
        return result

    @app.post("/api/agent/plan")
    async def api_agent_plan(request: Request):
        """生成执行计划（先规划再执行）"""
        try:
            raw = await request.body()
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            data = {}
        task = data.get("task", "").strip()
        if not task:
            return JSONResponse({"error": "empty task"}, 400)
        model = data.get("model", "deepseek")
        system = data.get("system", "")
        agent = Agent(model_key=model)
        return agent.plan(task, system=system)

    @app.post("/api/agent/review")
    async def api_agent_review(request: Request):
        """对抗审查 Agent 输出"""
        try:
            raw = await request.body()
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            data = {}
        task = data.get("task", "").strip()
        output = data.get("output", "").strip()
        if not task or not output:
            return JSONResponse({"error": "task and output required"}, 400)
        agent = Agent()
        return agent.review(task, output, data.get("steps"))

    @app.post("/api/agent/stream")
    async def api_agent_stream(request: Request):
        try:
            raw = await request.body()
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            data = {}
        task = data.get("task", "").strip()
        model = data.get("model", "deepseek")
        system = data.get("system", "")

        async def generate():
            try:
                agent = Agent(model_key=model)
                for event in agent.stream(task, system=system):
                    try:
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    except (TypeError, ValueError) as je:
                        # JSON 序列化失败 — 截断可能超长的字段
                        safe = {}
                        for k, v in event.items():
                            if isinstance(v, str) and len(v) > 5000:
                                safe[k] = v[:5000] + '...[truncated]'
                            elif isinstance(v, (dict, list)):
                                try:
                                    json.dumps(v)
                                    safe[k] = v
                                except:
                                    safe[k] = str(v)[:1000]
                            else:
                                safe[k] = v
                        yield f"data: {json.dumps(safe, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ═══════ Background Agent Tasks ═══════
    import threading, uuid as _uuid

    _agent_tasks = {}  # task_id → {status, result, model, created_at}
    _task_lock = threading.Lock()

    @app.post("/api/agent/task")
    async def api_agent_task(request: Request):
        """后台异步运行 Agent，立即返回 task_id"""
        try:
            raw = await request.body()
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            data = {}
        task_text = data.get("task", "").strip()
        if not task_text:
            return JSONResponse({"error": "empty task"}, 400)
        model = data.get("model", "deepseek")
        system = data.get("system", "")
        task_id = str(_uuid.uuid4())[:8]

        with _task_lock:
            _agent_tasks[task_id] = {"status": "running", "result": None, "model": model,
                                      "task": task_text[:100], "created_at": time.time()}

        def _run_background():
            try:
                agent = Agent(model_key=model)
                result = agent.run(task_text, system=system)
                with _task_lock:
                    _agent_tasks[task_id]["status"] = "done" if result.get("success") else "failed"
                    _agent_tasks[task_id]["result"] = result.get("result", "")[:2000]
                    _agent_tasks[task_id]["turns"] = result.get("turns", 0)
            except Exception as e:
                with _task_lock:
                    _agent_tasks[task_id]["status"] = "error"
                    _agent_tasks[task_id]["error"] = str(e)[:500]
            # Notify user
            try:
                from notify import notify_windows
                status = _agent_tasks[task_id]["status"]
                notify_windows(f"Agent [{status.upper()}]", _agent_tasks[task_id].get("result", "")[:100])
            except:
                pass

        threading.Thread(target=_run_background, daemon=True).start()
        return {"ok": True, "task_id": task_id, "status": "running"}

    @app.get("/api/agent/task/{task_id}")
    async def api_agent_task_status(task_id: str):
        with _task_lock:
            task = _agent_tasks.get(task_id)
        if not task:
            return {"ok": False, "error": "task not found"}
        return {"ok": True, **task}

    @app.get("/api/agent/tasks")
    async def api_agent_task_list():
        with _task_lock:
            return {"ok": True, "tasks": list(_agent_tasks.values())}

    @app.get("/api/tools/health")
    async def api_tools_health():
        """工具健康检查：检测依赖可用性"""
        health = {"total": tools.TOOLS.__len__(), "available": 0, "unavailable": [], "details": {}}

        # Check ffmpeg
        ff = tools._find_ffmpeg()
        health["details"]["ffmpeg"] = bool(ff)
        if ff:
            health["details"]["ffmpeg_path"] = ff

        # Check dependencies
        for mod, pkg in [("PIL", "Pillow"), ("pptx", "python-pptx"),
                          ("ezdxf", "ezdxf"), ("psutil", "psutil")]:
            try:
                __import__(mod)
                health["details"][pkg] = True
            except ImportError:
                health["details"][pkg] = False

        # Check tesseract
        import shutil as _sh
        tess = _sh.which("tesseract")
        if not tess:
            for p in ["C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
                      "C:\\Tesseract-OCR\\tesseract.exe"]:
                if _os.path.exists(p):
                    tess = p
                    break
        health["details"]["tesseract"] = bool(tess)

        # Count available tools (ones whose deps are met)
        for name in tools.TOOLS:
            if name.startswith("video_") and not ff:
                health["unavailable"].append(name)
            elif name == "screenshot" and not health["details"].get("Pillow", False):
                health["unavailable"].append(name)  # has PowerShell fallback actually
            else:
                health["available"] += 1

        health["available"] = health["total"] - len(health["unavailable"])
        return health

    # ═══════ v4.0 Routes: RAG, Plugins, MCP, Email ═══════

    @app.get("/api/rag/search")
    async def api_rag_search(q: str = "", top_k: int = 5):
        try:
            from local_rag import local_rag as lr
            results = lr.search(q, top_k)
            return {"ok": True, "results": results}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/rag/index")
    async def api_rag_index(request: Request):
        try:
            data = await request.json()
            path = data.get("path", os.path.expanduser("~/Documents"))
            from local_rag import local_rag as lr
            result = lr.index_directory(path)
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/rag/stats")
    async def api_rag_stats():
        try:
            from local_rag import local_rag as lr
            return {"ok": True, "stats": lr.stats()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/plugins")
    async def api_plugins():
        try:
            from plugin_manager import pm
            return {"ok": True, "plugins": pm.list_plugins(), "available": pm.discover()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/plugins/{name}/load")
    async def api_plugin_load(name: str):
        try:
            from plugin_manager import pm
            ok = pm.load(name)
            return {"ok": ok, "name": name}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/plugins/{name}/unload")
    async def api_plugin_unload(name: str):
        try:
            from plugin_manager import pm
            pm.unload(name)
            return {"ok": True, "name": name}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/mcp/connect")
    async def api_mcp_connect(request: Request):
        try:
            data = await request.json()
            name = data.get("name", "")
            command = data.get("command", "")
            url = data.get("url", "")
            if command:
                ok = mcp_client.connect_stdio(name, command)
            elif url:
                ok = mcp_client.connect_sse(name, url)
            else:
                return {"ok": False, "error": "Need command or url"}
            return {"ok": ok, "name": name}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/mcp/servers")
    async def api_mcp_servers():
        try:
            return {"ok": True, "servers": mcp_client.server_status(),
                    "tools": len(mcp_client.list_tools())}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/rag/memory")
    async def api_rag_memory(query: str = "", action: str = "recall"):
        try:
            if action == "recall" and query:
                results = rag_mem.recall(query)
                return {"ok": True, "results": [{k: str(v) for k, v in r.items()} for r in results]}
            elif action == "stats":
                return {"ok": True, "stats": rag_mem.stats()}
            return {"ok": False, "error": "Need query for recall, or action=stats"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/rag/memory")
    async def api_rag_memory_store(request: Request):
        try:
            data = await request.json()
            content = data.get("content", "")
            category = data.get("category", "general")
            if content:
                rag_mem.remember(content, category)
                return {"ok": True}
            return {"ok": False, "error": "Need content"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ═══════ v4.0: Real-time Monitoring ═══════

    @app.get("/api/monitoring")
    async def api_monitoring():
        """实时系统监控数据"""
        info = {}
        try:
            # CPU
            try:
                import psutil
                info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
                vmem = psutil.virtual_memory()
                info["ram_total_gb"] = round(vmem.total / (1024**3), 1)
                info["ram_used_gb"] = round(vmem.used / (1024**3), 1)
                info["ram_percent"] = vmem.percent
            except:
                info["cpu_percent"] = 0
                info["ram_percent"] = 0

            # Process count
            try:
                info["process_count"] = len(psutil.pids())
            except:
                info["process_count"] = 0

            # GPU via nvidia-smi if available
            try:
                import shutil as _sh
                nvsmi = _sh.which("nvidia-smi")
                if nvsmi:
                    r = subprocess.run([nvsmi, "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                                       "--format=csv,noheader,nounits"],
                                      capture_output=True, text=True, timeout=5,
                                      creationflags=subprocess.CREATE_NO_WINDOW if _os.name == "nt" else 0)
                    parts = r.stdout.strip().split(",")
                    if len(parts) >= 4:
                        info["gpu_percent"] = int(float(parts[0].strip()))
                        info["gpu_vram_used_mb"] = int(float(parts[1].strip()))
                        info["gpu_vram_total_mb"] = int(float(parts[2].strip()))
                        info["gpu_temp"] = int(float(parts[3].strip()))
            except:
                pass

            # Disk
            try:
                import shutil as sd
                disk = sd.disk_usage(_os.path.expanduser("~"))
                info["disk_total_gb"] = round(disk.total / (1024**3), 1)
                info["disk_used_gb"] = round(disk.used / (1024**3), 1)
            except:
                pass

            # Agent background tasks
            try:
                from notify import background_tasks
                info["background_tasks"] = len(background_tasks) if background_tasks else 0
            except:
                info["background_tasks"] = 0

            return {"ok": True, "info": info}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.get("/api/monitoring/stream")
    async def api_monitoring_stream():
        """SSE 实时推送系统监控数据（每 2 秒）"""
        async def generate():
            import asyncio as _aio
            while True:
                try:
                    info = {}
                    try:
                        import psutil
                        info["cpu_percent"] = psutil.cpu_percent(interval=0.3)
                        vmem = psutil.virtual_memory()
                        info["ram_total_gb"] = round(vmem.total / (1024**3), 1)
                        info["ram_used_gb"] = round(vmem.used / (1024**3), 1)
                        info["ram_percent"] = vmem.percent
                        info["process_count"] = len(psutil.pids())
                    except:
                        info["cpu_percent"] = 0
                        info["ram_percent"] = 0
                    try:
                        import shutil as _sh
                        nvsmi = _sh.which("nvidia-smi")
                        if nvsmi:
                            r = subprocess.run([nvsmi, "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                                               "--format=csv,noheader,nounits"],
                                              capture_output=True, text=True, timeout=3,
                                              creationflags=subprocess.CREATE_NO_WINDOW if _os.name == "nt" else 0)
                            parts = r.stdout.strip().split(",")
                            if len(parts) >= 4:
                                info["gpu_percent"] = int(float(parts[0].strip()))
                                info["gpu_vram_used_mb"] = int(float(parts[1].strip()))
                                info["gpu_vram_total_mb"] = int(float(parts[2].strip()))
                                info["gpu_temp"] = int(float(parts[3].strip()))
                    except:
                        pass
                    try:
                        import shutil as sd
                        disk = sd.disk_usage(_os.path.expanduser("~"))
                        info["disk_total_gb"] = round(disk.total / (1024**3), 1)
                        info["disk_used_gb"] = round(disk.used / (1024**3), 1)
                    except:
                        pass
                    yield f"data: {json.dumps({'ok': True, 'info': info}, ensure_ascii=False)}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False)}\n\n"
                await _aio.sleep(2)
        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ═══════ v4.1: Multi-Agent Team ═══════

    @app.get("/api/team/roles")
    async def api_team_roles():
        try:
            from multi_agent import AgentTeam
            team = AgentTeam()
            return {"ok": True, "roles": team.get_roles()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/team/stream")
    async def api_team_stream(request: Request):
        try:
            data = await request.json()
        except:
            data = {}
        task = data.get("task", "").strip()
        if not task:
            return JSONResponse({"error": "empty task"}, 400)

        async def generate():
            try:
                from multi_agent import AgentTeam
                team = AgentTeam()
                for event in team.stream(task):
                    try:
                        yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                    except:
                        yield f"data: {json.dumps({'type': 'error', 'error': 'serialize'}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ═══════ CLI ═══════

if __name__ == "__main__":
    import sys
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "列出C盘根目录的内容"
    print(f"Agent task: {task}")
    print("=" * 50)
    for event in stream_agent(task, model="deepseek"):
        t = event.get("type")
        if t == "thinking":
            print(f"\n💭 {event['text'][:300]}")
        elif t == "tool_call":
            print(f"🔧 {event['tool']}({json.dumps(event['args'], ensure_ascii=False)})")
        elif t == "tool_result":
            r = event['result']
            ok = "✅" if r.get("ok") else "❌"
            preview = json.dumps(r, ensure_ascii=False)[:200]
            print(f"   {ok} {preview}")
        elif t == "done":
            print(f"\n{'='*50}")
            print(f"完成 ({event['turns']} 轮): {event['text'][:500]}")
        elif t == "error":
            print(f"\n❌ {event['error']}")
    print()
