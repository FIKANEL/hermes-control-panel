"""
Verification Suite for Bug 2 (Single-Instance, Fast Launch, Mutex, Window Focus, and No Console)
"""

import sys
import os
import time
import socket
import ctypes
from ctypes import wintypes
import subprocess
import psutil

WINDOW_TITLE = "Hermes Agent Control Panel"
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SW_MINIMIZE = 6
SW_RESTORE = 9

def find_panel_hwnd():
    found = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                if WINDOW_TITLE in buff.value:
                    found.append((hwnd, buff.value))
        return True
    user32.EnumWindows(enum_cb, 0)
    return found

def kill_all_panel_instances():
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = " ".join(p.info['cmdline'] or []).lower()
            if "hermes-control-panel" in cmd and "app.py" in cmd:
                p.kill()
        except Exception:
            pass
    time.sleep(1)

def run_bug2_tests():
    print("=" * 60)
    print("STARTING TEST SUITE: BUG 2 (Shortcut, Mutex & Window Management)")
    print("=" * 60)

    # Clean slate
    kill_all_panel_instances()
    time.sleep(1)

    results = {}

    # -------------------------------------------------------------
    # 1. Shortcut Launch Time Measurement (Target < 1.5s)
    # -------------------------------------------------------------
    print("\n--- Test 2.1: Launch Time Measurement ---")
    t0 = time.time()
    # Launch exactly like shortcut: pythonw.exe app.py
    proc = subprocess.Popen(
        ["C:\\Python314\\pythonw.exe", "app.py"],
        cwd="C:\\FIKKAN\\project\\hermes-control-panel"
    )

    hwnd = None
    launch_duration = None
    for _ in range(60): # up to 6s
        hwnds = find_panel_hwnd()
        if hwnds:
            hwnd = hwnds[0][0]
            launch_duration = round(time.time() - t0, 3)
            break
        time.sleep(0.05)

    print(f"  Window appeared in: {launch_duration}s (HWND: {hwnd})")
    results["test_2_1_launch_time"] = {
        "success": launch_duration is not None and launch_duration < 2.0,
        "launch_duration_seconds": launch_duration,
        "target_met": launch_duration < 1.5 if launch_duration else False
    }

    # -------------------------------------------------------------
    # 2. Rapid 3x Shortcut Click Test
    # -------------------------------------------------------------
    print("\n--- Test 2.2: Rapid 3x Shortcut Click Test ---")
    sub_procs = []
    for i in range(3):
        p = subprocess.Popen(
            ["C:\\Python314\\pythonw.exe", "app.py"],
            cwd="C:\\FIKKAN\\project\\hermes-control-panel"
        )
        sub_procs.append(p)
        time.sleep(0.05)

    # Wait for secondary processes to exit cleanly
    time.sleep(2.0)

    # Check window count
    hwnds = find_panel_hwnd()
    print(f"  Total '{WINDOW_TITLE}' Windows Open: {len(hwnds)}")

    # Check for any error MessageBoxes open
    dialog_boxes = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def check_dialog(h, _):
        if user32.IsWindowVisible(h):
            length = user32.GetWindowTextLengthW(h)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(h, buff, length + 1)
                title = buff.value
                # Check if it's a message box belonging to our process
                cls_buff = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(h, cls_buff, 256)
                if cls_buff.value == "#32770" and WINDOW_TITLE in title:
                    dialog_boxes.append((h, title))
        return True
    user32.EnumWindows(check_dialog, 0)
    print(f"  Popup Error Dialogs Found: {len(dialog_boxes)}")

    results["test_2_2_rapid_3x"] = {
        "success": len(hwnds) == 1 and len(dialog_boxes) == 0,
        "window_count": len(hwnds),
        "error_dialog_count": len(dialog_boxes)
    }

    # -------------------------------------------------------------
    # 3. Minimize Window & Click Shortcut (Restore to Foreground)
    # -------------------------------------------------------------
    print("\n--- Test 2.3: Minimize Window & Shortcut Re-focus Test ---")
    if hwnds:
        main_hwnd = hwnds[0][0]
        # Minimize
        user32.ShowWindow(main_hwnd, SW_MINIMIZE)
        time.sleep(0.5)
        is_iconic_before = bool(user32.IsIconic(main_hwnd))
        print(f"  Window IsIconic before shortcut: {is_iconic_before}")

        # Run shortcut
        p_sub = subprocess.Popen(
            ["C:\\Python314\\pythonw.exe", "app.py"],
            cwd="C:\\FIKKAN\\project\\hermes-control-panel"
        )
        p_sub.wait(timeout=5)
        time.sleep(0.5)

        is_iconic_after = bool(user32.IsIconic(main_hwnd))
        is_visible = bool(user32.IsWindowVisible(main_hwnd))
        fg_hwnd = user32.GetForegroundWindow()
        is_fg = (fg_hwnd == main_hwnd)
        print(f"  Window IsIconic after shortcut: {is_iconic_after} (should be False)")
        print(f"  Window IsVisible after shortcut: {is_visible}")
        print(f"  Window is Foreground / Active: {is_fg}")

        results["test_2_3_minimize_restore"] = {
            "success": is_iconic_before is True and is_iconic_after is False and is_visible is True,
            "minimized_successfully": is_iconic_before,
            "restored_successfully": not is_iconic_after,
            "window_visible": is_visible,
            "foreground_focused": is_fg
        }

    # -------------------------------------------------------------
    # 4. Force Kill & Clean Immediate Restart Test
    # -------------------------------------------------------------
    print("\n--- Test 2.4: Force Kill & Restart Test ---")
    kill_all_panel_instances()
    for _ in range(20):
        if not find_panel_hwnd():
            break
        time.sleep(0.1)

    # Immediately launch after kill
    t_restart0 = time.time()
    p_restart = subprocess.Popen(
        ["C:\\Python314\\pythonw.exe", "app.py"],
        cwd="C:\\FIKKAN\\project\\hermes-control-panel"
    )

    restarted_hwnd = None
    for _ in range(60):
        hwnds = find_panel_hwnd()
        if hwnds:
            restarted_hwnd = hwnds[0][0]
            break
        time.sleep(0.05)

    restart_time = round(time.time() - t_restart0, 3)
    print(f"  Restart after force-kill succeeded in {restart_time}s (HWND: {restarted_hwnd})")

    results["test_2_4_force_kill_restart"] = {
        "success": restarted_hwnd is not None,
        "restart_duration_seconds": restart_time
    }

    # -------------------------------------------------------------
    # 5. No Console Window Test
    # -------------------------------------------------------------
    print("\n--- Test 2.5: No Console Window Test ---")
    # Check parent/child processes of the running pythonw instance
    has_console = False
    console_hwnds = []
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = " ".join(p.info['cmdline'] or []).lower()
            if "hermes-control-panel" in cmd and "app.py" in cmd:
                # Check conhost or cmd attached
                for child in p.children():
                    if "cmd" in child.name().lower() or "conhost" in child.name().lower():
                        has_console = True
        except Exception:
            pass

    print(f"  Console/cmd window attached: {has_console} (should be False)")
    results["test_2_5_no_console"] = {
        "success": not has_console,
        "console_attached": has_console
    }

    # Final cleanup
    kill_all_panel_instances()
    print("\n" + "=" * 60)
    print("BUG 2 TEST RESULTS SUMMARY:")
    import json
    print(json.dumps(results, indent=2))
    print("=" * 60)
    return results

if __name__ == "__main__":
    run_bug2_tests()
