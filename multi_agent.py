"""
AI Suite — Multi-Agent Collaboration (v4.1)
AgentTeam: 任务分解 → 并行执行 → 结果融合
角色专家: researcher / coder / operator / general
用法:
  from multi_agent import AgentTeam
  team = AgentTeam()
  for event in team.stream("分析C盘空间占用并清理临时文件"):
      print(event)
"""

import json, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Generator

# ═══════ Agent Role Definitions ═══════

ROLES = {
    "researcher": {
        "description": "信息研究员 — 搜索、阅读、总结",
        "system_prompt": """你是信息研究员。专注收集和分析信息。
工具偏好: web_search, web_fetch, read_file, list_dir, find_files
输出: 整理好的调查结果和关键发现。""",
        "preferred_tools": ["web_search", "web_fetch", "read_file", "list_dir", "find_files",
                           "system_info", "clipboard_read"],
        "model": "deepseek"
    },
    "coder": {
        "description": "代码工程师 — 编写脚本、处理数据、自动化",
        "system_prompt": """你是代码工程师。专注编写和执行代码解决问题。
工具偏好: shell, run_python, write_file, read_file
输出: 可工作的代码和运行结果。""",
        "preferred_tools": ["shell", "run_python", "write_file", "read_file", "list_dir"],
        "model": "deepseek"
    },
    "operator": {
        "description": "桌面操作员 — 操控窗口、文件、系统",
        "system_prompt": """你是桌面操作员。专注操作 Windows 桌面和文件。
工具偏好: click, type_text, press_key, screenshot, window_control, copy_file, move_file, delete_file
输出: 操作完成状态和结果。""",
        "preferred_tools": ["click", "type_text", "press_key", "screenshot", "get_windows",
                           "focus_window", "window_control", "copy_file", "move_file", "delete_file",
                           "launch_app", "system_info", "list_processes"],
        "model": "ollama:qwen3:8b"  # 本地快速响应
    },
    "general": {
        "description": "通用助手 — 协调、总结、复杂推理",
        "system_prompt": """你是通用 AI 助手。负责协调任务和复杂推理。
可以使用所有工具。当其他专家完成任务后，你会综合分析结果。""",
        "preferred_tools": [],  # all tools
        "model": "deepseek"
    }
}

# ═══════ Task Decomposer ═══════

DECOMPOSE_PROMPT = """你是一个任务分解专家。把用户任务分解为 1-4 个子步骤，分配给合适的角色专家。

可用角色: researcher(信息搜索/分析), coder(编写脚本/代码), operator(桌面操作/文件管理), general(综合推理)

规则:
- 简单任务用 1 个角色，复杂任务可以 2-4 个
- 需要搜索+写代码的任务：researcher 先搜，coder 后写
- 有依赖关系的标 depends_on (数组，0开始索引)
- 纯粹对话/问答用 general

输出 JSON 数组，只输出 JSON：
[{"role": "researcher", "task": "搜索GPU价格", "depends_on": []}]

用户任务: {task}
"""

def decompose_task(task: str) -> List[Dict]:
    """LLM 驱动任务分解，降级到关键词匹配"""
    # Try LLM decomposition first
    try:
        import urllib.request as _ur
        body = json.dumps({
            "model": "qwen3:8b",
            "messages": [
                {"role": "system", "content": "输出纯 JSON 数组。不要解释。"},
                {"role": "user", "content": DECOMPOSE_PROMPT.format(task=task)}
            ],
            "stream": False,
            "options": {"temperature": 0.3}
        }).encode()
        req = _ur.Request("http://localhost:11434/api/chat", body,
                          headers={"Content-Type": "application/json"})
        resp = json.loads(_ur.urlopen(req, timeout=30).read())
        content = resp.get("message", {}).get("content", "")
        # Extract JSON from response (may be wrapped in markdown)
        import re
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            steps = json.loads(json_match.group())
            if isinstance(steps, list) and len(steps) > 0:
                # Validate and normalize
                valid = []
                for i, s in enumerate(steps):
                    if isinstance(s, dict) and "role" in s and "task" in s:
                        role = s["role"] if s["role"] in ROLES else "general"
                        deps = s.get("depends_on", [])
                        valid.append({"role": role, "task": s["task"],
                                      "depends_on": deps if isinstance(deps, list) else []})
                if valid:
                    return valid
    except Exception:
        pass

    # Fallback: keyword heuristic
    steps = []

    task_lower = task.lower()

    if any(w in task_lower for w in ["搜索", "查一下", "查找", "研究", "调研", "信息", "资料", "最新", "search", "find", "research"]):
        steps.append({"role": "researcher", "task": "搜索并收集信息: " + task})

    if any(w in task_lower for w in ["写代码", "脚本", "编程", "python脚本", "自动化脚本", "代码实现", "运行命令", "执行命令", "code", "script"]):
        steps.append({"role": "coder", "task": "编写代码或脚本处理: " + task})

    if any(w in task_lower for w in ["打开文件", "创建文件", "删除文件", "移动文件", "清理文件夹", "整理文件夹",
                                      "桌面清理", "窗口", "点击", "截图", "操控", "操作文件", "文件管理",
                                      "file", "folder", "window", "click", "clean disk", "clean folder"]):
        steps.append({"role": "operator", "task": "操作文件或桌面: " + task})

    if any(w in task_lower for w in ["邮件", "日历", "email", "calendar", "发邮件", "收邮件"]):
        steps.append({"role": "operator", "task": "处理邮件/日历: " + task})

    if any(w in task_lower for w in ["视频", "video", "剪辑", "裁剪", "压缩"]):
        steps.append({"role": "coder", "task": "处理视频: " + task})

    # If no specialization matched, use general
    if not steps:
        steps.append({"role": "general", "task": task})

    # Always add a synthesizer if multiple steps
    if len(steps) > 1:
        dep_indices = list(range(len(steps)))  # all existing steps
        steps.append({"role": "general", "task": "综合分析上述结果，给出最终答案。原始任务: " + task,
                       "depends_on": dep_indices})

    return steps

# ═══════ AgentTeam ═══════

class AgentTeam:
    def __init__(self, max_parallel: int = 4):
        self.max_parallel = max_parallel
        self.results: Dict[str, dict] = {}
        self.events: list = []

    def run(self, task: str) -> dict:
        """同步运行多 Agent 团队"""
        steps = decompose_task(task)
        self.events = [{"type": "plan", "steps": len(steps), "detail": steps}]

        # Separate parallel vs dependent steps
        parallel_steps = [s for s in steps if not s.get("depends_on")]
        dependent_steps = [s for s in steps if s.get("depends_on")]

        results = {}

        # Phase 1: Run parallel steps
        if parallel_steps:
            with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(parallel_steps))) as pool:
                futures = {}
                for i, step in enumerate(parallel_steps):
                    f = pool.submit(self._run_agent, step["role"], step["task"], f"agent_{i}")
                    futures[f] = (i, step)

                for future in as_completed(futures):
                    i, step = futures[future]
                    try:
                        result = future.result()
                        results[f"step_{i}"] = {
                            "role": step["role"],
                            "task": step["task"],
                            "result": result
                        }
                        self.events.append({"type": "step_done", "agent": step["role"],
                                           "task": step["task"][:80], "result": result})
                    except Exception as e:
                        results[f"step_{i}"] = {"role": step["role"], "error": str(e)}
                        self.events.append({"type": "step_error", "agent": step["role"], "error": str(e)})

        # Phase 2: Run dependent steps (with context from phase 1)
        for step in dependent_steps:
            context = json.dumps(results, ensure_ascii=False)[:3000]
            full_task = f"{step['task']}\n\n前期结果:\n{context}"
            try:
                result = self._run_agent(step["role"], full_task, "synthesizer")
                key = f"step_{len(results)}"
                results[key] = {"role": step["role"], "task": step["task"], "result": result}
                self.events.append({"type": "step_done", "agent": step["role"], "result": result})
            except Exception as e:
                self.events.append({"type": "step_error", "agent": step["role"], "error": str(e)})

        # Build final result
        # 取最后一个成功步骤的结果，而非依赖长度索引
        final_keys = sorted([k for k in results if results.get(k)], key=lambda k: int(k.split("_")[1]))
        final = results.get(final_keys[-1], {}).get("result", {}) if final_keys else {}
        if not final or not final.get("success"):
            final = {"success": True, "text": self._build_summary(results), "steps": len(steps)}

        self.events.append({"type": "done", "steps": len(steps), "result": final})
        return final

    def stream(self, task: str):
        """流式运行多 Agent 团队"""
        for event in self._stream_internal(task):
            yield event

    def _stream_internal(self, task: str):
        steps = decompose_task(task)
        yield {"type": "plan", "steps": len(steps), "detail": steps}

        parallel_steps = [s for s in steps if not s.get("depends_on")]
        dependent_steps = [s for s in steps if s.get("depends_on")]
        results = {}

        # Phase 1: Parallel
        if parallel_steps:
            with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(parallel_steps))) as pool:
                futures = {}
                for i, step in enumerate(parallel_steps):
                    f = pool.submit(self._run_agent_stream, step["role"], step["task"], f"agent_{i}")
                    futures[f] = (i, step)

                for future in as_completed(futures):
                    i, step = futures[future]
                    try:
                        agent_events, agent_result = future.result()
                        results[f"step_{i}"] = {"role": step["role"], "task": step["task"], "result": agent_result}
                        for evt in agent_events:
                            evt["agent"] = step["role"]
                            evt["agent_id"] = i
                            yield evt
                        yield {"type": "step_done", "agent": step["role"], "agent_id": i,
                               "task": step["task"][:80], "result": agent_result}
                    except Exception as e:
                        yield {"type": "step_error", "agent": step["role"], "agent_id": i, "error": str(e)}

        # Phase 2: Dependent
        for step in dependent_steps:
            # 过滤失败步骤，扩容上下文至 1500 字符
            context = json.dumps({
                k: v.get("result", {}).get("text", "")[:1500]
                for k, v in results.items()
                if v and not v.get("result", {}).get("error")
            }, ensure_ascii=False)
            full_task = f"{step['task']}\n\n前期结果:\n{context}"
            try:
                agent_events, agent_result = self._run_agent_stream(step["role"], full_task, "synthesizer")
                key = f"step_{len(results)}"
                results[key] = {"role": step["role"], "task": step["task"], "result": agent_result}
                for evt in agent_events:
                    evt["agent"] = step["role"]
                    evt["agent_id"] = "synthesizer"
                    yield evt
                yield {"type": "step_done", "agent": step["role"], "agent_id": "synthesizer", "result": agent_result}
            except Exception as e:
                yield {"type": "step_error", "agent": step["role"], "agent_id": "synthesizer", "error": str(e)}

        # 取最后一个成功步骤的结果，而非依赖长度索引
        final_keys = sorted([k for k in results if results.get(k)], key=lambda k: int(k.split("_")[1]))
        final = results.get(final_keys[-1], {}).get("result", {}) if final_keys else {}
        if not final or not final.get("success"):
            final = {"success": True, "text": self._build_summary(results), "steps": len(steps)}
        yield {"type": "done", "steps": len(steps), "result": final}

    def _run_agent(self, role: str, task: str, agent_id: str) -> dict:
        """Run single agent synchronously"""
        from agent import Agent
        role_def = ROLES.get(role, ROLES["general"])
        agent = Agent(model_key=role_def["model"])
        result = agent.run(task, system=role_def["system_prompt"])
        return result

    def _run_agent_stream(self, role: str, task: str, agent_id: str):
        """Run single agent, collect events and result"""
        from agent import Agent
        role_def = ROLES.get(role, ROLES["general"])
        agent = Agent(model_key=role_def["model"])
        events = []
        final_result = {"success": True, "text": ""}
        try:
            for event in agent.stream(task, system=role_def["system_prompt"]):
                events.append(event)
                if event.get("type") == "done":
                    final_result = {"success": True, "text": event.get("text", ""),
                                  "turns": event.get("turns", 0)}
        except Exception as e:
            final_result = {"success": False, "error": str(e)}
            events.append({"type": "error", "error": str(e)})
        return events, final_result

    def _build_summary(self, results: dict) -> str:
        """Build summary text from all agent results"""
        parts = []
        for key, data in results.items():
            role = data.get("role", "unknown")
            result = data.get("result", {})
            text = result.get("text", result.get("result", ""))
            if text:
                parts.append(f"## {role}\n{str(text)[:500]}")
        return "\n\n".join(parts)

    def get_roles(self) -> List[Dict]:
        """返回可用角色"""
        return [{"id": k, "description": v["description"], "model": v["model"],
                 "tools": len(v["preferred_tools"])} for k, v in ROLES.items()]


# ═══════ Global instance ═══════

team = AgentTeam()

# ═══════ CLI ═══════

if __name__ == "__main__":
    import sys
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "分析C盘空间占用"
    print(f"Multi-Agent Task: {task}")
    print("=" * 60)
    for event in AgentTeam().stream(task):
        t = event.get("type")
        if t == "plan":
            print(f"\n📋 分解为 {event['steps']} 步:")
            for s in event["detail"]:
                dep = f" (依赖: {s.get('depends_on')})" if s.get("depends_on") else ""
                print(f"  [{s['role']}] {s['task'][:80]}{dep}")
        elif t == "thinking":
            print(f"  💭 [{event.get('agent','?')}] {event.get('text','')[:200]}")
        elif t == "tool_call":
            print(f"  🔧 [{event.get('agent','?')}] {event.get('tool','?')}({json.dumps(event.get('args',{}), ensure_ascii=False)[:100]})")
        elif t == "tool_result":
            r = event.get('result', {})
            ok = "✅" if r.get("ok") else "❌"
            print(f"     {ok}")
        elif t == "step_done":
            r = event.get('result', {})
            ok = "✅" if r.get('success') or r.get('ok') else "❌"
            print(f"  {ok} [{event.get('agent','?')}] 完成")
        elif t == "step_error":
            print(f"  ❌ [{event.get('agent','?')}] {event.get('error','')[:100]}")
        elif t == "done":
            print(f"\n{'=' * 60}")
            final = event.get('result', {})
            print(f"完成 ({event['steps']} 步):")
            print(final.get('text', str(final)[:500]))
        elif t == "error":
            print(f"❌ {event.get('error','')}")
    print()
