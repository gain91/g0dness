---
name: ai-suite-desktop
description: "AI Suite v4.1 — Tauri 桌面 AI 套件：53 工具 + 多 Agent + MCP + 自进化 + 角色预设 + 对话/生图/生视频"
metadata:
  type: project
  originSessionId: d85639fc-8bf2-45a4-998a-ca4f3982c043
---

# AI Suite Desktop v4.1

Windows 11, RTX 5070 Ti 12GB VRAM, Python 3.12.

## 架构

```
AI_Suite.exe (Tauri 原生, 6MB)
  ├─ Ollama serve (如未运行)
  ├─ python gen_web.py           → FastAPI :5000 (Chat UI + 生图/生视频)
  ├─ python model_orchestrator.py → FastAPI :5001 (多模型编排 + Agent + AIGateway)
  ├─ python mcp_server.py --sse  → :5100 (MCP Server, 可选)
  └─ webview 加载 dist/index.html → 轮询 /api/status → 跳转 /chat
```

GUI: Tauri webview，托盘隐藏，Ctrl+Shift+A 全局热键呼出，单实例 Mutex。

## 运行服务

| Port | 服务 | 文件 |
|------|------|------|
| 11434 | Ollama | 自启 |
| 5000 | gen_web (FastAPI) | `gen_web.py` |
| 5001 | model_orchestrator (FastAPI) | `model_orchestrator.py` |
| 5100 | MCP SSE Server (可选) | `mcp_server.py --sse` |
| 8188 | ComfyUI | gen_web 按需启动 |

## 前端 (`ollama-chat.html`)

设计: ChatGPT Desktop + Raycast + Linear — 中性灰白底，靛蓝点缀，玻璃态顶栏。

**四模式:** ? 对话 ? 生图 ? 生视频 ? Agent

**面板:** ? Claude Code ? Codex ? ? 实时监控(CPU/GPU/RAM) ? 模型管理 ? 调度 ? 语音 ? LAN QR ? 三主题

**v4.1 UI 改进:** 首次引导页、Agent 模板(8个)、快捷工具(对话模式🔧)、后台任务轮询、安全转义。

## 模型清单

**本地 Ollama:** `deepseek-r1:14b`(默认) ? `qwen3:8b` ? `huihui_ai/qwen3-abliterated:8b`(无审查) ? `lingmo-uncensored:latest` ? `lingmo-writer:latest`

**OpenRouter 云端:** `claude`(Fable 5) ? `claude-sonnet`(4.6) ? `claude-haiku`(4.5) ? `gpt`(5.5) ? `gpt-mini`(4o-mini) ? `gemini`(3.5 Flash) ? `gemini-fast`(2.5 Flash)

**DeepSeek 直连:** `deepseek-v4-pro` (Anthropic Messages API, 100万 ctx)

**火山引擎:** 生图 `seedream3/4/5` ? 生视频 `seedance`(2.0) ? `wan_i2v`(14B)

## 关键文件

| 文件 | 作用 |
|------|------|
| `gen_web.py` | FastAPI :5000 — Chat HTML + 生图/生视频/上传/历史 |
| `model_orchestrator.py` | FastAPI :5001 — 多模型路由 + Agent + AIGateway + 技能市场 |
| `agent.py` | Agent 核心 v4.1 — ReAct + 规划模式 + 目标检测 + 对抗审查 + 后台任务 + 自进化 |
| `tools.py` | 工具系统 — 47→53 MCP 工具 (含 MarkItDown 集成) |
| `multi_agent.py` | 多 Agent 协作 — AgentTeam + LLM 驱动任务分解 |
| `mcp_server.py` | MCP Server — stdio + SSE 暴露所有工具 |
| `mcp_client.py` | MCP Client — Agent 连接外部 MCP 服务器 |
| `rag_memory.py` | RAG 记忆 — 向量嵌入 + 语义检索 |
| `local_rag.py` | 本地文档索引 — txt/pdf/docx/代码 |
| `plugin_manager.py` | 插件系统 — Python 热加载 + 文件监控 |
| `email_tools.py` | 邮件工具 — Outlook 发/收/日历/联系人 (+5) |
| `db.py` | SQLite — 对话记忆持久化 |
| `memory_agent.py` | 学习记忆 + 自进化 — 偏好/反馈/技能自创建/Curator |
| `scheduler.py` | 定时调度 — Cron + 自然语言 |
| `notify.py` | 通知系统 — Windows Toast / VBS Popup |
| `file_watcher.py` | 文件监工 — 监控 + OCR + Agent 处理 |
| `hw_monitor.py` | 硬件监测 — RAM/VRAM 智能路由 |
| `key_vault.py` | 密钥加密 — AES-256-CBC |
| `ollama-chat.html` | 前端 UI — 四模式 + 工具面板 + 仪表盘 + 引导页 |
| `test_tools.py` | 冒烟测试 — 37/37 全过 |
| `ai-suite-tauri/` | Tauri 壳 — Rust 源码 + 构建配置 |

## Agent v4.1 核心能力

| 功能 | 说明 |
|------|------|
| ReAct 循环 | 思考→工具调用→观察→重复 (max 15 轮, 目标检测提前终止) |
| 规划模式 | `/api/agent/plan` — 先规划再执行 |
| 目标检测 | qwen3:8b 每轮检查任务是否完成 |
| 对抗审查 | `/api/agent/review` — 第二个模型审查输出 |
| 后台任务 | `/api/agent/task` — 异步执行 + 轮询 |
| 4 模型后端 | DeepSeek/Ollama/OpenRouter + 降级链 |
| SSE 流式 | 对话 + Agent token 级别流式 |
| RAG 记忆 | 向量嵌入 + 语义上下文注入 (run + stream) |
| 错误恢复 | 工具失败 → 分析原因 → 自动建议修复 |
| 工具链 | list_dir → prompt read_file, search → prompt fetch, 磁盘低 → 建议清理 |

## AI Gateway (reactive-resume 模式)

| 功能 | 说明 |
|------|------|
| 统一接口 | `AIGateway.chat()` — 单入口多提供商 |
| 降级链 | DeepSeek→Ollama, OpenRouter→Ollama |
| 用量统计 | 调用次数 + token 估算 |
| 健康检查 | `/api/gateway/health` 各提供商可用性 |

## 自进化系统 (Hermes Agent 模式)

| 组件 | 说明 |
|------|------|
| Skill Auto-Creation | Agent 成功后自动创建可复用技能 |
| Curator | 定期清理低质量/过时记忆 |
| Adaptive Context | 学习用户工具偏好、目录习惯 |
| Session Mining | `/api/memory/mine` 扫描历史发现模式 |
| Learn Hook | 每次 Agent 执行后自动 `_learn_from_result()` |

## 工具系统 (53 个)

| 类别 | 数量 | 新增 v4.1 |
|------|------|-----------|
| 📁 文件 | 7 | |
| 💻 Shell | 2 | |
| 🌐 网页 | 3 | web_search: 代理+多引擎+120KB |
| 📋 剪贴板 | 2 | |
| 🖥️ 桌面 | 13 | |
| ⚙️ 系统 | 5 | |
| 📄 文档 | 3 | +convert_to_md (MarkItDown) |
| 🎬 视频 | 13 | |
| 📧 邮件 | 5 | |

**工具缓存:** TTL 缓存 + LRU 淘汰 (200条上限)

## API 路由汇总

| 路由 | 功能 |
|------|------|
| `/api/chat/stream` | 对话 SSE 流式 |
| `/api/agent/run` | Agent 同步执行 |
| `/api/agent/stream` | Agent SSE 流式 |
| `/api/agent/plan` | Agent 规划模式 |
| `/api/agent/review` | Agent 对抗审查 |
| `/api/agent/task` | 后台 Agent 任务 |
| `/api/agent/task/{id}` | 后台任务状态 |
| `/api/agent/tasks` | 后台任务列表 |
| `/api/agent/learn` | Agent 学习钩子 |
| `/api/team/roles` | 多 Agent 角色列表 |
| `/api/team/stream` | 多 Agent 流式 |
| `/api/gateway/health` | AI Gateway 健康 |
| `/api/gateway/chat` | AI Gateway 对话 |
| `/api/tools` | 工具列表 |
| `/api/tools/{name}` | 工具执行 |
| `/api/tools/health` | 工具健康检查 |
| `/api/tools/catalog` | 工具目录 (5列) |
| `/api/monitoring` | 系统监控快照 |
| `/api/monitoring/stream` | 系统监控 SSE 实时 |
| `/api/memory/evolve` | 技能进化 |
| `/api/memory/curator` | 记忆清理 |
| `/api/memory/mine` | 会话挖掘 |
| `/api/memory/adaptive` | 自适应上下文 |

## 安装的技能 (37 个)

**官方 (anthropics/skills):** algorithmic-art, brand-guidelines, canvas-design, claude-api, doc-coauthoring, docx, frontend-design, internal-comms, mcp-builder, pdf, pptx, skill-creator, slack-gif-creator, theme-factory, web-artifacts-builder, webapp-testing, xlsx

**安全 (NovaCode37):** dependency-check, http-sec-audit, jwt-inspector, prompt-injection-tester, sast-lite, secret-scanner

**效率:** last30days (趋势调研), playwright-skill (浏览器自动化), taste-skill 14件 (UI设计质量), skill-miner/personalizer/generalizer (技能优化), supabase/postgres-best-practices

**工具:** headroom v0.25.0 (上下文压缩60-95%), markitdown v0.1.6 (20+格式→MD)

## v4.0→v4.1 演进

| 版本 | 关键新增 |
|------|----------|
| v4.0 | MCP Server/Client ? RAG 记忆 ? 插件系统 ? 邮件 ? 本地 RAG ? 视觉定位 ? 实时监控 |
| v4.1 | 多 Agent 协作 ? Agent 规划+目标检测+对抗审查+后台 ? 自进化 ? AI Gateway ? 53工具 ? 仪表盘实时 ? 10项UI修复 ? 5项目标模式 ? 37技能 |

## 构建

```bash
cargo tauri build    # → ai-suite.exe + AI_Suite_4.1.0_x64-setup.exe
python test_tools.py # → 37/37 全过
python mcp_server.py --sse --port 5100  # MCP SSE 模式
```

## 仓库

`github.com/gain91/g0dness` — master 分支，v4.1.0
