use std::fs::OpenOptions;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::Manager;

#[derive(Default)]
struct BackendRuntime {
    child: Option<Child>,
}

#[derive(Default)]
struct BackendState(Mutex<BackendRuntime>);

fn data_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    if let Some(path) = std::env::var_os("DZMM_NEXT_DATA_DIR") {
        return Ok(path.into());
    }
    app.path()
        .app_data_dir()
        .map(|path| path.join("v3"))
        .map_err(|error| format!("app data directory: {error}"))
}

fn backend_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    if let Some(path) = std::env::var_os("DZMM_NEXT_BACKEND_PATH") {
        return Ok(path.into());
    }
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("resource directory: {error}"))?;
    let executable = if cfg!(windows) {
        "dzmm-next-backend.exe"
    } else {
        "dzmm-next-backend"
    };
    Ok(resource_dir
        .join("backend-runtime")
        .join("dzmm-next-backend")
        .join(executable))
}

fn backend_port() -> String {
    if let Ok(configured) = std::env::var("DZMM_NEXT_PORT") {
        return configured;
    }
    if TcpListener::bind(("127.0.0.1", 8765)).is_ok() {
        return "8765".to_owned();
    }
    TcpListener::bind(("127.0.0.1", 0))
        .ok()
        .and_then(|listener| listener.local_addr().ok())
        .map(|address| address.port().to_string())
        .unwrap_or_else(|| "8765".to_owned())
}

fn stop_runtime(runtime: &mut BackendRuntime) {
    if let Some(mut process) = runtime.child.take() {
        let _ = process.kill();
        let _ = process.wait();
    }
}

fn stop_backend(state: &BackendState) {
    if let Ok(mut runtime) = state.0.lock() {
        stop_runtime(&mut runtime);
    }
}

fn start_runtime(app: &tauri::AppHandle, runtime: &mut BackendRuntime) -> Result<(), String> {
    let executable = backend_path(app)?;
    if !executable.exists() {
        return Err(format!("DZMM 本机服务组件缺失: {}", executable.display()));
    }
    let app_data = data_dir(app)?;
    std::fs::create_dir_all(&app_data).map_err(|error| format!("create app data: {error}"))?;
    let port = backend_port();
    let parent_pid = std::process::id().to_string();
    let log_path = app_data.join("dzmm.log");
    let log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|error| format!("open DZMM log {}: {error}", log_path.display()))?;
    let error_log = log
        .try_clone()
        .map_err(|error| format!("prepare DZMM error log {}: {error}", log_path.display()))?;
    let child = Command::new(&executable)
        .env("DZMM_NEXT_DATA_DIR", &app_data)
        .env("DZMM_NEXT_PORT", &port)
        .env("DZMM_NEXT_PARENT_PID", parent_pid)
        .stdin(Stdio::null())
        .stdout(Stdio::from(log))
        .stderr(Stdio::from(error_log))
        .spawn()
        .map_err(|error| format!("start DZMM 本机服务: {error}"))?;
    runtime.child = Some(child);
    Ok(())
}

#[tauri::command]
fn start_backend(
    app: tauri::AppHandle,
    state: tauri::State<'_, BackendState>,
) -> Result<String, String> {
    let mut runtime = state.0.lock().map_err(|_| "backend state lock poisoned")?;
    stop_runtime(&mut runtime);
    start_runtime(&app, &mut runtime)?;
    Ok(format!("http://127.0.0.1:{}", backend_port()))
}

#[tauri::command]
fn stop_host_backend(state: tauri::State<'_, BackendState>) {
    stop_backend(&state);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(BackendState::default())
        .invoke_handler(tauri::generate_handler![start_backend, stop_host_backend])
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                window.show()?;
                window.set_focus()?;
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                stop_backend(&window.state::<BackendState>());
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build DZMM desktop host");

    app.run(|app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
        ) {
            stop_backend(&app_handle.state::<BackendState>());
        }
    });
}
