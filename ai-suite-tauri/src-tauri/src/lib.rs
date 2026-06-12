use tauri::{
    Manager,
    menu::{Menu, MenuItem},
    tray::{TrayIconBuilder, TrayIconEvent, MouseButton, MouseButtonState},
};
use std::process::{Command, Child};
use std::sync::Mutex;
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt; // CREATE_NO_WINDOW

/// Create a Command with CREATE_NO_WINDOW (suppresses console popups on Windows)
fn silent_command(program: &str) -> Command {
    let mut cmd = Command::new(program);
    #[cfg(target_os = "windows")]
    cmd.creation_flags(0x08000000);
    cmd
}

// ═══════ Single-instance via lock file ═══════

mod single_instance {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use std::ptr::null_mut;

    pub fn try_lock() -> bool {
        unsafe {
            extern "system" {
                fn CreateMutexW(attrs: *const std::ffi::c_void, owner: i32, name: *const u16) -> *mut std::ffi::c_void;
                fn GetLastError() -> u32;
                fn CloseHandle(h: *mut std::ffi::c_void) -> i32;
            }
            const ERROR_ALREADY_EXISTS: u32 = 183;
            let name: Vec<u16> = OsStr::new("Global\\AI_Suite_g0dness_SingleInstance")
                .encode_wide().chain(Some(0)).collect();
            let handle = CreateMutexW(null_mut(), 1, name.as_ptr());
            if handle.is_null() || GetLastError() == ERROR_ALREADY_EXISTS {
                bring_existing_window_to_front();
                if !handle.is_null() { CloseHandle(handle); }
                return false;
            }
            std::mem::forget(handle);
        }
        true
    }

    fn bring_existing_window_to_front() {
        let title: Vec<u16> = OsStr::new("AI Suite - g0dness")
            .encode_wide().chain(Some(0)).collect();
        unsafe {
            extern "system" {
                fn FindWindowW(class: *const u16, title: *const u16) -> *mut std::ffi::c_void;
                fn ShowWindow(hwnd: *mut std::ffi::c_void, cmd: i32) -> i32;
                fn SetForegroundWindow(hwnd: *mut std::ffi::c_void) -> i32;
            }
            const SW_SHOW: i32 = 5;
            let hwnd = FindWindowW(null_mut(), title.as_ptr());
            if !hwnd.is_null() {
                ShowWindow(hwnd, SW_SHOW);
                SetForegroundWindow(hwnd);
            }
        }
    }
}

// Store child Python processes for cleanup on exit
struct AppState {
    ollama: Mutex<Option<Child>>,
    gen_web: Mutex<Option<Child>>,
    orchestrator: Mutex<Option<Child>>,
}


/// Find a working Python executable (system or venv)
fn find_python() -> Option<String> {
    let python_names = ["python", "python3", "py"];
    let extra_paths = [
        // Windows Store Python
        "",
        "C:\\Users\\86538\\AppData\\Local\\Microsoft\\WindowsApps\\",
    ];

    for prefix in &extra_paths {
        for name in &python_names {
            let full = if prefix.is_empty() {
                name.to_string()
            } else {
                format!("{}{}.exe", prefix, name)
            };
            if let Ok(output) = silent_command(&full).arg("--version").output() {
                if output.status.success() {
                    return Some(full);
                }
            }
        }
    }
    None
}

/// Start Ollama if not already running
fn start_ollama() -> Option<Child> {
    // Check if already running
    if let Ok(output) = silent_command("ollama").arg("list").output() {
        if output.status.success() {
            eprintln!("Ollama already running");
            return None;
        }
    }
    // Start ollama serve
    eprintln!("Starting Ollama...");
    silent_command("ollama")
        .arg("serve")
        .spawn()
        .inspect_err(|e| eprintln!("Ollama start failed: {}", e))
        .ok()
}

/// Start both Python backend servers
fn start_servers(home: &str) -> (Option<Child>, Option<Child>, Option<Child>) {
    let python = find_python().unwrap_or_else(|| "python".to_string());

    let ollama = start_ollama();

    let gen_web = silent_command(&python)
        .arg(format!("{}/gen_web.py", home))
        .spawn()
        .inspect_err(|e| eprintln!("gen_web start failed: {}", e))
        .ok();

    let orchestrator = silent_command(&python)
        .arg(format!("{}/model_orchestrator.py", home))
        .spawn()
        .inspect_err(|e| eprintln!("orchestrator start failed: {}", e))
        .ok();

    (ollama, gen_web, orchestrator)
}

fn kill_servers(state: &AppState) {
    if let Ok(mut ollama) = state.ollama.lock() {
        if let Some(ref mut c) = *ollama { c.kill().ok(); }
    }
    if let Ok(mut gw) = state.gen_web.lock() {
        if let Some(ref mut c) = *gw { c.kill().ok(); }
    }
    if let Ok(mut orch) = state.orchestrator.lock() {
        if let Some(ref mut c) = *orch { c.kill().ok(); }
    }
    // Also kill any leftover python processes
    let _ = silent_command("taskkill")
        .args(["/f", "/im", "python.exe"])
        .spawn();
}

#[tauri::command]
fn open_claude_code() {
    silent_command("cmd")
        .args(["/c", "start", "claude"])
        .spawn()
        .ok();
}

#[tauri::command]
fn get_api_url() -> String {
    "http://127.0.0.1:5000".to_string()
}

#[tauri::command]
fn get_orch_url() -> String {
    "http://127.0.0.1:5001".to_string()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Single-instance: if already running, bring existing window to front and exit
    if !single_instance::try_lock() {
        std::process::exit(0);
    }

    let home = std::env::var("USERPROFILE").unwrap_or_else(|_| "C:/Users/86538".to_string());
    let (ollama, gw, orch) = start_servers(&home);

    // Background: register global hotkey Ctrl+Shift+A → show window
    std::thread::spawn(|| {
        use std::ffi::OsStr;
        use std::os::windows::ffi::OsStrExt;
        use std::ptr::null_mut;

        unsafe extern "system" {
            fn RegisterHotKey(hwnd: *mut std::ffi::c_void, id: i32, fsModifiers: u32, vk: u32) -> i32;
            fn GetMessageW(msg: *mut std::ffi::c_void, hwnd: *mut std::ffi::c_void, min: u32, max: u32) -> i32;
            fn PeekMessageW(msg: *mut std::ffi::c_void, hwnd: *mut std::ffi::c_void, min: u32, max: u32, remove: u32) -> i32;
            fn FindWindowW(class: *const u16, title: *const u16) -> *mut std::ffi::c_void;
            fn ShowWindow(hwnd: *mut std::ffi::c_void, cmd: i32) -> i32;
            fn SetForegroundWindow(hwnd: *mut std::ffi::c_void) -> i32;
        }
        const MOD_CONTROL: u32 = 0x0002;
        const MOD_SHIFT: u32 = 0x0004;
        const MOD_NOREPEAT: u32 = 0x4000;
        const VK_A: u32 = 0x41;
        const SW_SHOW: i32 = 5;
        const WM_HOTKEY: u32 = 0x0312;

        // Register Ctrl+Shift+A
        unsafe {
            if RegisterHotKey(null_mut(), 1, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_A) == 0 {
                return; // Failed to register
            }
        }

        // Message loop — wait for hotkey
        let mut msg: [u8; 48] = [0; 48]; // MSG struct
        loop {
            let ret = unsafe { GetMessageW(msg.as_mut_ptr() as *mut _, null_mut(), 0, 0) };
            if ret <= 0 { break; }
            // Check if it's our hotkey
            let message = u32::from_ne_bytes([msg[4], msg[5], msg[6], msg[7]]);
            if message == WM_HOTKEY {
                let title: Vec<u16> = OsStr::new("AI Suite - g0dness")
                    .encode_wide().chain(Some(0)).collect();
                unsafe {
                    let hwnd = FindWindowW(null_mut(), title.as_ptr());
                    if !hwnd.is_null() {
                        ShowWindow(hwnd, SW_SHOW);
                        SetForegroundWindow(hwnd);
                    }
                }
            }
        }
    });

    // Background: notify when services are ready
    std::thread::spawn(|| {
        for _ in 0..60 {
            std::thread::sleep(std::time::Duration::from_secs(1));
            if std::net::TcpStream::connect_timeout(
                &"127.0.0.1:5001".parse().unwrap(),
                std::time::Duration::from_secs(2),
            ).is_ok()
            {
                let ps = r#"
                [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
                $t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
                $t.GetElementsByTagName("text").Item(0).AppendChild($t.CreateTextNode("AI Suite 已就绪")) > $null
                $t.GetElementsByTagName("text").Item(1).AppendChild($t.CreateTextNode("所有服务已启动，可以开始使用")) > $null
                $n = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("AI Suite")
                $n.Show([Windows.UI.Notifications.ToastNotification]::new($t))
                "#;
                let _ = silent_command("powershell")
                    .args(["-Command", ps])
                    .spawn();
                break;
            }
        }
    });

    tauri::Builder::default()
        .manage(AppState {
            ollama: Mutex::new(ollama),
            gen_web: Mutex::new(gw),
            orchestrator: Mutex::new(orch),
        })
        .setup(|app| {
            // Build tray menu items
            let show_item = MenuItem::with_id(app, "show", "显示窗口", true, None::<&str>)?;
            let agent_item = MenuItem::with_id(app, "agent", "启动 Agent", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &agent_item, &quit_item])?;

            let icon = tauri::image::Image::from_bytes(
                include_bytes!("../icons/icon.png")
            ).expect("Failed to load tray icon");

            TrayIconBuilder::new()
                .icon(icon)
                .menu(&menu)
                .tooltip("AI Suite — g0dness")
                .on_menu_event(|app, event| {
                    match event.id().as_ref() {
                        "show" => {
                            if let Some(w) = app.get_webview_window("main") {
                                w.show().ok();
                                w.set_focus().ok();
                            }
                        }
                        "agent" => {
                            // Show window and switch to agent mode via eval
                            if let Some(w) = app.get_webview_window("main") {
                                w.show().ok();
                                w.set_focus().ok();
                                let _ = w.eval("if(typeof switchMode==='function') switchMode('agent')");
                            }
                        }
                        "quit" => {
                            let state = app.state::<AppState>();
                            kill_servers(&state);
                            // Clean up lock file
                            let _ = std::fs::remove_file(
                                std::path::PathBuf::from(
                                    std::env::var("USERPROFILE").unwrap_or_default()
                                ).join(".ai-suite").join("app.lock")
                            );
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event {
                        if let Some(w) = tray.app_handle().get_webview_window("main") {
                            w.show().ok();
                            w.set_focus().ok();
                        }
                    }
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                window.hide().ok();
            }
        })
        .invoke_handler(tauri::generate_handler![
            open_claude_code,
            get_api_url,
            get_orch_url,
        ])
        .run(tauri::generate_context!())
        .expect("error running AI Suite");
}
