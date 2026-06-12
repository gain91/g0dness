"""
AI Suite — Tool System (MCP-compatible)
工具注册 + 执行引擎，通过 /api/tools 暴露给前端
"""
import os, subprocess, json, tempfile

TOOLS = {}

def register(name, description, handler, schema=None):
    TOOLS[name] = {"name": name, "description": description, "handler": handler, "schema": schema or {}}

# ─── File Tools ───

def tool_read_file(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read(50000)
        return {"ok": True, "content": content, "truncated": len(content) >= 50000}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_list_dir(path):
    try:
        items = []
        for name in os.listdir(path):
            full = os.path.join(path, name)
            items.append({"name": name, "type": "dir" if os.path.isdir(full) else "file",
                          "size": os.path.getsize(full) if os.path.isfile(full) else 0})
        return {"ok": True, "items": sorted(items, key=lambda x: (x["type"], x["name"]))[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_write_file(path, content):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "path": path}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─── Sandbox ───

DANGEROUS_PATTERNS = [
    r'rm\s+-rf\s+/', r'del\s+/[fsq]\s+\w:\\', r'format\s', r'fdisk\s',
    r'mkfs\.', r'dd\s+if=', r'>\s*/dev/', r'chmod\s+777\s+/',
    r'shutdown\s', r'reboot', r'halt', r'poweroff',
    r'wget\s.*\|.*sh', r'curl\s.*\|.*bash',
]

SAFE_WRITE_DIRS = [
    os.path.expanduser("~"),
    os.path.expanduser("~/Desktop"),
    os.path.expanduser("~/Documents"),
    os.path.expanduser("~/Downloads"),
    os.path.expanduser("~/.ai-suite"),
    tempfile.gettempdir(),
    os.getcwd(),
]

def _sandbox_shell(command: str) -> dict:
    """Check shell command for dangerous patterns"""
    import re
    cmd_lower = command.lower()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, cmd_lower):
            return {"ok": False, "error": f"Blocked dangerous command pattern: {pattern}"}
    return {"ok": True}

def _sandbox_path(path: str) -> dict:
    """Check if file path is safe to write to"""
    try:
        abs_path = os.path.abspath(path).lower()
    except:
        return {"ok": False, "error": f"Invalid path: {path}"}
    for safe_dir in SAFE_WRITE_DIRS:
        try:
            if abs_path.startswith(os.path.abspath(safe_dir).lower()):
                return {"ok": True}
        except:
            pass
    return {"ok": False, "error": f"Path '{path}' not in allowed directories. Must be under ~/ or %TEMP%."}

# ─── Shell Tool ───

def tool_shell(command, cwd=None):
    # Sandbox check
    check = _sandbox_shell(command)
    if not check["ok"]:
        return check
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True,
                                timeout=30, cwd=cwd or os.path.expanduser("~"),
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return {"ok": True, "stdout": result.stdout[-5000:], "stderr": result.stderr[-2000:],
                "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Command timed out (30s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─── Clipboard Tool ───

def tool_clipboard_read():
    try:
        import tkinter as tk
        root = tk.Tk(); root.withdraw()
        text = root.clipboard_get()
        root.destroy()
        return {"ok": True, "text": text[:10000]}
    except:
        try:
            result = subprocess.run(["powershell", "-Command", "Get-Clipboard"],
                                    capture_output=True, text=True, timeout=5,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            return {"ok": True, "text": result.stdout[:10000]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

def tool_clipboard_write(text):
    try:
        # Base64 encode to avoid injection
        import base64
        encoded = base64.b64encode(text.encode("utf-8")).decode()
        ps = f"[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{encoded}')) | Set-Clipboard"
        subprocess.run(["powershell", "-Command", ps],
                       capture_output=True, timeout=5,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─── Web Tool ───

def tool_web_fetch(url):
    import urllib.request as ur
    try:
        req = ur.Request(url, headers={"User-Agent": "AI-Suite/1.0"})
        resp = ur.urlopen(req, timeout=15)
        content = resp.read().decode("utf-8", errors="replace")[:10000]
        return {"ok": True, "content": content, "status": resp.status}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_web_search(query):
    import urllib.request as ur
    try:
        url = f"https://html.duckduckgo.com/html/?q={ur.quote(query)}"
        req = ur.Request(url, headers={"User-Agent": "AI-Suite/1.0"})
        resp = ur.urlopen(req, timeout=15)
        content = resp.read().decode("utf-8", errors="replace")[:8000]
        # crude extraction of result snippets
        results = []
        import re
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', content, re.DOTALL)
        for s in snippets[:5]:
            results.append(re.sub(r'<[^>]+>', '', s).strip())
        return {"ok": True, "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─── Desktop Tools (v3.0) ───

def tool_open_browser(url):
    """在默认浏览器打开 URL"""
    try:
        subprocess.run(["cmd", "/c", "start", url], timeout=5,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return {"ok": True, "url": url}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_screenshot(path=None):
    """截取屏幕截图，返回文件路径"""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        img = root.grab_screen()
        save_path = path or os.path.expanduser(f"~/Desktop/screenshot_{int(__import__('time').time())}.png")
        img.save(save_path, "PNG")
        root.destroy()
        return {"ok": True, "path": save_path, "size": f"{img.width}x{img.height}"}
    except ImportError:
        return {"ok": False, "error": "PIL/Pillow not available. Install: pip install Pillow"}
    except Exception as e:
        # Fallback: PowerShell screenshot
        try:
            save_path = path or os.path.expanduser("~/Desktop/screenshot.png")
            ps = f'''
            Add-Type -AssemblyName System.Windows.Forms,System.Drawing
            $screen = [System.Windows.Forms.Screen]::PrimaryScreen
            $bmp = New-Object System.Drawing.Bitmap($screen.Bounds.Width, $screen.Bounds.Height)
            $g = [System.Drawing.Graphics]::FromImage($bmp)
            $g.CopyFromScreen(0, 0, 0, 0, $bmp.Size)
            $bmp.Save("{save_path.replace(chr(92), chr(92)+chr(92))}")
            $g.Dispose()
            '''
            subprocess.run(["powershell", "-Command", ps], timeout=30,
                          capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            return {"ok": True, "path": save_path, "method": "powershell"}
        except Exception as e2:
            return {"ok": False, "error": f"{e} | fallback: {e2}"}

def tool_find_files(directory, pattern="*", max_results=50):
    """递归搜索文件"""
    import fnmatch
    try:
        results = []
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if fnmatch.fnmatch(f, pattern):
                    results.append(os.path.join(root, f))
                    if len(results) >= max_results:
                        return {"ok": True, "files": results, "truncated": True}
            if len(results) >= max_results:
                break
        return {"ok": True, "files": results, "truncated": False}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_run_python(code, timeout=10):
    """在隔离环境中执行 Python 代码（用于计算、数据处理等）"""
    import sys
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = ""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=timeout,
            cwd=os.path.expanduser("~"),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            env=env
        )
        return {
            "ok": True,
            "stdout": result.stdout[-5000:],
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Timeout ({timeout}s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Register all tools ───
register("read_file", "Read a file's contents", tool_read_file,
         {"path": {"type": "string", "description": "Absolute file path"}})
register("list_dir", "List directory contents", tool_list_dir,
         {"path": {"type": "string", "description": "Directory path"}})
register("write_file", "Write content to a file", tool_write_file,
         {"path": {"type": "string"}, "content": {"type": "string"}})
register("find_files", "Recursively search for files by name pattern", tool_find_files,
         {"directory": {"type": "string"}, "pattern": {"type": "string", "optional": True}})
register("shell", "Execute a shell command (30s timeout)", tool_shell,
         {"command": {"type": "string"}, "cwd": {"type": "string", "optional": True}})
register("run_python", "Execute Python code in isolation (for calculations, data processing)", tool_run_python,
         {"code": {"type": "string"}, "timeout": {"type": "number", "optional": True}})
register("clipboard_read", "Read text from clipboard", tool_clipboard_read, {})
register("clipboard_write", "Write text to clipboard", tool_clipboard_write,
         {"text": {"type": "string"}})
register("web_fetch", "Fetch a web page content", tool_web_fetch,
         {"url": {"type": "string"}})
register("web_search", "Search the web via DuckDuckGo", tool_web_search,
         {"query": {"type": "string"}})
register("open_browser", "Open a URL in the default browser", tool_open_browser,
         {"url": {"type": "string"}})
register("screenshot", "Take a screenshot and save to file", tool_screenshot,
         {"path": {"type": "string", "optional": True}})

def tool_ocr(image_path=None):
    """OCR 识别图片文字（Windows 内置 OCR 引擎）"""
    try:
        # 先截图如果没有指定路径
        target = image_path
        if not target:
            import time
            target = os.path.expanduser(f"~/Desktop/ocr_{int(time.time())}.png")
            r = tool_screenshot(target)
            if not r.get("ok"):
                return {"ok": False, "error": "截图失败: " + r.get("error", "")}

        ps = f'''
        Add-Type -AssemblyName System.Drawing
        $bmp = [System.Drawing.Bitmap]::FromFile("{target.replace(chr(92), chr(92)+chr(92))}")
        # Use Windows.Media.Ocr for built-in OCR
        [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] > $null
        [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime] > $null
        [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] > $null
        [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime] > $null

        $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
        $encoder = [Windows.Graphics.Imaging.BitmapEncoder]::CreateAsync([Windows.Graphics.Imaging.BitmapEncoder]::PngEncoderId(), $stream).GetAwaiter().GetResult()
        $encoder.SetSoftwareBitmap([Windows.Graphics.Imaging.SoftwareBitmap]::CreateCopyFromBuffer(
            [Windows.Security.Cryptography.CryptographicBuffer]::CreateFromByteArray((
                Get-Content "{target.replace(chr(92), chr(92)+chr(92))}" -Encoding Byte
            )), [Windows.Graphics.Imaging.BitmapPixelFormat]::Rgba8, $bmp.Width, $bmp.Height
        ))
        $encoder.FlushAsync().GetAwaiter().GetResult()
        $stream.Seek(0) > $null
        $decoder = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream).GetAwaiter().GetResult()
        $sb = $decoder.GetSoftwareBitmapAsync().GetAwaiter().GetResult()
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
        if (-not $engine) {{ $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage("zh-Hans") }}
        if (-not $engine) {{ $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage("en") }}
        $result = $engine.RecognizeAsync($sb).GetAwaiter().GetResult()
        $text = ($result.Lines | ForEach-Object {{ ($_.Words | ForEach-Object {{ $_.Text }}) -join " " }}) -join "`n"
        $bmp.Dispose()
        $text
        '''
        result = subprocess.run(["powershell", "-Command", ps],
                               capture_output=True, text=True, timeout=30,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        text = result.stdout.strip()
        if not text:
            # Fallback: Tesseract if installed
            try:
                import subprocess as sp
                r2 = sp.run(["tesseract", target, "stdout", "-l", "chi_sim+eng"],
                           capture_output=True, text=True, timeout=30)
                if r2.stdout.strip():
                    text = r2.stdout.strip()
            except:
                pass
        return {"ok": True, "text": text[:10000], "source": target}
    except Exception as e:
        return {"ok": False, "error": str(e)}

register("ocr", "Extract text from an image using OCR (Windows built-in)", tool_ocr,
         {"image_path": {"type": "string", "optional": True, "description": "Image file path, omit to screenshot first"}})

# ─── Desktop Control Tools (v3.1) ───

def tool_click(x: int, y: int, button: str = "left"):
    """模拟鼠标点击"""
    try:
        import ctypes
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_RIGHTDOWN = 0x0008
        MOUSEEVENTF_RIGHTUP = 0x0010
        ctypes.windll.user32.SetCursorPos(x, y)
        if button == "right":
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        else:
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return {"ok": True, "x": x, "y": y, "button": button}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_type_text(text: str, interval: float = 0.02):
    """模拟键盘输入"""
    try:
        import ctypes
        import time as _time
        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002
        for ch in text:
            vk = ord(ch)
            ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_UNICODE, 0)
            ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)
            _time.sleep(interval)
        return {"ok": True, "length": len(text)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_press_key(key: str):
    """模拟按键（enter, escape, tab, space, backspace, delete, 方向键等）"""
    VK_MAP = {
        "enter": 0x0D, "return": 0x0D, "escape": 0x1B, "esc": 0x1B,
        "tab": 0x09, "space": 0x20, "backspace": 0x08, "delete": 0x2E,
        "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
        "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
        "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
        "f11": 0x7A, "f12": 0x7B,
        "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
    }
    vk = VK_MAP.get(key.lower())
    if vk is None:
        return {"ok": False, "error": f"Unknown key: {key}. Use: {', '.join(VK_MAP.keys())}"}
    try:
        import ctypes
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        return {"ok": True, "key": key}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_get_windows():
    """获取当前打开的窗口列表"""
    import ctypes
    try:
        user32 = ctypes.windll.user32
        windows = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_callback(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, buf, 256)
                title = buf.value
                if title and len(title.strip()) > 0:
                    windows.append({"hwnd": str(hwnd), "title": title})
            return True
        user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
        return {"ok": True, "windows": windows[:30]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_focus_window(title_match: str):
    """根据标题匹配聚焦窗口"""
    import ctypes
    try:
        user32 = ctypes.windll.user32
        found = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_callback(hwnd, _lparam):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            title = buf.value
            if title and title_match.lower() in title.lower():
                found.append(hwnd)
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
                return False  # Stop enumeration
            return True
        user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
        if found:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(found[0], buf, 256)
            return {"ok": True, "focused": buf.value}
        return {"ok": False, "error": f"Window not found: {title_match}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_move_mouse(x: int, y: int):
    """移动鼠标到指定坐标（不点击）"""
    try:
        import ctypes
        ctypes.windll.user32.SetCursorPos(x, y)
        return {"ok": True, "x": x, "y": y}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def tool_get_mouse_pos():
    """获取当前鼠标位置"""
    try:
        import ctypes
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return {"ok": True, "x": pt.x, "y": pt.y}
    except Exception as e:
        return {"ok": False, "error": str(e)}

register("click", "Click mouse at (x, y)", tool_click,
         {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "optional": True}})
register("move_mouse", "Move mouse to (x, y) without clicking", tool_move_mouse,
         {"x": {"type": "integer"}, "y": {"type": "integer"}})
register("mouse_pos", "Get current mouse position", tool_get_mouse_pos, {})
register("type_text", "Simulate typing text via keyboard", tool_type_text,
         {"text": {"type": "string"}, "interval": {"type": "number", "optional": True}})
register("press_key", "Press a key (enter, escape, tab, f1-f12, arrows...)", tool_press_key,
         {"key": {"type": "string"}})
register("get_windows", "List all visible window titles", tool_get_windows, {})
register("focus_window", "Focus a window by title (partial match)", tool_focus_window,
         {"title_match": {"type": "string"}})

def execute(tool_name, params):
    if tool_name not in TOOLS:
        return {"ok": False, "error": f"Unknown tool: {tool_name}"}
    try:
        return TOOLS[tool_name]["handler"](**params)
    except TypeError as e:
        return {"ok": False, "error": f"Invalid params: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def list_tools():
    return [{"name": t["name"], "description": t["description"], "schema": t["schema"]}
            for t in TOOLS.values()]
