---
name: ai-suite-desktop
description: "AI Suite v4.1 — Tauri 桌面 AI 套件：52 工具 Agent + 多 Agent 协作 + MCP + 角色预设 + 对话/生图/生视频"
metadata:
  type: project
  originSessionId: d85639fc-8bf2-45a4-998a-ca4f3982c043
---

# AI Suite Desktop v4.0

Windows 11, RTX 5070 Ti 12GB VRAM, PyTorch 2.11.0+cu128.

## 架构

```
AI_Suite.exe (Tauri 原生, 6.26 MB)
  ├─ 启动 Ollama serve (如未运行)
  ├─ python gen_web.py         → FastAPI :5000 (Chat UI + 生图/生视频)
  ├─ python model_orchestrator.py → FastAPI :5001 (多模型编排 + Agent)
  └─ webview 加载 dist/index.html → 轮询 /api/status → 跳转 /chat
```

GUI: Tauri webview，托盘隐藏，Ctrl+Shift+A 全局热键呼出，单实例锁。

## 运行服务

| Port | 服务 | 文件 |
|------|------|------|
| 11434 | Ollama | 自启 |
| 5000 | gen_web (FastAPI) | `gen_web.py` |
| 5001 | model_orchestrator (FastAPI) | `model_orchestrator.py` |
| 5100 | MCP SSE Server (可选) | `mcp_server.py --sse` |
| 8188 | ComfyUI | gen_web 按需启动 |

## 前端

`/chat` → `ollama-chat.html`（仓库根目录，相对路径加载）

设计: ChatGPT Desktop + Raycast + Linear 风格 — 中性灰白底，靛蓝点缀，玻璃态顶栏。

**四模式:** 💬 对话 · 🎨 生图 · 🎬 生视频 · 🤖 Agent

**面板:** 🧠 Claude Code ⚡ Codex 双按钮 · 📊 实时监控(CPU/GPU/RAM) · 📦 模型管理 · ⏰ 调度 · 🎤 语音 · 📱 LAN QR · 🎨 三主题

## 模型清单

**本地 Ollama:** `deepseek-r1:14b`(默认) · `qwen3:8b` · `huihui_ai/qwen3-abliterated:8b`(无审查) · `lingmo-uncensored:latest` · `lingmo-writer:latest`

**OpenRouter 云端:** `claude`(Fable 5) · `claude-sonnet`(4.6) · `claude-haiku`(4.5) · `gpt`(5.5) · `gpt-mini`(4o-mini) · `gemini`(3.5 Flash) · `gemini-fast`(2.5 Flash)

**DeepSeek 直连:** `deepseek-v4-pro` (Anthropic Messages API, 100万 ctx)

**火山引擎:** 生图 `seedream3/4/5` · 生视频 `seedance`(2.0) · `wan_i2v`(14B)

## 关键文件

| 文件 | 作用 |
|------|------|
| `gen_web.py` | FastAPI :5000 — Chat HTML + 生图/生视频/上传/历史 |
| `model_orchestrator.py` | FastAPI :5001 — 多模型路由 + Agent + Tool API |
| `agent.py` | Agent 核心 v4.0 — ReAct 循环 + RAG 记忆 + 插件 + MCP |
| `tools.py` | 工具系统 — 47 个 MCP 工具 |
| `mcp_server.py` | MCP Server — stdio + SSE 暴露所有工具 |
| `mcp_client.py` | MCP Client — Agent 连接外部 MCP 服务器 |
| `rag_memory.py` | RAG 记忆 — 向量嵌入 + 语义检索 |
| `local_rag.py` | 本地文档索引 — txt/pdf/docx/代码 |
| `plugin_manager.py` | 插件系统 — Python 热加载 + 文件监控 |
| `email_tools.py` | 邮件工具 — Outlook 发/收/日历/联系人 (+5) |
| `db.py` | SQLite — 对话记忆持久化 |
| `memory_agent.py` | 学习记忆 — 偏好/反馈/Agent 上下文 |
| `scheduler.py` | 定时调度 — Cron + 自然语言 |
| `notify.py` | 通知系统 — Windows Toast / VBS Popup |
| `file_watcher.py` | 文件监工 — 监控 + OCR + Agent 处理 |
| `hw_monitor.py` | 硬件监测 — RAM/VRAM 智能路由 |
| `ollama-chat.html` | 前端 UI — 四模式 + 工具面板 + 仪表盘 |
| `test_tools.py` | 冒烟测试 — 26/26 全过 |
| `ai-suite-tauri/` | Tauri 壳 — Rust 源码 + 构建配置 |
| `~/.model_keys.json` | API Keys — openrouter/deepseek/google/volcengine |
| `~/.ai-suite/` | 运行时数据 — memory.db, agent_memory.db, rag_memory.db, local_rag.db |

## 工具系统 (47 个，+5 email = 52)

| 类别 | 数量 | 新增 v4.0 |
|------|------|-----------|
| 📁 文件 | 7 | |
| 💻 Shell | 2 | |
| 🌐 网页 | 3 | |
| 📋 剪贴板 | 2 | |
| 🖥️ 桌面 | 13 | +screenshot_find, click_text (视觉定位) |
| ⚙️ 系统 | 5 | |
| 📄 文档 | 2 | |
| 🎬 视频 | 13 | |
| 📧 邮件 | 5 | send_email, read_emails, list_calendar, create_event, search_contacts |

**依赖:** ffmpeg 8.1.1 · tesseract 5.4.0 · python-pptx · ezdxf · Pillow · psutil · pywin32 (邮件)

## v4.0 核心新增

| 模块 | 能力 | 价值 |
|------|------|------|
| MCP Server | 标准 MCP 协议暴露 47 工具，stdio+SSE 双传输 | 生态级基础设施 |
| RAG 记忆 | 向量嵌入 + 语义检索，Agent 自动构建上下文 | 越用越聪明 |
| 插件系统 | Python 热加载，文件监控自动重载 | 社区可扩展 |
| MCP Client | Agent 连外部 MCP Server，无限扩展 | 打破工具天花板 |
| 邮件/日历 | Outlook 集成，发/收/日历/联系人 | 办公自动化 |
| 本地 RAG | 索引文档目录，语义搜索代码/PDF/文本 | 知识库检索 |
| 视觉定位 | screenshot_find + click_text，看图找文字点击 | 视觉 Agent |
| 实时监控 | CPU/GPU/RAM/Disk 进度条仪表盘 | 系统感知 |

## Agent 系统

ReAct 循环 (max 15 轮) · 4 模型后端 (DeepSeek/Ollama/OpenRouter) · SSE 流式

v4.0: RAG 记忆上下文注入 · 插件工具自动发现 · MCP 外部工具调用

## Agent API 路由 (v4.0 新增)

| 路由 | 方法 | 功能 |
|------|------|------|
| `/api/rag/memory` | GET/POST | RAG 记忆检索/存储 |
| `/api/rag/search` | GET | 本地文档搜索 |
| `/api/rag/index` | POST | 索引目录 |
| `/api/rag/stats` | GET | 索引统计 |
| `/api/plugins` | GET | 插件列表 |
| `/api/plugins/{name}/load` | POST | 加载插件 |
| `/api/plugins/{name}/unload` | POST | 卸载插件 |
| `/api/mcp/connect` | POST | 连接 MCP Server |
| `/api/mcp/servers` | GET | MCP 服务器列表 |
| `/api/monitoring` | GET | 实时 CPU/GPU/RAM/Disk |

## 版本演进

| 版本 | 关键新增 |
|------|----------|
| v2.0 | SSE 流式 · 对话记忆 · FastAPI · 主题切换 · 工具(8) · Tauri |
| v2.1 | DeepSeek V4 · Markdown · 导出 · 粘贴 · 自启 · 模型管理 · 单实例 |
| v3.0 | Agent(ReAct) · 工具(13) · 通知 · 调度 · 记忆 · 沙箱 |
| v3.1 | 热键 · 桌面控制(+7) · 监工 · 语音 · 仪表盘 · Ollama 自启 |
| v3.2 | 文档生成(pptx/dxf) · 系统管理(10) · 工具 32 |
| v3.3 | 视频编辑(13) · UI 翻新(ChatGPT风格) · 工具 45 · 测试 26/26 · Codex |
| v4.0 | MCP Server/Client · RAG 记忆 · 插件系统 · 邮件 · 本地 RAG · 视觉定位 · 实时监控 · 工具 47+5 |

## 构建

```bash
cargo tauri build    # → ai-suite.exe + AI_Suite_3.3.0_x64-setup.exe
python test_tools.py # → 26/26 测试
python mcp_server.py --sse --port 5100  # MCP SSE 模式
```

EXE: `C:\Users\86538\AI_Suite\AI_Suite.exe` (6.26 MB)
安装包: `ai-suite-tauri/src-tauri/target/release/bundle/nsis/AI_Suite_3.3.0_x64-setup.exe`

## v4.1 新增 (2026-06-12~13)

| 功能 | 文件 | 说明 |
|------|------|------|
| 多 Agent 协作 | `multi_agent.py` | AgentTeam 4 角色，任务分解，并行执行，结果融合 |
| Agent 工具链 | `agent.py` | list_dir→提示读文件，搜索→提示抓详情，磁盘低→清理 |
| CHANGELOG | `CHANGELOG.md` | v2.0~v4.1 完整版本历史 |
| 中文标注 | `tools.py` | 全部 47 工具 description 中文+English |
| 控制台隐藏 | `lib.rs` | `silent_command()` + `CREATE_NO_WINDOW` 全部子进程无弹窗 |
| 单实例 Mutex | `lib.rs` | Windows 内核级互斥锁，防重复启动 |
| 托盘修复 | `lib.rs` | `include_bytes!` 嵌入图标，删除 duplicate config |
| 角色预设 | 前端 + orchestrator | Persona 选择器，保存/切换，system prompt 注入 |
| 命令面板 | 前端 | Ctrl+K Raycast 式搜索工具+命令 |
| README | `README.md` | badges、快速开始、架构图、工具表 |
| 使用手册 | HTML + PPTX | 9 章节完整手册 |
| 密钥加密 | `key_vault.py` | AES-256-CBC 加密 API Keys |

## 检修记录 (v4.1)

- time crate 0.3.48→0.3.47 修复 tauri-utils 编译冲突
- CI: 8 次反复调试 → 锁 Rust 1.96.0 + Cargo.lock + tauri-action
- tkinter 幽灵托盘图标 → 纯 PowerShell clipboard
- 双托盘图标 → 删 tauri.conf.json trayIcon + Rust 嵌入图标
- System prompt 不生效 → orchestrator 读取 system 字段 + 替换优先
- 僵尸 Python 进程 → CREATE_NO_WINDOW + Mutex 单实例

## 构建

```bash
cargo tauri build    # → ai-suite.exe + AI_Suite_4.1.0_x64-setup.exe
python test_tools.py # → 36/36 测试
python mcp_server.py --sse --port 5100  # MCP SSE 模式
```

EXE: `C:\Users\86538\AI_Suite\AI_Suite.exe` (6.26 MB)
安装包: `ai-suite-tauri/src-tauri/target/release/bundle/nsis/AI_Suite_4.1.0_x64-setup.exe`

## 仓库

`github.com/gain91/g0dness` — master 分支，v4.1.0
