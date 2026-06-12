"""
AI Suite — Tool Smoke Tests
Run: PYTHONIOENCODING=utf-8 python test_tools.py
"""
import sys, os, tempfile, json
import tools

PASS = 0
FAIL = 0
SKIP = 0

def test(name, fn, *args, **kwargs):
    global PASS, FAIL, SKIP
    try:
        result = fn(*args, **kwargs)
        ok = result.get("ok", False)
        if ok:
            PASS += 1
            print(f"  OK {name}")
        else:
            FAIL += 1
            err = result.get("error", "unknown")[:80]
            print(f"  FAIL {name}: {err}")
        return result
    except Exception as e:
        FAIL += 1
        print(f"  CRASH {name}: {type(e).__name__}: {e}")

def skip(name, reason=""):
    global SKIP
    SKIP += 1
    print(f"  SKIP {name}: {reason}")

# File Tools
print("\n--- File Tools ---")
td = tempfile.gettempdir()
tf = os.path.join(td, "test_aisuite.txt")

test("write_file", tools.tool_write_file, tf, "hello world")
test("read_file", tools.tool_read_file, tf)
test("list_dir", tools.tool_list_dir, td)
test("find_files", tools.tool_find_files, td, "*.txt", 5)
r = test("copy_file", tools.tool_copy_file, tf, tf + ".bak")
if r and r.get("ok"):
    test("delete_file", tools.tool_delete_file, tf + ".bak", True)
os.unlink(tf)

# Shell Tools
print("\n--- Shell Tools ---")
test("shell echo", tools.tool_shell, "echo hello")
test("run_python", tools.tool_run_python, "print(42)")

# Web Tools
print("\n--- Web Tools ---")
skip("web_fetch", "needs internet")
skip("web_search", "needs internet")

# System Tools
print("\n--- System Tools ---")
r = test("system_info", tools.tool_system_info)
if r and r.get("ok"):
    info = r.get("info", {})
    print(f"     RAM={info.get('ram_total_gb')}GB Disk={info.get('disk_total_gb')}GB")

test("list_processes", tools.tool_list_processes)

# Desktop Tools
print("\n--- Desktop Tools ---")
test("mouse_pos", tools.tool_get_mouse_pos)
test("get_windows", tools.tool_get_windows)
test("get_volume", tools.tool_get_volume)

# Clipboard Tools
print("\n--- Clipboard Tools ---")
test("clipboard_write", tools.tool_clipboard_write, "ai-suite test")
test("clipboard_read", tools.tool_clipboard_read)

# Document Tools
print("\n--- Document Tools ---")
try:
    from pptx import Presentation
    slides = [{"title": "Test Slide", "content": ["Item 1", "Item 2"]}]
    test("create_pptx", tools.tool_create_pptx, "Test", json.dumps(slides))
except ImportError:
    skip("create_pptx", "needs python-pptx")

try:
    import ezdxf
    entities = [{"type": "line", "x1": 0, "y1": 0, "x2": 50, "y2": 50, "layer": "outline"},
                {"type": "circle", "cx": 25, "cy": 25, "radius": 10, "layer": "holes"}]
    test("create_dxf", tools.tool_create_dxf, "test_drawing", json.dumps(entities))
except ImportError:
    skip("create_dxf", "needs ezdxf")

# Video Tools
print("\n--- Video Tools ---")
ff = tools._find_ffmpeg()
if ff:
    print(f"     ffmpeg: {ff}")
    import subprocess as sp
    test_mp4 = os.path.join(td, "test_vid.mp4")
    try:
        sp.run([ff, "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                "-c:v", "libx264", "-c:a", "aac", "-t", "1", "-y", test_mp4],
               capture_output=True, timeout=10,
               creationflags=sp.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if os.path.exists(test_mp4):
            test("video_info", tools.tool_video_info, test_mp4)
            test("video_trim", tools.tool_video_trim, test_mp4, test_mp4 + ".trim.mp4", duration="0.5")
            test("video_resize", tools.tool_video_resize, test_mp4, test_mp4 + ".resize.mp4", 160, 120)
            test("video_extract_audio", tools.tool_video_extract_audio, test_mp4)
            test("video_extract_frames", tools.tool_video_extract_frames, test_mp4,
                 output_dir=os.path.join(td, "test_frames"), fps=2, duration=0.5)
            test("video_compress", tools.tool_video_compress, test_mp4, test_mp4 + ".comp.mp4", 30)
            test("video_to_gif", tools.tool_video_to_gif, test_mp4, test_mp4 + ".gif", duration=0.5)
            # Cleanup
            for f in os.listdir(td):
                if f.startswith("test_vid") or f.startswith("test_frames"):
                    fp = os.path.join(td, f)
                    try:
                        if os.path.isfile(fp): os.unlink(fp)
                        elif os.path.isdir(fp): __import__('shutil').rmtree(fp)
                    except: pass
    except Exception as e:
        skip("video_*", f"ffmpeg error: {e}")
else:
    for vt in ["video_info","video_trim","video_resize","video_extract_audio",
               "video_speed","video_to_gif","video_compress","video_crop"]:
        skip(vt, "ffmpeg not found")

# Summary
total = PASS + FAIL + SKIP
print(f"\n{'='*40}")
print(f"{PASS} passed, {FAIL} failed, {SKIP} skipped ({total} total)")
if FAIL:
    print(f"FAIL: {FAIL} tests failed")
    sys.exit(1)
else:
    print("All tests passed")
