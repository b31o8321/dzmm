use std::sync::Mutex;

use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};

#[derive(Default)]
struct BackendState {
    child: Mutex<Option<CommandChild>>,
}

#[tauri::command]
async fn start_backend(
    app: tauri::AppHandle,
    state: tauri::State<'_, BackendState>,
    lan_mode: bool,
) -> Result<(), String> {
    // Stop any existing instance.
    {
        let mut guard = state.child.lock().unwrap();
        if let Some(child) = guard.take() {
            let _ = child.kill();
        }
    }

    let host = if lan_mode { "0.0.0.0" } else { "127.0.0.1" };

    let mut cmd = app
        .shell()
        .sidecar("dzmm-backend")
        .map_err(|e| format!("failed to resolve sidecar: {}", e))?
        .env("DZMM_HOST", host)
        .env("DZMM_PORT", "8765");

    if lan_mode {
        // Resolve the bundled frontend dist so the backend can serve it on LAN.
        // tauri.conf.json:bundle.resources copies "../dist" → "frontend-dist/".
        if let Ok(resource_dir) = app.path().resource_dir() {
            let dist = resource_dir.join("frontend-dist");
            if dist.exists() {
                cmd = cmd.env("DZMM_FRONTEND_DIST", dist.to_string_lossy().to_string());
            }
        }
    }

    let (mut rx, child) = cmd
        .spawn()
        .map_err(|e| format!("failed to spawn backend: {}", e))?;

    {
        let mut guard = state.child.lock().unwrap();
        *guard = Some(child);
    }

    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    let s = String::from_utf8_lossy(&line);
                    eprintln!("[dzmm-backend] {}", s.trim_end());
                }
                CommandEvent::Stderr(line) => {
                    let s = String::from_utf8_lossy(&line);
                    eprintln!("[dzmm-backend ERR] {}", s.trim_end());
                }
                _ => {}
            }
        }
    });

    Ok(())
}

#[tauri::command]
fn get_lan_url() -> Result<String, String> {
    use local_ip_address::local_ip;
    let ip = local_ip().map_err(|e| format!("could not determine LAN IP: {}", e))?;
    Ok(format!("http://{}:8765", ip))
}

#[tauri::command]
fn stop_backend(state: tauri::State<'_, BackendState>) -> Result<(), String> {
    let mut guard = state.child.lock().unwrap();
    if let Some(child) = guard.take() {
        let _ = child.kill();
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendState::default())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            // The sidecar is no longer auto-spawned here; the frontend's
            // BootGate calls invoke('start_backend', { lanMode }) once the
            // user picks a mode.
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            start_backend,
            stop_backend,
            get_lan_url
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Best-effort: kill the backend when the main window goes away.
                let state: tauri::State<'_, BackendState> = window.state();
                let mut guard = state.child.lock().unwrap();
                if let Some(child) = guard.take() {
                    let _ = child.kill();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
