"""
Hermes Agent Control Panel - Desktop Application
Native Windows desktop app (WebView2 via pywebview) & local server.
Features Windows Named Mutex, Single-Instance Restoration, and Fast Windowing.
"""

import sys
import os
import io
import time
import socket
import threading
import webbrowser
from pathlib import Path

# Safeguard standard streams when running under pythonw.exe (no console attached)
class NullWriter(io.TextIOBase):
    def write(self, s):
        return len(s) if s else 0
    def flush(self):
        pass

if sys.stdout is None:
    sys.stdout = NullWriter()
if sys.stderr is None:
    sys.stderr = NullWriter()

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from webui_server import run_server, MANAGER

PORT = 8640
MUTEX_NAME = "Local\\NousHermesAgentControlPanelMutex"
WINDOW_TITLE = "Hermes Agent Control Panel"

# Global references
_MUTEX_HANDLE = None

def acquire_single_instance_mutex():
    """
    Attempts to create and acquire the single-instance Windows named mutex.
    Returns (handle, is_already_running).
    Windows kernel automatically frees this mutex when the holding process terminates/crashes.
    """
    if os.name != 'nt':
        return None, False

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    CreateMutexW = kernel32.CreateMutexW
    CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    CreateMutexW.restype = wintypes.HANDLE

    ERROR_ALREADY_EXISTS = 183

    handle = CreateMutexW(None, True, MUTEX_NAME)
    last_err = kernel32.GetLastError()

    if last_err == ERROR_ALREADY_EXISTS:
        return handle, True
    return handle, False

def focus_existing_window() -> bool:
    """
    Finds the existing Hermes Agent Control Panel window, restores it if minimized,
    and brings it to the foreground. Returns True if window was successfully focused.
    """
    if os.name != 'nt':
        return False

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    SW_RESTORE = 9
    SW_SHOW = 5

    found_hwnd = None

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_cb(hwnd, lparam):
        nonlocal found_hwnd
        if user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                if WINDOW_TITLE in buff.value:
                    found_hwnd = hwnd
                    return False # Found it, stop enumeration
        return True

    user32.EnumWindows(enum_cb, 0)

    if found_hwnd:
        try:
            if user32.IsIconic(found_hwnd):
                user32.ShowWindow(found_hwnd, SW_RESTORE)
            else:
                user32.ShowWindow(found_hwnd, SW_SHOW)

            user32.BringWindowToTop(found_hwnd)
            user32.SetForegroundWindow(found_hwnd)
            if hasattr(user32, 'SwitchToThisWindow'):
                user32.SwitchToThisWindow(found_hwnd, True)
            return True
        except Exception:
            pass
    return False

def prompt_unresponsive_instance_cleanup() -> bool:
    """
    If mutex exists but no responsive window can be found, asks user if they want
    to force-close the hung process and restart.
    Verifies process identity (must be hermes-control-panel) before killing.
    """
    if os.name != 'nt':
        return False

    import ctypes
    user32 = ctypes.windll.user32

    # MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND
    res = user32.MessageBoxW(
        0,
        "Hermes Agent Control Panel terdeteksi sedang berjalan di latar belakang namun jendela tidak merespons.\n\nApakah Anda ingin menutup paksa proses lama dan membuka ulang?",
        WINDOW_TITLE,
        0x00000004 | 0x00000020 | 0x00010000
    )

    if res == 6: # IDYES
        import psutil
        cleaned = False
        current_pid = os.getpid()

        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr and conn.laddr.port == PORT:
                pid = conn.pid
                if pid and pid != current_pid:
                    try:
                        p = psutil.Process(pid)
                        cmdline = " ".join(p.cmdline()).lower()
                        # Verify that this process really belongs to hermes-control-panel
                        if "hermes-control-panel" in cmdline or "app.py" in cmdline:
                            p.kill()
                            cleaned = True
                    except Exception:
                        pass

        # Also scan processes holding app.py in our directory
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            if p.info['pid'] != current_pid:
                try:
                    cmdline = " ".join(p.info['cmdline'] or []).lower()
                    if "hermes-control-panel" in cmdline and "app.py" in cmdline:
                        p.kill()
                        cleaned = True
                except Exception:
                    pass

        time.sleep(0.8)
        return cleaned

    return False

def is_port_listening(port: int) -> bool:
    """Checks if a TCP port is in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(('127.0.0.1', port)) == 0

def start_server_thread():
    t = threading.Thread(target=run_server, args=(PORT,), daemon=True)
    t.start()
    # Wait for server to bind port
    for _ in range(20):
        if is_port_listening(PORT):
            break
        time.sleep(0.05)

def main():
    global _MUTEX_HANDLE

    # 1. Windows AppUserModelID for taskbar grouping
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("nous.hermes.controlpanel.1.0")
        except Exception:
            pass

    # 2. Single-Instance Check via Windows Named Mutex
    mutex_handle, is_already_running = acquire_single_instance_mutex()
    _MUTEX_HANDLE = mutex_handle

    if is_already_running:
        # Give the first instance window a brief moment if it's currently launching
        focused = False
        for _ in range(6):
            if focus_existing_window():
                focused = True
                break
            time.sleep(0.2)

        if focused:
            # First instance restored & brought to front; exit cleanly without alert
            sys.exit(0)

        # Mutex exists but no visible window found after retries
        cleaned = prompt_unresponsive_instance_cleanup()
        if not cleaned:
            sys.exit(0)

    # 3. Start local non-blocking HTTP server in background thread
    start_server_thread()

    url = f"http://127.0.0.1:{PORT}"

    use_web_only = "--web" in sys.argv
    if use_web_only:
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sys.exit(0)

    # 4. Launch Native Desktop Window (Fast Startup)
    try:
        import webview
        window = webview.create_window(
            title=WINDOW_TITLE,
            url=url,
            width=1080,
            height=760,
            min_size=(940, 640),
            background_color="#08090a",
            text_select=True
        )
        webview.start(debug=False)
    except Exception as e:
        MANAGER.add_log("desktop", "WARN", f"pywebview failed ({e}), opening in default browser...")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sys.exit(0)

if __name__ == "__main__":
    main()
