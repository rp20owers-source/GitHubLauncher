import ctypes
import sys
import tkinter as tk
from ctypes import wintypes

from app.ui import GitHubLauncherWindow

APP_TITLE = "GitHubLauncher"
MUTEX_NAME = "Local\\GitHubLauncher.SingleInstance"


def focus_existing_window() -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    user32.FindWindowW.restype = wintypes.HWND
    hwnd = user32.FindWindowW(None, APP_TITLE)
    if hwnd:
        user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)


def main() -> int:
    mutex = None
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            focus_existing_window()
            return 0

    try:
        root = tk.Tk()
        GitHubLauncherWindow(root)
        root.mainloop()
    finally:
        if mutex:
            kernel32.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
