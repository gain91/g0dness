"""
AI Suite — Agent Core (v3.0)
ReAct 循环：思考→工具调用→观察→重复
支持 Ollama 本地 / DeepSeek V4 / OpenRouter 云端
"""
import json
import urllib.request as ur
from typing import Generator, Dict, Any, List, Optional
import tools
import hw_monitor

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
        # Build messages — skip system from self.messages (already adding our own)
        msgs = [{"role": "system", "content": CACHE_SYSTEM_PROMPT + "\n" + AGENT_SYSTEM}]
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

    # ─── 主循环 ───

    def run(self, task: str, system: str = "") -> dict:
        """
        同步运行 Agent
        Returns: {success, result, turns, steps, model}
        """
        mt = self._model_type
        # 检测 Ollama 模型是否支持原生 tool calling
        use_ollama_tools = mt == "ollama" and self._ollama_model not in (
            "deepseek-r1:14b",  # DeepSeek-R1 不支持原生 tool calling
        )
        is_fallback = (mt == "ollama" and not use_ollama_tools)

        # 初始化消息
        sys_content = AGENT_SYSTEM_FALLBACK if is_fallback else AGENT_SYSTEM
        if system:
            sys_content = sys_content + "\n\n用户上下文: " + system

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
                # 尝试降级到 Ollama
                if mt != "ollama":
                    try:
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
                continue

            # 3. 无工具调用 → 任务完成
            steps.append({"turn": turn, "final": True, "text": text})
            return {
                "success": True,
                "result": text,
                "turns": turn + 1,
                "steps": steps,
                "model": self.model_key
            }

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
        use_ollama_tools = mt == "ollama" and self._ollama_model not in (
            "deepseek-r1:14b",
        )
        is_fallback = (mt == "ollama" and not use_ollama_tools)

        sys_content = AGENT_SYSTEM_FALLBACK if is_fallback else AGENT_SYSTEM
        if system:
            sys_content = sys_content + "\n\n用户上下文: " + system

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
                    resp = self._call_ollama(use_tools=True)
                    text, tool_calls = self._parse_ollama(resp)
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
                continue

            yield {"type": "done", "text": text, "turns": turn + 1}
            return

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
