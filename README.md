<p align="center">
  <img src="ai_suite_icon.ico" width="80" alt="AI Suite">
</p>
<h1 align="center">g0dness AI Suite</h1>
<p align="center">全自主桌面 AI 套件 · 52 工具 · 4 模式 · 多模型编排</p>
<p align="center">
  <img src="https://github.com/gain91/g0dness/actions/workflows/build.yml/badge.svg" alt="Build">
  <img src="https://img.shields.io/badge/version-4.0-6366f1" alt="v4.0">
  <img src="https://img.shields.io/badge/tools-52-10b981" alt="52 tools">
  <img src="https://img.shields.io/badge/tests-26%2F26-10b981" alt="tests">
  <img src="https://img.shields.io/badge/platform-Windows%2011-0078d4" alt="Windows">
</p>

---

## 快速开始

```bash
# 1. 安装依赖
pip install fastapi uvicorn pillow psutil python-pptx ezdxf pywin32

# 2. 配置 API Keys
cp .model_keys.example.json ~/.model_keys.json
# 编辑 ~/.model_keys.json，填入你的 key

# 3. 启动服务
python gen_web.py &
python model_orchestrator.py &

# 4. 打开浏览器
start http://localhost:5000/chat
```

**或者下载 EXE**：从 [Releases](https://github.com/gain91/g0dness/releases) 下载 `AI_Suite_*_x64-setup.exe`，双击安装。

## 功能

### 四模式

| 模式 | 功能 |
|------|------|
| 💬 对话 | Ollama 本地无限 + OpenRouter 云端多模型（Claude/GPT/Gemini） |
| 🎨 生图 | SDXL 本地 / Seedream / GPT-Image / Gemini-Image |
| 🎬 生视频 | Seedance 2.0 / Wan 图生视频 |
| 🤖 Agent | 52 工具 ReAct 循环，流式执行，后台任务 |

### 52 工具

| 类别 | 工具 |
|------|------|
| 📁 文件 (7) | read, write, list, find, copy, move, delete |
| 💻 Shell (2) | shell, run_python |
| 🌐 网页 (3) | web_fetch, web_search, open_browser |
| 📋 剪贴板 (2) | read, write |
| 🖥️ 桌面 (13) | click, type, press_key, screenshot, ocr, screenshot_find, click_text, window_control... |
| ⚙️ 系统 (5) | system_info, list_processes, kill_process, get_volume, set_volume |
| 📄 文档 (2) | create_pptx, create_dxf |
| 🎬 视频 (13) | trim, concat, resize, extract_audio, speed, gif, compress, convert... |
| 📧 邮件 (5) | send_email, read_emails, list_calendar, create_event, search_contacts |

### v4.0 核心能力

| 模块 | 说明 |
|------|------|
| 🔌 MCP Server | 标准 MCP 协议暴露 52 工具（stdio + SSE），Claude Code / Codex 直连 |
| 🧠 RAG 记忆 | 向量嵌入 + 语义检索，Agent 越用越聪明 |
| 📦 插件系统 | Python 热加载插件，文件监控自动重载 |
| 🌍 MCP Client | Agent 连接外部 MCP Server，无限扩展 |
| 📧 邮件/日历 | Outlook 集成，发/收/日历/联系人 |
| 📚 本地 RAG | 索引文档目录，语义搜索 txt/pdf/docx/代码 |
| 🖼️ 视觉定位 | 截图 + OCR 找文字，自动精准点击 |
| 📊 实时监控 | CPU/GPU/RAM/Disk 进度条仪表盘 |

## 架构

```
AI_Suite.exe (Tauri, 6MB)
  ├─ Ollama serve
  ├─ python gen_web.py         → FastAPI :5000 (Chat UI + 生图)
  ├─ python model_orchestrator.py → FastAPI :5001 (编排 + Agent)
  ├─ python mcp_server.py --sse → :5100 (MCP Server, 可选)
  └─ Webview → loading → /chat
```

## 模型

**本地 (Ollama):** deepseek-r1:14b · qwen3:8b · qwen3-abliterated · lingmo

**云端 (OpenRouter):** Claude (Fable 5/Sonnet 4.6/Haiku 4.5) · GPT (5.5/4o-mini) · Gemini (3.5/2.5 Flash)

**直连:** DeepSeek V4 Pro (100万 ctx) · 火山引擎 Seedream/Seedance

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| Ctrl+1/2/3/4 | 切换模式（对话/生图/生视频/Agent） |
| Ctrl+N | 新建对话 |
| Ctrl+Enter | 发送消息 |
| Ctrl+Shift+A | 全局热键呼出窗口 |
| Ctrl+K | 命令面板（搜索工具+快速执行） |
| Ctrl+V | 粘贴图片上传 |

## 项目结构

```
├── gen_web.py          # FastAPI :5000 — Chat + 生图/生视频
├── model_orchestrator.py # FastAPI :5001 — 编排 + Agent + API
├── agent.py            # Agent 核心 v4.0 — ReAct + RAG + 插件
├── tools.py            # 工具系统 — 47 MCP 工具
├── mcp_server.py       # MCP Server — stdio + SSE
├── mcp_client.py       # MCP Client — 连接外部 MCP
├── rag_memory.py       # RAG 记忆 — 向量语义检索
├── local_rag.py        # 本地 RAG — 文档索引
├── plugin_manager.py   # 插件系统 — 热加载
├── email_tools.py      # 邮件工具 — Outlook 集成
├── db.py               # 对话记忆 — SQLite
├── scheduler.py        # 定时调度
├── notify.py           # 通知系统
├── memory_agent.py     # 学习记忆
├── file_watcher.py     # 文件监工
├── hw_monitor.py       # 硬件监测
├── ollama-chat.html    # 前端 UI
├── test_tools.py       # 冒烟测试
├── ai-suite-tauri/     # Tauri 壳 (Rust)
└── .github/workflows/  # CI/CD
```

## 构建

```bash
# 本地开发
python gen_web.py &
python model_orchestrator.py &

# 构建 EXE
cd ai-suite-tauri/src-tauri && cargo tauri build

# 测试
python test_tools.py

# MCP Server
python mcp_server.py --sse --port 5100
```

## License

MIT
