# AI Suite

> Tauri 桌面应用 + FastAPI 后端，本地多模型对话/生图/生视频/Agent 助手

## 运行环境

- Windows 11, Python 3.12, RTX 5070 Ti 12GB VRAM
- Ollama 本地推理（默认 deepseek-r1:14b）

## 启动方式

```bash
# 开发模式
cd g0dness
python gen_web.py              # :5000 Chat UI + 生图/生视频
python model_orchestrator.py   # :5001 多模型编排 + Agent
python mcp_server.py --sse     # :5100 MCP Server（可选）

# 生产构建
cargo tauri build              # → AI_Suite.exe
```

## 架构

```
AI_Suite.exe (Tauri 原生壳)
  ├─ python gen_web.py           → FastAPI :5000 (Chat UI + 生图/生视频)
  ├─ python model_orchestrator.py → FastAPI :5001 (Agent + AIGateway)
  ├─ python mcp_server.py --sse  → :5100 (MCP Server)
  └─ webview 加载 dist/index.html
```

## 文件职责

| 文件 | 职责 |
|------|------|
| `gen_web.py` | FastAPI :5000 — Chat HTML + 生图/生视频/上传/历史/模板 |
| `model_orchestrator.py` | FastAPI :5001 — 多模型路由 + Agent + AIGateway + 成本路由 |
| `agent.py` | Agent 核心 — ReAct 循环 + 规划 + 目标检测 + 对抗审查 + Prompt Defense |
| `tools.py` | 53 个工具 — 文件/Shell/网页/桌面/文档/视频/邮件 |
| `multi_agent.py` | 多 Agent 协作 — DAG 拓扑排序 + 任务分解 |
| `mcp_server.py` | MCP Server — stdio + SSE 暴露所有工具 |
| `mcp_client.py` | MCP Client — 连接外部 MCP 服务器 |
| `ollama-chat.html` | 前端 UI — 四模式 + 工具面板 + 仪表盘 |
| `rag_memory.py` | RAG 记忆 — 向量嵌入 + 语义检索 |
| `local_rag.py` | 本地文档索引 — txt/pdf/docx/代码 |
| `memory_agent.py` | 学习记忆 + 自进化 + 本能学习 |
| `plugin_manager.py` | 插件系统 — Python 热加载 |
| `email_tools.py` | 邮件工具 — Outlook |
| `db.py` | SQLite 对话持久化 |
| `scheduler.py` | 定时调度 — Cron + 自然语言 |
| `config.py` | JSON 配置 + 环境变量覆盖（AI_SUITE_ 前缀） |
| `key_vault.py` | 密钥加密 — AES-256-GCM |
| `hw_monitor.py` | 硬件监测 — RAM/VRAM 智能路由 |
| `health_monitor.py` | 服务自愈 — Ollama/ComfyUI 自动重启 |
| `logger.py` | 结构化日志 — 5MB 滚动 |
| `cost_tracker.py` | 费用追踪 — OpenRouter + Volcengine |
| `auth_middleware.py` | LAN Token 鉴权 |

## 模型

**本地 Ollama:** deepseek-r1:14b (默认), qwen3:8b, qwen3-abliterated:8b

**OpenRouter 云端:** claude (Fable 5), claude-sonnet (4.6), claude-haiku (4.5), gpt (5.5), gemini (3.5 Flash)

**DeepSeek 直连:** deepseek-v4-pro (Anthropic Messages API)

**火山引擎:** 生图 seedream5, 生视频 seedance (2.0)

## Agent 能力

- ReAct 循环（最多 15 轮，目标检测提前终止）
- 规划模式 `/api/agent/plan`
- 对抗审查 `/api/agent/review`
- 后台任务 `/api/agent/task`
- 4 模型后端 + 降级链：ollama → deepseek → claude → gpt → gemini
- RAG 语义记忆注入

## 关键约定

- 所有 API 返回 JSON，错误统一 try/except
- 工具调用有沙箱路径检查 + JSONL 审计日志
- 配置优先级：环境变量（AI_SUITE_ 前缀）> config.json > 默认值
- 前端四模式：💬 对话 🎨 生图 🎬 生视频 🤖 Agent
- 测试：`python test_tools.py`（37/37 冒烟测试）
