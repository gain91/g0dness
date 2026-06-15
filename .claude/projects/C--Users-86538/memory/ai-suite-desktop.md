---
name: ai-suite-desktop
description: "AI Suite v4.2 — Tauri 桌面 AI 套件：53 工具 + 多 Agent + MCP + 自进化 + 角色预设 + 对话/生图/生视频 + 7 新模块 + 15 安全修复 + 10 UX 升级"
metadata:
  type: project
  originSessionId: d85639fc-8bf2-45a4-998a-ca4f3982c043
  version: 4.2.0
  updated: 2026-06-15
---

# AI Suite Desktop v4.2

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

## v4.2 新增模块 (7 个)

| 模块 | 作用 |
|------|------|
| `logger.py` | 结构化日志 — 5MB 滚动文件 + JSON lines + stderr |
| `config.py` | JSON 配置 + 环境变量覆盖 (AI_SUITE_ 前缀) |
| `auth_middleware.py` | LAN Token 鉴权 — X-Auth-Token header / ?token= 查询参数 |
| `health_monitor.py` | 后台 30s 检测 Ollama/ComfyUI → 自动重启 |
| `cost_tracker.py` | OpenRouter/Volcengine 按 token/张数 计费统计 |
| `tool_audit.py` | 工具调用 JSONL 审计日志 (~/.ai-suite/logs/) |
| `templates_lib.py` | 10 个预设 Prompt 模板 + 用户自定义 |

## v4.2 安全修复 (15 项)

| # | 严重度 | 文件 | 修复 |
|---|--------|------|------|
| 1 | 🔴 | `tools.py` | write_file 加 _sandbox_path 检查（原可写系统文件） |
| 2 | 🔴 | `tools.py` | screenshot PowerShell 注入 → base64 编码路径 |
| 3 | 🔴 | `tools.py` | ocr PowerShell 注入 → base64 编码路径 |
| 4 | 🔴 | `tools.py` | screenshot_find 路径+查询 base64 编码 |
| 5 | 🔴 | `ollama-chat.html` | 会话加载 XSS → escapeHTML(m.content) |
| 6 | 🔴 | `gen_web.py` | 上传路径穿越 → basename + 边界检查 |
| 7 | 🔴 | `agent.py` | prompt injection → 沙箱分隔符 (USER CONTEXT 标记) |
| 8 | 🟡 | `gen_web.py` | ComfyUI 轮询加 150 次上限 + 5 分钟超时 |
| 9 | 🟡 | `gen_web.py` | state 字典竞态 → clear()+update() 替代引用替换 |
| 10 | 🟡 | `model_orchestrator.py` | AIGateway 降级链扩至 ollama→deepseek→claude→gpt→gemini |
| 11 | 🟡 | `model_orchestrator.py` | generate_image_openrouter 响应加 error 检查 + try/except |
| 12 | 🟡 | `model_orchestrator.py` | provider_health 阻塞 → asyncio.to_thread() |
| 13 | 🟡 | `agent.py` | tool_calls: None → [] 兼容 Anthropic API |
| 14 | 🟡 | `ollama-chat.html` | 新会话首条消息清空 → newConversation(true) 保留视图 |
| 15 | 🟡 | `multi_agent.py` | 上下文 200→1500 字符 + 过滤失败步骤 |

## v4.2 前端 UX 升级 (10 项)

| # | 功能 | 实现 |
|---|------|------|
| 1 | ⏹ 停止生成 | AbortController + 按钮切换 |
| 2 | 🌓 暗色自动 | prefers-color-scheme + 4 主题 (default/dark/light/auto) |
| 3 | 📎 拖拽上传 | chatView dragover/drop 事件 |
| 4 | ✏️ 编辑/🔄重生成 | hover 编辑按钮 + regenerate() |
| 5 | 📊 Markdown | 表格/删除线/任务列表/标题/引用 |
| 6 | 🔍 对话搜索 | convSearch 输入框实时过滤 |
| 7 | 💾 会话恢复 | localStorage 记录上次活跃会话 |
| 8 | 💰 费用徽章 | header 显示累计费用 |
| 9 | 📋 模板选择器 | chat 输入区 tplSelect 下拉 |
| 10 | 📈 进度条 | 生图/视频轮询显示 progress 元素 |

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

**四模式:** 💬 对话 🎨 生图 🎬 生视频 🤖 Agent

**面板:** 🧠 Claude Code ⚡ Codex 📊 实时监控(CPU/GPU/RAM) 📦 模型管理 📅 调度 🎤 语音 📱 LAN QR 🌓 三主题

**v4.2 UI:** 停止按钮、暗色自动、拖拽上传、编辑/重生成、对话搜索、费用徽章、模板选择器、进度条

## 模型清单

**本地 Ollama:** `deepseek-r1:14b`(默认) 🔵 `qwen3:8b` 🔵 `huihui_ai/qwen3-abliterated:8b`(无审查) 🔵 `lingmo-uncensored:latest` 🔵 `lingmo-writer:latest`

**OpenRouter 云端:** `claude`(Fable 5) 🔵 `claude-sonnet`(4.6) 🔵 `claude-haiku`(4.5) 🔵 `gpt`(5.5) 🔵 `gpt-mini`(4o-mini) 🔵 `gemini`(3.5 Flash) 🔵 `gemini-fast`(2.5 Flash)

**DeepSeek 直连:** `deepseek-v4-pro` (Anthropic Messages API, 100万 ctx)

**火山引擎:** 生图 `seedream5` 🔵 生视频 `seedance`(2.0) 🔵 `wan_i2v`(14B)

> v4.2: 4.0/4.5 模型名已移除（账号未开通，5.0 综合最优）

## 关键文件

| 文件 | 作用 |
|------|------|
| `gen_web.py` | FastAPI :5000 — Chat HTML + 生图/生视频/上传/历史 |
| `model_orchestrator.py` | FastAPI :5001 — 多模型路由 + Agent + AIGateway + 技能市场 |
| `agent.py` | Agent 核心 v4.2 — ReAct + 规划模式 + 目标检测 + 对抗审查 + 后台任务 + 自进化 |
| `tools.py` | 工具系统 — 53 MCP 工具 (含 MarkItDown 集成 + 沙箱审计) |
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
| `key_vault.py` | 密钥加密 — AES-256-GCM + 60 万迭代 |
| `logger.py` | 🆕 结构化日志 — 5MB 滚动 + stderr |
| `config.py` | 🆕 JSON 配置系统 + 环境变量覆盖 |
| `auth_middleware.py` | 🆕 LAN Token 鉴权 |
| `health_monitor.py` | 🆕 服务自愈 — Ollama/ComfyUI 自动重启 |
| `cost_tracker.py` | 🆕 费用追踪 — OpenRouter + Volcengine |
| `tool_audit.py` | 🆕 工具审计日志 — JSONL |
| `templates_lib.py` | 🆕 Prompt 模板库 — 10 预设 + 自定义 |
| `ollama-chat.html` | 前端 UI — 四模式 + 工具面板 + 仪表盘 + 引导页 |
| `test_tools.py` | 冒烟测试 — 37/37 全过 |
| `ai-suite-tauri/` | Tauri 壳 — Rust 源码 + 构建配置 |

## Agent v4.2 核心能力

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
| Prompt 注入防护 | 用户上下文沙箱分隔符 |

## AI Gateway (reactive-resume 模式)

| 功能 | 说明 |
|------|------|
| 统一接口 | `AIGateway.chat()` — 单入口多提供商 |
| 降级链 | ollama→deepseek→claude→gpt→gemini (v4.2 扩至 5 级) |
| 用量统计 | 调用次数 + token + 费用追踪 |
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

| 类别 | 数量 | 新增 v4.1-4.2 |
|------|------|-----------|
| 📁 文件 | 7 | write_file 沙箱检查 |
| 💻 Shell | 2 | PowerShell 注入防护 (base64) |
| 🌐 网页 | 3 | web_search: 代理+多引擎+120KB |
| 📋 剪贴板 | 2 | |
| 🖥️ 桌面 | 13 | OCR/截图注入防护 |
| ⚙️ 系统 | 5 | |
| 📄 文档 | 3 | +convert_to_md (MarkItDown) |
| 🎬 视频 | 13 | |
| 📧 邮件 | 5 | |

**工具缓存:** TTL 缓存 + LRU 淘汰 (200 条上限)
**审计日志:** 所有工具调用记录到 JSONL (~/.ai-suite/logs/tool_audit.jsonl)

## API 路由汇总

| 路由 | 功能 |
|------|------|
| `/api/chat/stream` | 对话 SSE 流式 |
| `/ws/chat` | 🆕 WebSocket 双向聊天 + cancel |
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
| `/api/cost/stats` | 🆕 费用统计 |
| `/api/templates` | 🆕 模板 CRUD |
| `/api/audit/tools` | 🆕 工具审计日志 |
| `/api/conversations/{id}/export` | 🆕 导出 JSON/MD |
| `/api/conversations/import` | 🆕 导入对话 |
| `/api/models/openrouter` | 🆕 动态模型列表 (1h 缓存) |

## 安装的技能 (37 个)

**官方 (anthropics/skills):** algorithmic-art, brand-guidelines, canvas-design, claude-api, doc-coauthoring, docx, frontend-design, internal-comms, mcp-builder, pdf, pptx, skill-creator, slack-gif-creator, theme-factory, web-artifacts-builder, webapp-testing, xlsx

**安全 (NovaCode37):** dependency-check, http-sec-audit, jwt-inspector, prompt-injection-tester, sast-lite, secret-scanner

**效率:** last30days (趋势调研), playwright-skill (浏览器自动化), taste-skill 14件 (UI设计质量), skill-miner/personalizer/generalizer (技能优化), supabase/postgres-best-practices

**工具:** headroom v0.25.0 (上下文压缩60-95%), markitdown v0.1.6 (20+格式→MD)

## 版本演进

| 版本 | 关键新增 |
|------|----------|
| v4.0 | MCP Server/Client 🔵 RAG 记忆 🔵 插件系统 🔵 邮件 🔵 本地 RAG 🔵 视觉定位 🔵 实时监控 |
| v4.1 | 多 Agent 协作 🔵 Agent 规划+目标检测+对抗审查+后台 🔵 自进化 🔵 AI Gateway 🔵 53工具 🔵 仪表盘实时 🔵 10项UI修复 🔵 5项目标模式 🔵 37技能 |
| v4.2 | 🆕 7 新模块 (日志/配置/鉴权/健康/费用/审计/模板) 🔵 15 安全修复 🔵 10 UX 升级 (停止/暗色/拖拽/编辑/搜索/MD/会话恢复/费用/模板/进度) 🔵 WebSocket 🔵 导出/导入 🔵 动态模型列表 🔵 Key Vault AES-256-GCM 🔵 Token 估算升级 |

## 构建

```bash
cargo tauri build    # → ai-suite.exe + AI_Suite_4.2.0_x64-setup.exe
python test_tools.py # → 37/37 全过
python mcp_server.py --sse --port 5100  # MCP SSE 模式
```

## 已知问题 & 修复历史

### 编排器 5001 启动死锁 (已修复: 2026-06-15)
**症状**: AI Suite 显示 "❌ 编排器未连接 (5001)"，`python model_orchestrator.py` 静默挂死。
**根因**: `model_orchestrator.py` 模块级 `DEEPSEEK_CONFIG = _load_deepseek_config()` 触发 `load_keys()` → `from key_vault import...` → cryptography CFFI Rust 绑定在 Windows Python 3.12 exec/import 上下文死锁。
**修复** (commit `95c9c9d`):
1. `DEEPSEEK_CONFIG` 懒加载 — 模块级改 `get_deepseek_config()` 首次访问初始化
2. `load_keys()` 读明文 JSON 优先，key_vault 降级 — 避免启动路径触发 cryptography 导入

### 云端生图 404 (已修复: 2026-06-15)
**症状**: Seedream 4.0/4.5 模型返回 HTTP 404。
**根因**: 火山引擎账号 (2129058516) 未激活 4.0/4.5，仅开通了 5.0。5.0 是所有版本中最优（联网搜索/逻辑推理/PNG/性价比）。
**修复**: 前端下拉移除 4.0/4.5，只保留 Seedream 5.0。

### OpenRouter 生图 403 (已知: 2026-06-15)
**症状**: OpenRouter 图片生成返回 403 Forbidden。
**原因**: OpenRouter 需要梯子，国内直连被墙。Seedream 火山引擎不需要梯子。**处理**: 无代码修复，用户需自行翻墙或使用 Seedream。

## 仓库

`github.com/gain91/g0dness` — master 分支，v4.2.0
