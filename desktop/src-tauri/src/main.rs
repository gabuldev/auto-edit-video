// Auto-Edit desktop — Tauri v2 shell.
// The heavy lifting lives in the Python engine (`auto-edit serve`); this window
// just loads the web UI in ../ui, which talks to the local API over HTTP + SSE.
//
// On launch the shell starts the engine itself unless one is already listening
// on ENGINE_ADDR (e.g. you ran `auto-edit serve` by hand — that one is reused
// and left alone). The engine we started is killed when the app exits.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, File};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{Manager, RunEvent};

const ENGINE_ADDR: &str = "127.0.0.1:8760";

/// The engine process this app spawned (None if we reused an existing one).
struct Engine(Mutex<Option<Child>>);

fn engine_listening() -> bool {
    let addr: SocketAddr = ENGINE_ADDR.parse().unwrap();
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

fn home() -> Option<PathBuf> {
    std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" }).map(PathBuf::from)
}

/// Repo checkout this binary was built from (desktop/src-tauri/../..). Only
/// meaningful for dev builds running from the source tree.
fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

/// Find the `auto-edit` executable. A GUI app launched from Finder/Dock does
/// not inherit the shell's PATH, so look in the usual install spots before
/// asking the user's login shell.
fn find_auto_edit() -> Option<PathBuf> {
    if let Some(p) = std::env::var_os("AUTO_EDIT_BIN") {
        return Some(PathBuf::from(p));
    }

    let exe = if cfg!(windows) { "auto-edit.exe" } else { "auto-edit" };
    let venv_bin = if cfg!(windows) { "Scripts" } else { "bin" };
    let mut candidates = vec![repo_root().join(".venv").join(venv_bin).join(exe)];
    if let Some(h) = home() {
        candidates.push(h.join(".local/bin").join(exe)); // uv tool / pipx
        candidates.push(h.join(".nix-profile/bin").join(exe));
    }
    candidates.push(PathBuf::from("/opt/homebrew/bin").join(exe));
    candidates.push(PathBuf::from("/usr/local/bin").join(exe));
    if let Some(p) = candidates.into_iter().find(|p| p.is_file()) {
        return Some(p);
    }

    lookup_in_shell()
}

#[cfg(unix)]
fn lookup_in_shell() -> Option<PathBuf> {
    let shell = std::env::var("SHELL").unwrap_or_else(|_| "/bin/zsh".into());
    let out = Command::new(shell).args(["-lc", "command -v auto-edit"]).output().ok()?;
    let line = String::from_utf8_lossy(&out.stdout).lines().last()?.trim().to_string();
    let p = PathBuf::from(line);
    p.is_file().then_some(p)
}

#[cfg(windows)]
fn lookup_in_shell() -> Option<PathBuf> {
    let out = Command::new("where").arg("auto-edit").output().ok()?;
    let line = String::from_utf8_lossy(&out.stdout).lines().next()?.trim().to_string();
    let p = PathBuf::from(line);
    p.is_file().then_some(p)
}

/// Where the engine runs. `serve` keeps its library in `<cwd>/workspace`
/// (unless AUTO_EDIT_WORKSPACE says otherwise): the repo in dev, so you see the
/// same workspaces as the CLI; ~/.auto-edit in a packaged app.
fn engine_cwd() -> PathBuf {
    if let Some(p) = std::env::var_os("AUTO_EDIT_CWD") {
        return PathBuf::from(p);
    }
    if cfg!(debug_assertions) {
        return repo_root();
    }
    let dir = std::env::var_os("AUTO_EDIT_HOME")
        .map(PathBuf::from)
        .or_else(|| home().map(|h| h.join(".auto-edit")))
        .unwrap_or_else(std::env::temp_dir);
    let _ = fs::create_dir_all(&dir);
    dir
}

/// The engine shipped inside the app (scripts/stage_engine.py → resources
/// "engine"): a portable Python with auto-edit, the pipeline files and an
/// FFmpeg with libass. None in dev builds, which use the installed CLI.
struct Embedded {
    python: PathBuf,
    repo: PathBuf,
    bin: PathBuf,
}

fn embedded_engine(resource_dir: Option<PathBuf>) -> Option<Embedded> {
    let root = resource_dir?.join("engine");
    let python = if cfg!(windows) {
        root.join("python").join("python.exe")
    } else {
        root.join("python").join("bin").join("python3")
    };
    if !python.is_file() {
        return None;
    }
    Some(Embedded { python, repo: root.join("repo"), bin: root.join("bin") })
}

fn engine_command(embedded: Option<&Embedded>) -> Result<(Command, String), String> {
    if let Some(e) = embedded {
        let mut cmd = Command::new(&e.python);
        cmd.args(["-m", "auto_edit.cli", "serve"]);
        // ffmpeg/ffprobe from the bundle first, then whatever the user has
        // (bash, the agent CLIs).
        let path = std::env::var_os("PATH").unwrap_or_default();
        let mut dirs = vec![e.bin.clone()];
        dirs.extend(std::env::split_paths(&path));
        if let Some(h) = home() {
            dirs.push(h.join(".local/bin"));
        }
        dirs.push(PathBuf::from("/opt/homebrew/bin"));
        dirs.push(PathBuf::from("/usr/local/bin"));
        if let Ok(joined) = std::env::join_paths(dirs) {
            cmd.env("PATH", joined);
        }
        let ffmpeg = e.bin.join(if cfg!(windows) { "ffmpeg.exe" } else { "ffmpeg" });
        cmd.env("AUTO_EDIT_REPO_ROOT", &e.repo)
            .env("AUTO_EDIT_FFMPEG", ffmpeg)
            .env("PYTHON", &e.python)
            .env("PYTHONNOUSERSITE", "1")
            .env("PYTHONUTF8", "1");
        return Ok((cmd, format!("{} (embutido)", e.python.display())));
    }
    let bin = find_auto_edit().ok_or(
        "`auto-edit` não encontrado. Instale o CLI ou aponte AUTO_EDIT_BIN pro executável.",
    )?;
    let mut cmd = Command::new(&bin);
    cmd.arg("serve");
    Ok((cmd, bin.display().to_string()))
}

fn start_engine(log_dir: &Path, embedded: Option<&Embedded>) -> Result<Child, String> {
    let (mut cmd, what) = engine_command(embedded)?;

    let _ = fs::create_dir_all(log_dir);
    let log_path = log_dir.join("engine.log");
    let log = File::create(&log_path).map_err(|e| format!("{}: {e}", log_path.display()))?;
    let log_err = log.try_clone().map_err(|e| e.to_string())?;

    cmd.current_dir(engine_cwd())
        .stdin(Stdio::null())
        .stdout(log)
        .stderr(log_err);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let child = cmd.spawn().map_err(|e| format!("{what}: {e}"))?;
    eprintln!("[auto-edit] engine started: {what} serve (log: {})", log_path.display());
    Ok(child)
}

fn main() {
    let app = tauri::Builder::default()
        .manage(Engine(Mutex::new(None)))
        .setup(|app| {
            if engine_listening() {
                eprintln!("[auto-edit] engine already running on {ENGINE_ADDR}, reusing it");
                return Ok(());
            }
            let log_dir = app
                .path()
                .app_log_dir()
                .unwrap_or_else(|_| std::env::temp_dir().join("auto-edit"));
            let embedded = embedded_engine(app.path().resource_dir().ok());
            match start_engine(&log_dir, embedded.as_ref()) {
                Ok(child) => *app.state::<Engine>().0.lock().unwrap() = Some(child),
                // Not fatal: the UI shows the offline banner and keeps polling.
                Err(e) => eprintln!("[auto-edit] could not start engine: {e}"),
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running Auto-Edit");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(mut child) = handle.state::<Engine>().0.lock().unwrap().take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}
