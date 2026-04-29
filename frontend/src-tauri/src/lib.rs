use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::Manager;

#[derive(Default)]
struct BackendState {
    child: Mutex<Option<Child>>,
}

fn spawn_backend(
    app: &tauri::AppHandle,
    lan_mode: bool,
) -> Result<Child, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("resource_dir: {}", e))?;
    let backend_dir = resource_dir.join("backend-runtime");

    let bin_name = if cfg!(windows) { "dzmm-backend.exe" } else { "dzmm-backend" };
    let exe = backend_dir.join(bin_name);

    if !exe.exists() {
        return Err(format!("backend binary missing at {}", exe.display()));
    }

    let mut cmd = Command::new(&exe);
    cmd.current_dir(&backend_dir);
    cmd.env(
        "DZMM_HOST",
        if lan_mode { "0.0.0.0" } else { "127.0.0.1" },
    );
    cmd.env("DZMM_PORT", "8765");

    if lan_mode {
        let dist = resource_dir.join("frontend-dist");
        if dist.exists() {
            cmd.env("DZMM_FRONTEND_DIST", dist.to_string_lossy().to_string());
        }
    }

    // Don't pop a console window on Windows.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }

    cmd.stdout(Stdio::null()).stderr(Stdio::null()).stdin(Stdio::null());

    cmd.spawn().map_err(|e| format!("spawn failed: {}", e))
}

fn kill_existing(state: &tauri::State<'_, BackendState>) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

#[tauri::command]
async fn start_backend(
    app: tauri::AppHandle,
    state: tauri::State<'_, BackendState>,
    lan_mode: bool,
) -> Result<(), String> {
    kill_existing(&state);
    let child = spawn_backend(&app, lan_mode)?;
    *state.child.lock().unwrap() = Some(child);
    Ok(())
}

#[tauri::command]
fn stop_backend(state: tauri::State<'_, BackendState>) -> Result<(), String> {
    kill_existing(&state);
    Ok(())
}

#[tauri::command]
fn get_lan_url() -> Result<String, String> {
    use local_ip_address::local_ip;
    let ip = local_ip().map_err(|e| format!("could not determine LAN IP: {}", e))?;
    Ok(format!("http://{}:8765", ip))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(BackendState::default())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            start_backend,
            stop_backend,
            get_lan_url
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state: tauri::State<'_, BackendState> = window.state();
                kill_existing(&state);
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
