"""AI 助手桌面版 — 双击运行，无需浏览器。关闭窗口转后台托盘。单实例。"""
import subprocess, sys, time, os, threading, socket, shutil, glob as _glob

# ═══════ 单实例检测 ═══════
import ctypes
from ctypes import wintypes

_MUTEX_NAME = "Global\\AI_Suite_SingleInstance"
_kernel32 = ctypes.windll.kernel32
_CreateMutexW = _kernel32.CreateMutexW
_CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
_CreateMutexW.restype = wintypes.HANDLE
_GetLastError = _kernel32.GetLastError
ERROR_ALREADY_EXISTS = 183

_mutex = _CreateMutexW(None, False, _MUTEX_NAME)
if _GetLastError() == ERROR_ALREADY_EXISTS:
    # 已有实例 — 找到窗口并提到前台
    import win32gui, win32con
    hwnd = win32gui.FindWindow(None, "AI Suite - 多模型助手")
    if hwnd:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
    sys.exit(0)

# ═══════ 获取真实 Python 解释器 ═══════
def _get_real_python():
    if getattr(sys, 'frozen', False):
        for n in ['python', 'python3', 'py']:
            found = shutil.which(n)
            if found:
                return found
        for ver in ['312', '311', '310', '313']:
            p = f'C:/Python{ver}/python.exe'
            if os.path.exists(p):
                return p
        for ver in ['312', '311', '310']:
            p = os.path.expandvars(f'%LOCALAPPDATA%\\Programs\\Python\\Python{ver}\\python.exe')
            if os.path.exists(p):
                return p
        raise RuntimeError(
            "未找到 Python 解释器。\n\n"
            "请安装 Python 3.12 并添加到 PATH：\n"
            "https://www.python.org/downloads/\n\n"
            "或安装到 C:\\Python312\\"
        )
    return sys.executable

_PYTHON = _get_real_python()

# ═══════ 清理旧的 PyInstaller 临时文件 ═══════
_temp_base = os.environ.get("LOCALAPPDATA", os.environ.get("TEMP", ""))
_temp_dir = os.path.join(_temp_base, "Temp") if "LOCALAPPDATA" in _temp_base.lower() or "localappdata" in _temp_base.lower() else _temp_base
_mei_pattern = os.path.join(_temp_dir, "_MEI*")
try:
    for _path in _glob.glob(_mei_pattern):
        try: shutil.rmtree(_path, ignore_errors=True)
        except: pass
except: pass

# ═══════ 端口工具 ═══════
def wait_port(port, timeout=30):
    for _ in range(timeout):
        try:
            s = socket.socket(); s.connect(('127.0.0.1', port)); s.close()
            return True
        except:
            time.sleep(0.5)
    return False

def is_port_open(port):
    try:
        s = socket.socket(); s.settimeout(1); s.connect(('127.0.0.1', port)); s.close()
        return True
    except:
        return False

def start_service(args, name, port):
    if is_port_open(port):
        return None
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW)

# ═══════ 启动子服务 ═══════
procs = []
p = start_service([_PYTHON, "C:/Users/86538/gen_web.py"], "Gen Web", 5000)
if p: procs.append(p)
p = start_service([_PYTHON, "C:/Users/86538/model_orchestrator.py"], "Orchestrator", 5001)
if p: procs.append(p)

# ═══════ 系统托盘 ═══════
_tray_exit = False
_window_visible = True
_webview_hwnd = None

def _get_webview_hwnd():
    """查找 webview 窗口句柄"""
    import win32gui
    hwnd = win32gui.FindWindow(None, "AI Suite - 多模型助手")
    return hwnd if hwnd else None

def _hide_window():
    global _window_visible
    import win32gui, win32con
    hwnd = _get_webview_hwnd()
    if hwnd:
        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
        _window_visible = False

def _show_window():
    global _window_visible
    import win32gui, win32con
    hwnd = _get_webview_hwnd()
    if hwnd:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
        _window_visible = True

def _tray_thread():
    """Windows 系统托盘图标线程"""
    import win32gui, win32con, win32api, ctypes

    WM_TRAY = win32con.WM_USER + 1
    TRAY_ID = 1

    # 注册隐藏窗口类
    hinst = win32api.GetModuleHandle(None)
    wc = win32gui.WNDCLASS()
    wc.lpfnWndProc = lambda hwnd, msg, wp, lp: _tray_wndproc(hwnd, msg, wp, lp)
    wc.lpszClassName = "AISuiteTray"
    wc.hInstance = hinst
    win32gui.RegisterClass(wc)

    tray_hwnd = win32gui.CreateWindow("AISuiteTray", "", 0, 0, 0, 0, 0, 0, 0, hinst, None)

    # 从 EXE 提取图标
    try:
        hicon = win32gui.ExtractIcon(0, sys.executable, 0)
    except:
        hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

    flags = win32gui.NIF_MESSAGE | win32gui.NIF_ICON | win32gui.NIF_TIP
    tip = "AI Suite - 多模型助手"

    # 用 ctypes 创建托盘图标
    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint32),
            ("hWnd", ctypes.c_void_p),
            ("uID", ctypes.c_uint32),
            ("uFlags", ctypes.c_uint32),
            ("uCallbackMessage", ctypes.c_uint32),
            ("hIcon", ctypes.c_void_p),
            ("szTip", ctypes.c_wchar * 128),
        ]
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            _fields_.insert(1, ("_pad", ctypes.c_uint32))

    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    nid.hWnd = tray_hwnd
    nid.uID = TRAY_ID
    nid.uFlags = flags
    nid.uCallbackMessage = WM_TRAY
    nid.hIcon = hicon
    nid.szTip = tip

    ctypes.windll.shell32.Shell_NotifyIconW(0x00000000, ctypes.byref(nid))  # NIM_ADD=0

    # 消息循环
    global _tray_exit
    while not _tray_exit:
        win32gui.PumpWaitingMessages()
        time.sleep(0.1)

    # 删除托盘图标
    ctypes.windll.shell32.Shell_NotifyIconW(0x00000002, ctypes.byref(nid))  # NIM_DELETE=2
    win32gui.DestroyWindow(tray_hwnd)


def _tray_wndproc(hwnd, msg, wparam, lparam):
    """托盘图标消息处理"""
    global _tray_exit
    import win32gui, win32con

    WM_TRAY = win32con.WM_USER + 1

    if msg == WM_TRAY:
        if lparam == win32con.WM_LBUTTONDBLCLK:
            _show_window()
        elif lparam == win32con.WM_RBUTTONUP:
            menu = win32gui.CreatePopupMenu()
            win32gui.AppendMenu(menu, win32con.MF_STRING, 1, '显示窗口')
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, '')
            win32gui.AppendMenu(menu, win32con.MF_STRING, 2, '退出')
            pos = win32gui.GetCursorPos()
            win32gui.SetForegroundWindow(hwnd)
            cmd = win32gui.TrackPopupMenu(menu, win32con.TPM_RETURNCMD | win32con.TPM_RIGHTBUTTON,
                                          pos[0], pos[1], 0, hwnd, None)
            win32gui.DestroyMenu(menu)
            if cmd == 1:
                _show_window()
            elif cmd == 2:
                _tray_exit = True
                _do_quit()
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


_quitting = False

def _do_quit():
    """退出程序 — 杀所有相关进程"""
    global _quitting
    _quitting = True
    for p in procs:
        try: p.terminate()
        except: pass
    for exe in ["python.exe", "python3.12.exe", "python3.exe"]:
        subprocess.run(["taskkill", "/f", "/im", exe],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    os._exit(0)

def _on_closing():
    global _quitting
    if _quitting:
        return True  # 允许关闭
    _hide_window()
    return False


def _on_closing():
    """窗口 X 按钮 → 隐藏到托盘"""
    _hide_window()
    return False  # 阻止实际关闭


# ═══════ 加载页 ═══════
LOADING_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AI Suite</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:#0f0f0f;color:#e0e0e0;min-height:100vh;
  display:flex;flex-direction:column;justify-content:center;align-items:center}
.spinner{width:44px;height:44px;border:3px solid #2a2a2a;border-top-color:#a78bfa;
  border-radius:50%;animation:spin .7s linear infinite;margin-bottom:20px}
@keyframes spin{to{transform:rotate(360deg)}}
h2{font-size:20px;background:linear-gradient(135deg,#a78bfa,#f472b6);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px}
p{color:#666;font-size:13px}
</style>
<script>
let attempts=0;
function check(){
  fetch('http://127.0.0.1:5000/api/status')
    .then(r=>{if(r.ok)location.replace('/chat');})
    .catch(()=>{attempts++;if(attempts<60)setTimeout(check,500);});
}
check();
</script>
</head>
<body>
<div class="spinner"></div>
<h2>AI Suite</h2>
<p>服务启动中...</p>
</body>
</html>"""

# ═══════ GUI ═══════
import webview

window = webview.create_window(
    title="AI Suite - 多模型助手",
    html=LOADING_HTML,
    width=1100,
    height=800,
    resizable=True,
    min_size=(800, 600),
)

# 窗口关闭 → 隐藏到托盘
window.events.closing += _on_closing

# 启动托盘线程
threading.Thread(target=_tray_thread, daemon=True).start()

# 后台等所有服务就绪后跳转到真实页面
def _wait_and_go():
    ok0 = wait_port(5000, timeout=30)
    ok1 = wait_port(5001, timeout=30)
    if ok0 and ok1:
        try:
            window.load_url("http://127.0.0.1:5000/chat")
        except:
            pass

threading.Thread(target=_wait_and_go, daemon=True).start()

# ═══════ 启动 GUI 主循环 ═══════
webview.start()

# webview.start() 返回 = 窗口被实际关闭了 → 清理退出
for p in procs:
    try: p.terminate()
    except: pass
sys.exit(0)
