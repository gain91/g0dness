"""
AI Suite — MCP Client (v4.0)
Agent 作为 MCP 客户端连接外部 MCP Server，扩展工具能力
支持 stdio 和 SSE 两种传输
用法:
  from mcp_client import MCPClient
  client = MCPClient()
  client.connect_stdio("python mcp_server.py")
  tools = client.list_tools()
  result = client.call_tool("read_file", {"path": "/tmp/test.txt"})
"""

import subprocess, json, threading, queue, time, os
import urllib.request as ur

class MCPClient:
    def __init__(self):
        self.servers: dict[str, dict] = {}  # name → {process, transport, tools}

    # ─── Stdio Transport ───

    def connect_stdio(self, name: str, command: str) -> bool:
        """连接 stdio MCP 服务器"""
        try:
            proc = subprocess.Popen(
                command, shell=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            # Initialize
            init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05",
                                   "capabilities": {},
                                   "clientInfo": {"name": "ai-suite-agent", "version": "4.0.0"}}}
            resp = self._rpc_stdio(proc, init_req)
            if resp and "result" in resp:
                # List tools
                tools_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
                tools_resp = self._rpc_stdio(proc, tools_req)
                tools = tools_resp.get("result", {}).get("tools", []) if tools_resp else []
                self.servers[name] = {"process": proc, "transport": "stdio", "tools": tools}
                print(f"[mcp] connected stdio: {name} ({len(tools)} tools)")
                return True
        except Exception as e:
            print(f"[mcp] stdio connect failed {name}: {e}")
        return False

    def _rpc_stdio(self, proc, request: dict, timeout: int = 30) -> dict:
        """JSON-RPC over stdio"""
        try:
            req_str = json.dumps(request, ensure_ascii=False) + "\n"
            proc.stdin.write(req_str)
            proc.stdin.flush()
            line = proc.stdout.readline()
            if line:
                return json.loads(line.strip())
        except Exception as e:
            return {"error": str(e)}
        return None

    # ─── SSE Transport ───

    def connect_sse(self, name: str, url: str) -> bool:
        """连接 SSE MCP 服务器"""
        try:
            # Get SSE endpoint
            sse_url = url.rstrip("/") + "/sse"
            req = ur.Request(sse_url, headers={"Accept": "text/event-stream"})
            resp = ur.urlopen(req, timeout=10)
            # Read first event to get message endpoint
            data = resp.readline().decode()
            if data.startswith("data: "):
                event_data = json.loads(data[6:])
                msg_url = event_data.get("endpoint", url.rstrip("/") + "/message")
            else:
                msg_url = url.rstrip("/") + "/message"

            # Initialize
            init_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05",
                                   "capabilities": {},
                                   "clientInfo": {"name": "ai-suite-agent", "version": "4.0.0"}}}).encode()
            req = ur.Request(msg_url, data=init_req,
                           headers={"Content-Type": "application/json"})
            init_resp = json.loads(ur.urlopen(req, timeout=10).read())
            if "result" in init_resp:
                # List tools
                tools_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode()
                req2 = ur.Request(msg_url, data=tools_req,
                                headers={"Content-Type": "application/json"})
                tools_resp = json.loads(ur.urlopen(req2, timeout=10).read())
                tools = tools_resp.get("result", {}).get("tools", [])
                self.servers[name] = {"url": msg_url, "transport": "sse", "tools": tools}
                print(f"[mcp] connected sse: {name} ({len(tools)} tools)")
                return True
        except Exception as e:
            print(f"[mcp] sse connect failed {name}: {e}")
        return False

    # ─── Tool Operations ───

    def list_tools(self, server: str = None) -> list:
        """列出工具"""
        if server:
            return self.servers.get(server, {}).get("tools", [])
        all_tools = []
        for name, srv in self.servers.items():
            for t in srv["tools"]:
                t["_server"] = name
                all_tools.append(t)
        return all_tools

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """调用工具（自动路由到正确的服务器）"""
        # Find which server has this tool
        target = None
        for name, srv in self.servers.items():
            for t in srv["tools"]:
                if t["name"] == tool_name:
                    target = (name, srv)
                    break
        if not target:
            return {"ok": False, "error": f"Tool not found: {tool_name}"}

        name, srv = target
        req = {"jsonrpc": "2.0", "id": 100, "method": "tools/call",
               "params": {"name": tool_name, "arguments": arguments}}

        if srv["transport"] == "stdio":
            resp = self._rpc_stdio(srv["process"], req)
        else:
            try:
                data = json.dumps(req).encode()
                http_req = ur.Request(srv["url"], data=data,
                                    headers={"Content-Type": "application/json"})
                resp = json.loads(ur.urlopen(http_req, timeout=30).read())
            except Exception as e:
                return {"ok": False, "error": str(e)}

        if resp and "result" in resp:
            content = resp["result"].get("content", [])
            for c in content:
                if c.get("type") == "text":
                    try:
                        return json.loads(c["text"])
                    except:
                        return {"ok": True, "text": c["text"]}
            return {"ok": True, "result": content}
        return {"ok": False, "error": resp.get("error", {}).get("message", "Unknown error") if resp else "No response"}

    # ─── Management ───

    def disconnect(self, name: str):
        """断开 MCP 服务器"""
        if name in self.servers:
            srv = self.servers.pop(name)
            if srv["transport"] == "stdio" and srv.get("process"):
                try:
                    srv["process"].terminate()
                except:
                    pass

    def disconnect_all(self):
        for name in list(self.servers.keys()):
            self.disconnect(name)

    def server_status(self) -> list:
        return [{"name": n, "transport": s["transport"], "tools": len(s["tools"])}
                for n, s in self.servers.items()]


# ═══════ Global instance ═══════

mcp = MCPClient()
