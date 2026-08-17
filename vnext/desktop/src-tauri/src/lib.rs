use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::Manager;

#[derive(Default)]
struct BackendRuntime {
    child: Option<Child>,
    lan_gameplay_enabled: bool,
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
    Ok(resource_dir.join("backend-runtime").join(executable))
}

fn backend_port() -> String {
    std::env::var("DZMM_NEXT_PORT").unwrap_or_else(|_| "8765".to_owned())
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
        return Err(format!(
            "vNext backend sidecar is missing: {}",
            executable.display()
        ));
    }
    let app_data = data_dir(app)?;
    std::fs::create_dir_all(&app_data).map_err(|error| format!("create app data: {error}"))?;
    let port = backend_port();
    let host = if runtime.lan_gameplay_enabled {
        "0.0.0.0"
    } else {
        "127.0.0.1"
    };
    let child = Command::new(&executable)
        .env("DZMM_NEXT_DATA_DIR", &app_data)
        .env("DZMM_NEXT_HOST", host)
        .env("DZMM_NEXT_PORT", &port)
        .env(
            "DZMM_NEXT_LAN_GAMEPLAY",
            if runtime.lan_gameplay_enabled {
                "1"
            } else {
                "0"
            },
        )
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("start vNext backend: {error}"))?;
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
fn set_lan_gameplay(
    enabled: bool,
    app: tauri::AppHandle,
    state: tauri::State<'_, BackendState>,
) -> Result<bool, String> {
    let mut runtime = state.0.lock().map_err(|_| "backend state lock poisoned")?;
    if runtime.lan_gameplay_enabled == enabled && runtime.child.is_some() {
        return Ok(enabled);
    }
    let previous = runtime.lan_gameplay_enabled;
    stop_runtime(&mut runtime);
    runtime.lan_gameplay_enabled = enabled;
    if let Err(error) = start_runtime(&app, &mut runtime) {
        runtime.lan_gameplay_enabled = previous;
        if let Err(recovery_error) = start_runtime(&app, &mut runtime) {
            return Err(format!(
                "restart backend for LAN gameplay: {error}; restore previous Host: {recovery_error}"
            ));
        }
        return Err(format!("restart backend for LAN gameplay: {error}"));
    }
    Ok(enabled)
}

#[tauri::command]
fn stop_host_backend(state: tauri::State<'_, BackendState>) {
    stop_backend(&state);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(BackendState::default())
        .invoke_handler(tauri::generate_handler![
            start_backend,
            set_lan_gameplay,
            stop_host_backend
        ])
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                stop_backend(&window.state::<BackendState>());
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to run DZMM Next desktop host");
}
