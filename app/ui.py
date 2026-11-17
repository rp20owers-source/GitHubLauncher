from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.request
from pathlib import Path

from app.core import (
    GitHubClient,
    InstallHistory,
    download_file,
    find_executable,
    get_github_token,
    matching_checksum_asset,
    parse_github_url,
    safe_urlopen,
    safe_extract_zip,
    verify_sha256,
)

BG_OUTER = "#11111b"
BG_INPUT = "#1e1e2e"
TEXT_MAIN = "#cdd6f4"
TEXT_MUTED = "#6c7086"
BORDER_IDLE = "#313244"
BORDER_FOCUS = "#89b4fa"
COLOR_WARN = "#f9e2af"
COLOR_INFO = "#89dceb"
COLOR_OK = "#a6e3a1"
COLOR_ERR = "#f38ba8"


def enable_win_polish(root: tk.Tk) -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()
    try:
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        preference = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(preference), ctypes.sizeof(preference)
        )
    except (AttributeError, OSError):
        pass


def _app_data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GitHubLauncher"


class GitHubLauncherWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.w, self.h = 600, 68
        self.root.title("GitHubLauncher")
        self.root.resizable(False, False)
        self.root.configure(bg=BG_OUTER)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{self.w}x{self.h}+{(sw - self.w) // 2}+{sh // 3}")
        self.root.update_idletasks()
        icon_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        icon_path = icon_root / "assets" / "githublauncher.ico"
        if sys.platform == "win32" and icon_path.exists():
            self.root.iconbitmap(str(icon_path))
        enable_win_polish(self.root)

        self.is_busy = False
        self.cancel_event = threading.Event()
        self.last_autofilled_clip = ""
        self.history = InstallHistory(_app_data_dir() / "history.json")
        self.history_items: list[str] = []
        self.history_index: int | None = None
        self.setting_history = False

        self.canvas = tk.Canvas(
            root, width=self.w, height=self.h, bg=BG_OUTER, highlightthickness=0, bd=0
        )
        self.canvas.pack(fill="both", expand=True)
        self.box_id = self._draw_rounded_rect(
            8,
            8,
            self.w - 8,
            self.h - 8,
            r=14,
            fill=BG_INPUT,
            outline=BORDER_FOCUS,
            width=2,
        )
        self._draw_icon(30, self.h // 2, BORDER_FOCUS)
        self.prog_id = self.canvas.create_line(
            20, self.h - 9, 20, self.h - 9, fill=COLOR_INFO, width=3, state="hidden"
        )
        self.url_var = tk.StringVar()
        self.url_var.trace_add("write", self._on_text_change)
        self.entry = tk.Entry(
            root,
            textvariable=self.url_var,
            font=("Segoe UI", 13),
            bg=BG_INPUT,
            fg=TEXT_MAIN,
            disabledbackground=BG_INPUT,
            disabledforeground=TEXT_MUTED,
            insertbackground=BORDER_FOCUS,
            insertwidth=2,
            selectbackground="#45475a",
            selectforeground=TEXT_MAIN,
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        self.entry.place(x=54, y=18, width=self.w - 76, height=32)
        self.default_prompt = (
            "Paste GitHub URL & press Enter to install (Shift+Enter: save only)"
        )
        self.placeholder = tk.Label(
            root,
            text=self.default_prompt,
            font=("Segoe UI", 12),
            bg=BG_INPUT,
            fg=TEXT_MUTED,
            anchor="w",
            cursor="xterm",
        )
        self.placeholder.place(x=54, y=18, width=self.w - 76, height=32)
        self.placeholder.bind("<Button-1>", lambda _event: self.entry.focus_set())
        self.placeholder.bind("<Button-3>", self._paste_clipboard)
        self.entry.bind("<Button-3>", self._paste_clipboard)
        self.entry.bind(
            "<Return>", lambda _event: self.start_download(auto_install=True)
        )
        self.entry.bind(
            "<Shift-Return>", lambda _event: self.start_download(auto_install=False)
        )
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", lambda _event: self._set_accent(BORDER_IDLE))
        self.entry.bind("<Up>", self._history_up)
        self.entry.bind("<Down>", self._history_down)
        self.root.bind("<Escape>", self._on_escape)
        self.entry.focus_set()

        if len(sys.argv) > 1 and parse_github_url(sys.argv[1])[0]:
            self.url_var.set(sys.argv[1].strip())
            self.root.after(150, lambda: self.start_download(auto_install=True))
        else:
            self.root.after(100, self._check_clipboard_autofill)

    def _draw_rounded_rect(self, x1, y1, x2, y2, r=14, **kwargs):
        points = [
            x1 + r,
            y1,
            x2 - r,
            y1,
            x2,
            y1,
            x2,
            y1 + r,
            x2,
            y2 - r,
            x2,
            y2,
            x2 - r,
            y2,
            x1 + r,
            y2,
            x1,
            y2,
            x1,
            y2 - r,
            x1,
            y1 + r,
            x1,
            y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, **kwargs)

    def _draw_icon(self, cx, cy, color):
        self.canvas.delete("icon")
        self.canvas.create_line(
            cx, cy - 8, cx, cy + 4, fill=color, width=2, capstyle="round", tags="icon"
        )
        self.canvas.create_line(
            cx - 5,
            cy - 1,
            cx,
            cy + 4,
            cx + 5,
            cy - 1,
            fill=color,
            width=2,
            capstyle="round",
            joinstyle="round",
            tags="icon",
        )
        self.canvas.create_line(
            cx - 7,
            cy + 8,
            cx + 7,
            cy + 8,
            fill=color,
            width=2,
            capstyle="round",
            tags="icon",
        )

    def _on_escape(self, _event=None):
        if self.is_busy:
            self.cancel_event.set()
        else:
            self.root.destroy()

    def _on_focus_in(self, _event=None):
        self._set_accent(BORDER_FOCUS)
        self._check_clipboard_autofill()

    def _check_clipboard_autofill(self):
        if self.is_busy or self.url_var.get().strip():
            return
        try:
            clip = self.root.clipboard_get().strip()
            if clip != self.last_autofilled_clip and parse_github_url(clip)[0]:
                self.last_autofilled_clip = clip
                self.url_var.set(clip)
                self.entry.select_range(0, "end")
                self.entry.icursor("end")
        except tk.TclError:
            pass

    def _paste_clipboard(self, _event=None):
        if self.is_busy:
            return
        try:
            clip = self.root.clipboard_get().strip()
            if clip:
                self.url_var.set(clip)
                self.entry.focus_set()
                self.entry.icursor("end")
        except tk.TclError:
            pass

    def _on_text_change(self, *_args):
        if not self.setting_history:
            self.history_index = None
        if self.url_var.get():
            self.placeholder.place_forget()
        elif not self.is_busy:
            self.placeholder.config(text=self.default_prompt, fg=TEXT_MUTED)
            self.placeholder.place(x=54, y=18, width=self.w - 76, height=32)

    def _history_up(self, _event=None):
        if self.is_busy:
            return "break"
        try:
            self.history_items = self.history.load()
        except (OSError, ValueError):
            self.set_ui_state("Could not read GitHubLauncher history", COLOR_ERR)
            return "break"
        if self.history_items:
            self.history_index = min(
                (self.history_index if self.history_index is not None else -1) + 1,
                len(self.history_items) - 1,
            )
            self._set_history_value(self.history_items[self.history_index])
        return "break"

    def _history_down(self, _event=None):
        if self.is_busy:
            return "break"
        if self.history_index is not None:
            self.history_index -= 1
            if self.history_index < 0:
                self.history_index = None
                self._set_history_value("")
            else:
                self._set_history_value(self.history_items[self.history_index])
        return "break"

    def _set_history_value(self, value: str):
        self.setting_history = True
        try:
            self.url_var.set(value)
        finally:
            self.setting_history = False

    def _set_accent(self, color: str):
        if self.is_busy and color in (BORDER_IDLE, BORDER_FOCUS):
            return
        self.canvas.itemconfig(self.box_id, outline=color)
        self._draw_icon(30, self.h // 2, color)

    def set_ui_state(self, message: str, color: str, progress: float | None = None):
        def update():
            self._set_accent(color)
            self.placeholder.config(text=message, fg=color)
            if not self.url_var.get():
                self.placeholder.place(x=54, y=18, width=self.w - 76, height=32)
            if progress is not None and 0.0 < progress <= 1.0:
                start, width = 22, self.w - 44
                self.canvas.coords(
                    self.prog_id,
                    start,
                    self.h - 9,
                    start + int(width * progress),
                    self.h - 9,
                )
                self.canvas.itemconfig(self.prog_id, fill=color, state="normal")
            else:
                self.canvas.itemconfig(self.prog_id, state="hidden")

        self.root.after(0, update)

    def start_download(self, auto_install: bool = True):
        if self.is_busy:
            return
        url = self.url_var.get().strip()
        if not url:
            return
        owner, repo, tag = parse_github_url(url)
        if not owner or not repo:
            self.url_var.set("")
            self.set_ui_state(
                "Invalid GitHub URL — use https://github.com/owner/repo", COLOR_ERR
            )
            return
        self.is_busy = True
        self.cancel_event.clear()
        self.url_var.set("")
        self.entry.config(state="disabled")
        threading.Thread(
            target=self.download_worker,
            args=(owner, repo, tag, auto_install),
            daemon=True,
        ).start()

    def download_worker(
        self, owner: str, repo: str, tag: str | None, auto_install: bool
    ):
        client = None
        try:
            client = GitHubClient(token=get_github_token())
            self.set_ui_state(f"Searching releases for {owner}/{repo}...", COLOR_WARN)
            download_url, filename, assets = client.download_choice(owner, repo, tag)
            downloads_dir = Path.home() / "Downloads"
            downloads_dir.mkdir(parents=True, exist_ok=True)
            dest_path = downloads_dir / Path(filename).name
            start_time = time.perf_counter()

            def progress(downloaded: int, total: int):
                elapsed = max(time.perf_counter() - start_time, 0.001)
                speed = downloaded / (1024 * 1024) / elapsed
                if total:
                    ratio = downloaded / total
                    message = f"Downloading {filename}  •  {int(ratio * 100)}% ({speed:.1f} MB/s)"
                    self.set_ui_state(message, COLOR_INFO, progress=min(ratio, 1.0))
                else:
                    message = f"Downloading {filename}  •  {downloaded / (1024 * 1024):.1f} MB ({speed:.1f} MB/s)"
                    self.set_ui_state(message, COLOR_INFO, progress=0.5)

            download_file(
                download_url,
                dest_path,
                headers=client.download_headers(download_url),
                progress=progress,
                cancel_event=self.cancel_event,
            )
            checksum_asset = matching_checksum_asset(assets, filename)
            if checksum_asset:
                self.set_ui_state(f"Verifying {filename}...", COLOR_WARN)
                checksum_url = checksum_asset.get(
                    "url", checksum_asset["browser_download_url"]
                )
                request = urllib.request.Request(
                    checksum_url,
                    headers=client.download_headers(checksum_url),
                )
                with safe_urlopen(request, timeout=30) as response:
                    checksum_text = response.read(1024 * 1024).decode("utf-8")
                try:
                    valid = verify_sha256(dest_path, checksum_text, filename)
                except ValueError:
                    if checksum_asset["name"].lower().endswith(".sha256"):
                        raise
                    valid = None
                if valid is False:
                    raise ValueError(f"SHA-256 verification failed for {filename}")
            if auto_install:
                self._run_or_extract(dest_path, repo)
            else:
                self._reveal_in_explorer(dest_path)
                self._finish(f"✓ Saved {filename} to Downloads", COLOR_OK)
        except InterruptedError:
            self._finish("Download canceled", COLOR_WARN)
        except Exception as error:
            warning = client.rate_limit_warning if client else None
            if getattr(error, "code", None) == 404:
                message = (
                    "GitHub returned 404. The repository or release may be private; "
                    "sign in with GitHub CLI or configure GITHUB_TOKEN."
                )
            else:
                message = f"Download failed: {error}"
            if warning:
                message = f"{warning} ({message})"
            self._finish(message, COLOR_ERR)

    def _run_or_extract(self, file_path: Path, repo: str):
        extension = file_path.suffix.lower()
        try:
            if extension in (".exe", ".msi"):
                self.set_ui_state(f"Launching {file_path.name}...", COLOR_OK)
                if sys.platform == "win32":
                    os.startfile(str(file_path))
                elif extension == ".exe":
                    subprocess.Popen([str(file_path)])
                else:
                    raise OSError(
                        "Windows Installer packages can only be launched on Windows"
                    )
                self._record_install(repo)
                self._finish(f"✓ Launched installer: {file_path.name}", COLOR_OK)
            elif extension == ".zip":
                install_parent = (
                    Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs"
                )
                install_dir = install_parent / repo
                self.set_ui_state(
                    f"Extracting {file_path.name}...", COLOR_WARN, progress=0.85
                )
                install_parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="GitHubLauncher-") as temporary:
                    workspace = Path(temporary)
                    extracted = safe_extract_zip(file_path, workspace / "extract")
                    target_exe = find_executable(extracted, repo)
                    staged_install = workspace / "staged-install"
                    if extracted != workspace / "extract":
                        shutil.move(str(extracted), staged_install)
                    else:
                        staged_install.mkdir()
                        for item in (workspace / "extract").iterdir():
                            if item != staged_install:
                                shutil.move(str(item), staged_install / item.name)
                    backup = install_parent / f".{repo}.backup"
                    if backup.exists():
                        shutil.rmtree(backup)
                    if install_dir.exists():
                        install_dir.replace(backup)
                    try:
                        staged_install.replace(install_dir)
                    except Exception:
                        if backup.exists():
                            backup.replace(install_dir)
                        raise
                    if backup.exists():
                        shutil.rmtree(backup)
                    if target_exe:
                        target_exe = install_dir / target_exe.relative_to(extracted)
                self._record_install(repo)
                if target_exe:
                    if sys.platform == "win32":
                        os.startfile(str(target_exe))
                    self._finish(f"✓ Installed & launched {target_exe.name}", COLOR_OK)
                else:
                    self._reveal_in_explorer(install_dir)
                    self._finish(f"✓ Extracted to {install_dir.name}", COLOR_OK)
            else:
                self._reveal_in_explorer(file_path)
                self._finish(f"✓ Saved {file_path.name}", COLOR_OK)
        except Exception as error:
            self._reveal_in_explorer(file_path)
            self._finish(f"Saved (auto-launch skipped: {error})", COLOR_WARN)

    def _record_install(self, repo: str):
        try:
            self.history.add(repo)
        except (OSError, ValueError) as error:
            self.set_ui_state(
                f"Installed, but history could not be saved: {error}", COLOR_WARN
            )

    @staticmethod
    def _reveal_in_explorer(path: Path):
        if sys.platform == "win32":
            if path.is_dir():
                os.startfile(str(path))
            else:
                subprocess.Popen(["explorer.exe", f"/select,{path}"])

    def _finish(self, message: str, color: str):
        def restore():
            self.is_busy = False
            self.entry.config(state="normal")
            self.entry.focus_set()
            self.set_ui_state(message, color, progress=None)

        self.root.after(0, restore)
