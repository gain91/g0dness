"""
AI Suite — Plugin Manager (v4.0)
Python 插件热加载系统：发现、加载、卸载、重载
插件目录: ~/.ai-suite/plugins/
每个插件是一个 .py 文件，暴露 register() 函数返回 {tools, routes, on_start, on_stop}
"""

import os, sys, json, time, importlib, threading
from typing import Dict, List, Any

PLUGIN_DIR = os.path.expanduser("~/.ai-suite/plugins")
os.makedirs(PLUGIN_DIR, exist_ok=True)

# ═══════ Plugin Manager ═══════

class PluginManager:
    def __init__(self):
        self.plugins: Dict[str, Any] = {}       # name → module
        self.tools: Dict[str, dict] = {}         # plugin tools
        self.routes: Dict[str, callable] = {}    # plugin API routes
        self.hooks: Dict[str, List[callable]] = {"on_start": [], "on_stop": [], "on_message": []}
        self._watcher = None

    def discover(self) -> List[str]:
        """发现可用插件"""
        plugins = []
        for f in os.listdir(PLUGIN_DIR):
            if f.endswith(".py") and not f.startswith("_"):
                plugins.append(f[:-3])
        return plugins

    def load(self, name: str) -> bool:
        """加载一个插件"""
        if name in self.plugins:
            return True
        path = os.path.join(PLUGIN_DIR, f"{name}.py")
        if not os.path.exists(path):
            return False
        try:
            spec = importlib.util.spec_from_file_location(f"plugin_{name}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.plugins[name] = module

            # Register plugin tools
            if hasattr(module, "register"):
                result = module.register()
                if isinstance(result, dict):
                    for t in result.get("tools", []):
                        self.tools[t["name"]] = t
                    for r in result.get("routes", []):
                        self.routes[r["path"]] = r["handler"]
                    for hook in result.get("hooks", []):
                        if hook["event"] in self.hooks:
                            self.hooks[hook["event"]].append(hook["callback"])

            # Call on_start
            if hasattr(module, "on_start"):
                module.on_start()

            print(f"[plugin] loaded: {name}")
            return True
        except Exception as e:
            print(f"[plugin] failed to load {name}: {e}")
            return False

    def unload(self, name: str):
        """卸载插件"""
        if name not in self.plugins:
            return
        module = self.plugins[name]
        if hasattr(module, "on_stop"):
            try:
                module.on_stop()
            except:
                pass
        # Remove plugin tools
        if hasattr(module, "register"):
            try:
                result = module.register()
                for t in result.get("tools", []):
                    self.tools.pop(t["name"], None)
            except:
                pass
        del self.plugins[name]
        print(f"[plugin] unloaded: {name}")

    def reload(self, name: str):
        """重载插件"""
        self.unload(name)
        self.load(name)

    def load_all(self):
        """加载所有插件"""
        for name in self.discover():
            self.load(name)

    def list_plugins(self) -> List[Dict]:
        """列出已加载插件"""
        result = []
        for name, mod in self.plugins.items():
            result.append({
                "name": name,
                "version": getattr(mod, "VERSION", "1.0.0"),
                "description": getattr(mod, "DESCRIPTION", ""),
                "tools": len([t for t in self.tools.values() if t.get("_plugin") == name]),
                "loaded": True
            })
        return result

    def start_watcher(self):
        """启动文件监控 — 插件文件变化自动重载"""
        import hashlib
        def watch():
            file_hashes = {}
            while True:
                try:
                    for f in os.listdir(PLUGIN_DIR):
                        if f.endswith(".py") and not f.startswith("_"):
                            path = os.path.join(PLUGIN_DIR, f)
                            name = f[:-3]
                            with open(path, "rb") as fh:
                                h = hashlib.md5(fh.read()).hexdigest()
                            old = file_hashes.get(name)
                            if old and old != h:
                                self.reload(name)
                            file_hashes[name] = h
                except:
                    pass
                time.sleep(3)
        self._watcher = threading.Thread(target=watch, daemon=True)
        self._watcher.start()

    def fire_hook(self, event: str, *args):
        """触发钩子"""
        for cb in self.hooks.get(event, []):
            try:
                cb(*args)
            except:
                pass

    def get_all_tools(self) -> List[dict]:
        """返回所有内置 + 插件工具列表"""
        import tools as builtin
        all_tools = tools.list_tools()
        for t in self.tools.values():
            all_tools.append({
                "name": t["name"],
                "description": t.get("description", ""),
                "schema": t.get("schema", {})
            })
        return all_tools

    def execute_tool(self, name: str, params: dict) -> dict:
        """执行工具（先查插件，再查内置）"""
        # Check plugins first
        if name in self.tools:
            try:
                handler = self.tools[name]["handler"]
                return handler(**params)
            except Exception as e:
                return {"ok": False, "error": str(e)}
        # Fallback to built-in
        return tools.execute(name, params)


# ═══════ Sample Plugin Template ═══════

SAMPLE_PLUGIN = '''"""
AI Suite Plugin — {name}
"""
VERSION = "1.0.0"
DESCRIPTION = "A sample plugin"

def register():
    """返回插件提供的工具和路由"""
    return {{
        "tools": [
            {{
                "name": "{name}_hello",
                "description": "Say hello",
                "handler": hello,
                "schema": {{"name": {{"type": "string", "description": "Your name", "optional": True}}}}
            }}
        ],
        "routes": [],
        "hooks": []
    }}

def hello(name="World"):
    return {{"ok": True, "message": f"Hello, {{name}}!"}}

def on_start():
    print("[{name}] plugin started")

def on_stop():
    print("[{name}] plugin stopped")
'''

def create_sample_plugin(name: str):
    """创建一个示例插件"""
    path = os.path.join(PLUGIN_DIR, f"{name}.py")
    if os.path.exists(path):
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(SAMPLE_PLUGIN.format(name=name))
    return True


# ═══════ Global instance ═══════

pm = PluginManager()

# ═══════ CLI ═══════

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "list":
            for p in pm.discover():
                loaded = p in pm.plugins
                print(f"  {'[loaded]' if loaded else '[found]'} {p}")
        elif cmd == "load" and len(sys.argv) > 2:
            pm.load(sys.argv[2])
        elif cmd == "load-all":
            pm.load_all()
            print(f"Loaded {len(pm.plugins)} plugins")
        elif cmd == "create" and len(sys.argv) > 2:
            if create_sample_plugin(sys.argv[2]):
                print(f"Created plugin: {sys.argv[2]}")
            else:
                print("Plugin already exists")
    else:
        print(f"Plugins: {pm.discover()}")
        print(f"Dir: {PLUGIN_DIR}")
