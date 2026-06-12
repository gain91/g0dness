# Changelog

## v4.1 (2026-06-12)

### Added
- Multi-agent collaboration (`multi_agent.py`): AgentTeam with 4 roles, task decomposition, parallel execution
- Agent tool chaining: auto-feed tool results to next reasoning step
- `/api/team/stream` SSE endpoint for multi-agent streaming
- Orange "团队" button in Agent tab with live per-agent status cards

## v4.0 (2026-06-12)

### Added
- MCP Server (`mcp_server.py`): stdio + SSE transport, exposes all 47 tools
- MCP Client (`mcp_client.py`): Agent connects to external MCP servers
- RAG Memory (`rag_memory.py`): vector embedding + semantic recall, Agent context injection
- Plugin System (`plugin_manager.py`): Python hot-reload, file watcher, sample template
- Email Tools (`email_tools.py`): Outlook send/read/calendar/contacts (+5 tools)
- Local RAG (`local_rag.py`): document indexing, semantic search (txt/pdf/docx/code)
- Visual targeting: `screenshot_find` + `click_text` tools
- Real-time monitoring: `/api/monitoring` endpoint, CPU/GPU/RAM dashboard bars
- Ctrl+K command palette: Raycast-style search with all tools + commands
- Key vault (`key_vault.py`): AES-256-CBC encrypted API key storage
- `README.md` with badges, quickstart, architecture, full tool table
- CI/CD: GitHub Actions auto-build Tauri EXE on push
- Total tools: 47 built-in + 5 email = 52

### Changed
- UI overhaul: ChatGPT + Raycast + Linear design, glass effects, indigo accent
- Agent v4.0: RAG context injection, plugin discovery, email tool registration
- Orchestrator: 10 new API routes for RAG/plugins/MCP/monitoring
- Dashboard: real-time monitoring bars, RAG stats, plugins, MCP status

### Fixed
- system_info RAM=0: replaced GlobalMemoryStatusEx with psutil
- screenshot: replaced non-existent tkinter.grab_screen() with PIL.ImageGrab
- volume: replaced 50-keypress hack with waveOutGetVolume/SetVolume API
- DeepSeek key: moved from hardcoded to `.model_keys.json`
- OCR: tesseract priority + simplified Windows OCR
- 12 hardcoded dark colors replaced with CSS variables
- 4 `var(--accent2)` undefined variable references
- `find_files` schema missing `max_results` param
- `delete_file` unhandled missing file error
- CI: pinned Rust 1.96.0, time crate =0.3.47, Cargo.lock committed

## v3.3 (2026-06-12)

### Added
- Video editing tools (13): trim, concat, resize, extract_audio, speed, gif, compress, convert, crop
- Document generation: `create_pptx`, `create_dxf`
- System management (10): system_info, list_processes, kill_process, volume, window_control, file ops
- Tool health API: `/api/tools/health`, dashboard dependency status
- `test_tools.py`: 26 smoke tests
- Codex CLI integration: green launch button, `/api/open_codex`

### Changed
- UI redesign: ChatGPT Desktop + Raycast + Linear style, glass-morphism, animations
- Total tools: 45

## v3.2 (2026-06-12)

### Added
- Desktop control (7): click, move_mouse, type_text, press_key, get_windows, focus_window, mouse_pos
- File watcher: monitor folders, auto OCR/notify/Agent process
- Voice input: Web Speech API
- Scheduler UI + Dashboard UI
- Ollama auto-start in Tauri shell
- Single instance lock + global hotkey Ctrl+Shift+A
- Auto-start shortcut

### Changed
- Tools: 20 → 32

## v3.1 (2026-06-12)

### Added
- Agent core (`agent.py`): ReAct loop, 4 model backends, SSE streaming
- Tools expanded (13): find_files, run_python, open_browser, screenshot, ocr
- Notification system (`notify.py`): Windows Toast + VBS Popup
- Scheduler (`scheduler.py`): Cron + natural language
- Learning memory (`memory_agent.py`): SQLite, preferences/feedback

## v3.0 (2026-06-12)

### Added
- Custom icon, global hotkey, desktop control tools
- Notification system, background task queue
- Agent keyboard shortcut Ctrl+4

## v2.x (2026-06-11 ~ 2026-06-12)

### Added
- v2.0: SSE streaming, conversation memory SQLite, FastAPI migration, theme system, MCP tools (8), Tauri shell
- v2.1: DeepSeek V4 Pro, Markdown rendering, conversation export, image paste, auto-start, model manager, single instance lock
- 14 bug fixes across 3 audit rounds
