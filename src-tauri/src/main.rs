// ATLAS native shell (Tauri 2). Thin host: runs the existing FastAPI core as a
// sidecar, waits for "ATLAS_READY <port>", then loads the current HUD in a webview.
// Single-instance, tray show/hide, autostart, and a clean sidecar shutdown on exit.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

#[derive(Default)]
struct SidecarState(Mutex<Option<CommandChild>>);

fn show_main(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
}

fn main() {
    tauri::Builder::default()
        // single-instance MUST be registered first
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            show_main(app);
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_positioner::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .manage(SidecarState::default())
        .setup(|app| {
            let handle = app.handle().clone();

            // Spawn the FastAPI core; it prints "ATLAS_READY <port>" once serving.
            let sidecar = app
                .shell()
                .sidecar("atlas-core")
                .expect("atlas-core sidecar missing")
                .args(["--port", "0"]);
            let (mut rx, child) = sidecar.spawn().expect("failed to start atlas-core");
            app.state::<SidecarState>().0.lock().unwrap().replace(child);

            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    if let CommandEvent::Stdout(line) = event {
                        let text = String::from_utf8_lossy(&line);
                        if let Some(rest) = text.trim().strip_prefix("ATLAS_READY ") {
                            if let Ok(port) = rest.trim().parse::<u16>() {
                                let url = format!("http://127.0.0.1:{port}");
                                if handle.get_webview_window("main").is_none() {
                                    let _ = WebviewWindowBuilder::new(
                                        &handle,
                                        "main",
                                        WebviewUrl::External(url.parse().unwrap()),
                                    )
                                    .title("ATLAS")
                                    .inner_size(1280.0, 860.0)
                                    .build();
                                }
                            }
                        }
                    }
                }
            });

            // Tray: click to show, right-click menu to quit.
            let quit = MenuItem::with_id(app, "quit", "Quit ATLAS", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&quit])?;
            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .icon_as_template(true)
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| {
                    if event.id.as_ref() == "quit" {
                        app.exit(0);
                    }
                })
                .on_tray_icon_event(|tray, _event| show_main(tray.app_handle()))
                .build(app)?;

            Ok(())
        })
        // Closing the window hides it (keeps ATLAS resident); Quit via tray exits.
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error building ATLAS")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } = event {
                // Kill the sidecar's process tree so uvicorn never orphans.
                if let Some(child) = app.state::<SidecarState>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
