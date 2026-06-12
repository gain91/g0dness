"""
AI Suite — MCP Server (v4.0)
标准 Model Context Protocol 实现，暴露 45 工具给任何 MCP 客户端
支持的传输: stdio (默认), SSE (--sse --port 5100)
用法:
  python mcp_server.py                    # stdio 模式
  python mcp_server.py --sse --port 5100  # SSE 模式
"""

import sys, os, json, asyncio
from typing import Any

# Add tools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tools

SERVER_NAME = "ai-suite"
SERVER_VERSION = "4.0.0"

# ═══════ JSON-RPC 2.0 ═══════

def rpc_response(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}

def rpc_error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}

# ═══════ MCP Handlers ═══════

def handle_initialize(id, params):
    return rpc_response(id, {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {},
            "resources": {}
        },
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}
    })

def handle_tools_list(id, params):
    tool_list = []
    for t in tools.list_tools():
        schema = t.get("schema", {})
        input_schema = {
            "type": "object",
            "properties": {},
            "required": []
        }
        for pname, pinfo in schema.items():
            input_schema["properties"][pname] = {
                "type": pinfo.get("type", "string"),
                "description": pinfo.get("description", "")
            }
            if not pinfo.get("optional"):
                input_schema["required"].append(pname)
        tool_list.append({
            "name": t["name"],
            "description": t["description"],
            "inputSchema": input_schema
        })
    return rpc_response(id, {"tools": tool_list})

def handle_tools_call(id, params):
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    if tool_name not in tools.TOOLS:
        return rpc_error(id, -32602, f"Unknown tool: {tool_name}")
    try:
        result = tools.execute(tool_name, arguments)
        return rpc_response(id, {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
            "isError": not result.get("ok", False)
        })
    except Exception as e:
        return rpc_response(id, {
            "content": [{"type": "text", "text": json.dumps({"ok": False, "error": str(e)})}],
            "isError": True
        })

def handle_resources_list(id, params):
    # Expose key files as resources
    resources = []
    home = os.path.expanduser("~")
    for name, path in [
        ("model_keys", os.path.join(home, ".model_keys.json")),
        ("memory_db", os.path.join(home, ".ai-suite/memory.db")),
        ("agent_memory_db", os.path.join(home, ".ai-suite/agent_memory.db")),
        ("skills_dir", os.path.join(home, ".ai-suite/skills")),
    ]:
        if os.path.exists(path):
            resources.append({
                "uri": f"file://{path}",
                "name": name,
                "mimeType": "application/octet-stream"
            })
    return rpc_response(id, {"resources": resources})

METHOD_MAP = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
    "resources/list": handle_resources_list,
    "notifications/initialized": lambda id, params: None,  # no-op
}

# ═══════ Stdio Transport ═══════

def run_stdio():
    """标准输入/输出 JSON-RPC 传输"""
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            request = json.loads(line)
            method = request.get("method", "")
            req_id = request.get("id")
            params = request.get("params", {})
            handler = METHOD_MAP.get(method)
            if handler:
                result = handler(req_id, params)
                if result:
                    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
            else:
                sys.stdout.write(json.dumps(rpc_error(req_id, -32601, f"Method not found: {method}"), ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            continue
        except KeyboardInterrupt:
            break
        except Exception as e:
            err = rpc_error(None, -32603, str(e))
            sys.stdout.write(json.dumps(err, ensure_ascii=False) + "\n")
            sys.stdout.flush()

# ═══════ SSE Transport ═══════

def run_sse(port=5100):
    """HTTP SSE 传输模式"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading

    class MCPHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/sse":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                # Send endpoint event
                endpoint = f"http://localhost:{port}/message"
                self.wfile.write(f"data: {json.dumps({'endpoint': endpoint})}\n\n".encode())
                self.wfile.flush()
                # Keep connection open
                while True:
                    try:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        import time
                        time.sleep(30)
                    except:
                        break
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/message":
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len)
                try:
                    request = json.loads(body)
                    method = request.get("method", "")
                    req_id = request.get("id")
                    params = request.get("params", {})
                    handler = METHOD_MAP.get(method)
                    if handler:
                        result = handler(req_id, params)
                    else:
                        result = rpc_error(req_id, -32601, f"Method not found: {method}")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    if result:
                        self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
                except Exception as e:
                    self.send_response(400)
                    self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.end_headers()

        def log_message(self, format, *args):
            pass  # suppress logs

    server = HTTPServer(("127.0.0.1", port), MCPHandler)
    print(f"MCP SSE Server: http://127.0.0.1:{port}/sse")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()

# ═══════ Entry ═══════

if __name__ == "__main__":
    if "--sse" in sys.argv:
        port = 5100
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        run_sse(port)
    else:
        run_stdio()
