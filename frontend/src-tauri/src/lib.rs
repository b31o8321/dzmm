use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;

use serde::Serialize;
use tauri::{Emitter, Manager};

#[derive(Clone, Copy, Default, Serialize)]
#[serde(rename_all = "snake_case")]
enum BackendMode {
    #[default]
    Stopped,
    Local,
    Remote,
    Error,
}

#[derive(Default)]
struct BackendProcess {
    child: Option<Child>,
    mode: BackendMode,
    error: Option<String>,
}

#[derive(Default)]
struct BackendState {
    process: Mutex<BackendProcess>,
}

#[derive(Serialize)]
struct BackendStatus {
    mode: BackendMode,
    pid: Option<u32>,
    lan_addresses: Vec<String>,
    error: Option<String>,
}

#[derive(Serialize, Clone)]
struct BackendLogEntry {
    stream: String, // "stdout" | "stderr" | "system"
    line: String,
    ts_ms: u64,
}

fn now_ms() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn pump<R: std::io::Read + Send + 'static>(app: tauri::AppHandle, reader: R, stream: &'static str) {
    thread::spawn(move || {
        let buf = BufReader::new(reader);
        for line in buf.lines() {
            match line {
                Ok(line) => {
                    let _ = app.emit(
                        "backend-log",
                        BackendLogEntry {
                            stream: stream.into(),
                            line,
                            ts_ms: now_ms(),
                        },
                    );
                }
                Err(e) => {
                    let _ = app.emit(
                        "backend-log",
                        BackendLogEntry {
                            stream: "system".into(),
                            line: format!("[{} read error] {}", stream, e),
                            ts_ms: now_ms(),
                        },
                    );
                    break;
                }
            }
        }
    });
}

fn spawn_backend(app: &tauri::AppHandle, lan_mode: bool) -> Result<Child, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("resource_dir: {}", e))?;
    let backend_dir = resource_dir.join("backend-runtime");

    let bin_name = if cfg!(windows) {
        "dzmm-backend.exe"
    } else {
        "dzmm-backend"
    };
    let exe = backend_dir.join(bin_name);

    if !exe.exists() {
        return Err(format!("backend binary missing at {}", exe.display()));
    }

    let mut cmd = Command::new(&exe);
    cmd.current_dir(&backend_dir);
    cmd.env("DZMM_HOST", if lan_mode { "0.0.0.0" } else { "127.0.0.1" });
    cmd.env("DZMM_PORT", "8765");
    cmd.env("DZMM_REMOTE_ACCESS", if lan_mode { "1" } else { "0" });

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

    cmd.stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .stdin(Stdio::null());

    let mut child = cmd.spawn().map_err(|e| format!("spawn failed: {}", e))?;

    let _ = app.emit(
        "backend-log",
        BackendLogEntry {
            stream: "system".into(),
            line: format!("spawned: {}", exe.display()),
            ts_ms: now_ms(),
        },
    );

    if let Some(stdout) = child.stdout.take() {
        pump(app.clone(), stdout, "stdout");
    }
    if let Some(stderr) = child.stderr.take() {
        pump(app.clone(), stderr, "stderr");
    }

    Ok(child)
}

fn kill_existing(process: &mut BackendProcess) {
    if let Some(mut child) = process.child.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn lan_addresses() -> Vec<String> {
    let Ok(interfaces) = local_ip_address::list_afinet_netifas() else {
        return Vec::new();
    };
    let mut addresses = interfaces
        .into_iter()
        .filter_map(|(_, address)| match address {
            std::net::IpAddr::V4(ip) if ip.is_private() && !ip.is_loopback() => {
                Some(format!("http://{}:8765", ip))
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    addresses.sort();
    addresses.dedup();
    addresses
}

fn restart_backend_inner(
    app: &tauri::AppHandle,
    state: &tauri::State<'_, BackendState>,
    remote_access: bool,
) -> Result<(), String> {
    let mut process = state
        .process
        .lock()
        .map_err(|_| "backend state lock poisoned".to_string())?;
    kill_existing(&mut process);
    process.error = None;
    match spawn_backend(app, remote_access) {
        Ok(child) => {
            process.child = Some(child);
            process.mode = if remote_access {
                BackendMode::Remote
            } else {
                BackendMode::Local
            };
            Ok(())
        }
        Err(error) => {
            process.mode = BackendMode::Error;
            process.error = Some(error.clone());
            Err(error)
        }
    }
}

#[tauri::command]
async fn start_backend(
    app: tauri::AppHandle,
    state: tauri::State<'_, BackendState>,
    lan_mode: bool,
) -> Result<(), String> {
    restart_backend_inner(&app, &state, lan_mode)
}

#[tauri::command]
async fn restart_backend(
    app: tauri::AppHandle,
    state: tauri::State<'_, BackendState>,
    remote_access: bool,
) -> Result<(), String> {
    restart_backend_inner(&app, &state, remote_access)
}

#[tauri::command]
fn stop_backend(state: tauri::State<'_, BackendState>) -> Result<(), String> {
    let mut process = state
        .process
        .lock()
        .map_err(|_| "backend state lock poisoned".to_string())?;
    kill_existing(&mut process);
    process.mode = BackendMode::Stopped;
    process.error = None;
    Ok(())
}

#[tauri::command]
fn get_backend_status(state: tauri::State<'_, BackendState>) -> Result<BackendStatus, String> {
    let mut process = state
        .process
        .lock()
        .map_err(|_| "backend state lock poisoned".to_string())?;
    if let Some(child) = process.child.as_mut() {
        if let Some(exit) = child
            .try_wait()
            .map_err(|error| format!("backend status failed: {}", error))?
        {
            process.child = None;
            process.mode = BackendMode::Error;
            process.error = Some(format!("backend exited unexpectedly: {}", exit));
        }
    }
    Ok(BackendStatus {
        mode: process.mode,
        pid: process.child.as_ref().map(Child::id),
        lan_addresses: lan_addresses(),
        error: process.error.clone(),
    })
}

#[tauri::command]
fn get_lan_url() -> Result<String, String> {
    lan_addresses()
        .into_iter()
        .next()
        .ok_or_else(|| "could not determine LAN IP".to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
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
            restart_backend,
            stop_backend,
            get_backend_status,
            get_lan_url
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state: tauri::State<'_, BackendState> = window.state();
                if let Ok(mut process) = state.process.lock() {
                    kill_existing(&mut process);
                    process.mode = BackendMode::Stopped;
                };
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
