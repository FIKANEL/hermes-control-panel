"""
Comprehensive Verification Suite for Hermes Agent Control Panel
Tests all requirements for Bug 1 and Bug 2.
"""

import sys
import os
import time
import socket
import json
import urllib.request
import threading
import subprocess
from pathlib import Path

BASE_DIR = Path("C:/FIKKAN/project/hermes-control-panel")
sys.path.insert(0, str(BASE_DIR))

from hermes_manager import HermesManager
from webui_server import run_server

def is_port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(('127.0.0.1', port)) == 0

def http_get(url: str) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode('utf-8'))

def http_post(url: str, data: dict = {}) -> dict:
    body = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))

def run_bug1_tests():
    print("=" * 60)
    print("STARTING TEST SUITE: BUG 1 (Start All Resilience)")
    print("=" * 60)

    # Start an embedded server on 8640 if not already running
    server_started = False
    if not is_port_listening(8640):
        t = threading.Thread(target=run_server, args=(8640,), daemon=True)
        t.start()
        time.sleep(1)
        server_started = True

    base_url = "http://127.0.0.1:8640"

    # Make sure stopped before starting
    http_post(f"{base_url}/api/services/stop_all")
    time.sleep(1)

    results = {}

    # -------------------------------------------------------------
    # 1. 5 Consecutive Start All -> Stop All cycles
    # -------------------------------------------------------------
    print("\n--- Test 1.1: 5 Consecutive Start All / Stop All Cycles ---")
    cycle_reports = []
    all_5_passed = True

    for cycle in range(1, 6):
        print(f"\n[Cycle {cycle}/5] Triggering Start All...")
        t0 = time.time()
        res = http_post(f"{base_url}/api/services/start_all")
        print(f"  Start All API Response in {round((time.time()-t0)*1000, 1)}ms: {res}")

        # Poll status until in_progress is False
        in_progress = True
        step_log = []
        while in_progress:
            time.sleep(1.0)
            status = http_get(f"{base_url}/api/status")
            prog = status.get("start_all_progress", {})
            in_progress = prog.get("in_progress", False)
            step_log.append(f"Step {prog.get('step')}/4: {prog.get('message')}")
            if time.time() - t0 > 45: # Safety break
                print("  ERROR: Cycle timed out!")
                break

        total_start_time = round(time.time() - t0, 2)
        print(f"  Start All finished in {total_start_time}s")

        # Verify module status and ports
        status_after_start = http_get(f"{base_url}/api/status")
        svc_states = {s["key"]: (s["status"], s.get("port"), s.get("pid")) for s in status_after_start["services"]}
        ports_listening = {
            9119: is_port_listening(9119),
            8642: is_port_listening(8642),
            8645: is_port_listening(8645)
        }
        print(f"  Module Statuses: {svc_states}")
        print(f"  Ports Listening: {ports_listening}")

        # Trigger Stop All
        t_stop0 = time.time()
        print("  Triggering Stop All...")
        http_post(f"{base_url}/api/services/stop_all")
        time.sleep(1.5)
        stop_time = round(time.time() - t_stop0, 2)

        status_after_stop = http_get(f"{base_url}/api/status")
        svc_states_stop = {s["key"]: s["status"] for s in status_after_stop["services"]}
        ports_after_stop = {
            9119: is_port_listening(9119),
            8642: is_port_listening(8642),
            8645: is_port_listening(8645)
        }
        print(f"  Module Statuses After Stop: {svc_states_stop}")
        print(f"  Ports Listening After Stop: {ports_after_stop} (all should be False)")

        cycle_ok = (
            all(s[0] == "RUNNING" for s in svc_states.values()) and
            all(ports_listening.values()) and
            all(st == "STOPPED" for st in svc_states_stop.values()) and
            not any(ports_after_stop.values())
        )
        if not cycle_ok:
            all_5_passed = False

        cycle_reports.append({
            "cycle": cycle,
            "start_time_s": total_start_time,
            "stop_time_s": stop_time,
            "running_statuses": svc_states,
            "ports_listening": ports_listening,
            "stopped_statuses": svc_states_stop,
            "ports_freed": not any(ports_after_stop.values()),
            "success": cycle_ok
        })

    results["test_1_1_cycles"] = {
        "all_passed": all_5_passed,
        "cycles": cycle_reports
    }

    # -------------------------------------------------------------
    # 2. Port Collision Error Scenario
    # -------------------------------------------------------------
    print("\n--- Test 1.2: Port Collision Scenario (Port 8642 Blocked) ---")
    http_post(f"{base_url}/api/services/stop_all")
    time.sleep(2.0)

    # Bind a dummy socket to port 8642 (exclusive)
    dummy_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    dummy_sock.bind(('127.0.0.1', 8642))
    dummy_sock.listen(1)
    print("  Dummy socket listening exclusively on 8642")

    try:
        t0 = time.time()
        http_post(f"{base_url}/api/services/start_all")
        in_progress = True
        while in_progress:
            time.sleep(1.0)
            status = http_get(f"{base_url}/api/status")
            prog = status.get("start_all_progress", {})
            in_progress = prog.get("in_progress", False)
            if time.time() - t0 > 40:
                break

        status_collision = http_get(f"{base_url}/api/status")
        services_dict = {s["key"]: s for s in status_collision["services"]}
        serve_status = services_dict["serve"]["status"]
        serve_error = services_dict["serve"]["error"]
        dash_status = services_dict["dashboard"]["status"]
        webui_status = services_dict["webui"]["status"]

        print(f"  Serve Module Status: {serve_status}, Error: {serve_error}")
        print(f"  Dashboard Status: {dash_status}, WebUI Status: {webui_status}")
        print(f"  Button/Progress Reset: in_progress={status_collision['start_all_progress']['in_progress']}")

        collision_ok = (
            serve_status == "ERROR" and
            "already used" in (serve_error or "").lower() and
            dash_status == "RUNNING" and
            webui_status == "RUNNING" and
            status_collision['start_all_progress']['in_progress'] is False
        )
        results["test_1_2_collision"] = {
            "success": collision_ok,
            "serve_status": serve_status,
            "serve_error": serve_error,
            "other_modules_running": dash_status == "RUNNING" and webui_status == "RUNNING",
            "progress_reset": not status_collision['start_all_progress']['in_progress']
        }
    finally:
        dummy_sock.close()
        time.sleep(0.5)
        http_post(f"{base_url}/api/services/stop_all")
        time.sleep(2.0)

    # -------------------------------------------------------------
    # 3. Missing/Wrong Hermes Path Scenario
    # -------------------------------------------------------------
    print("\n--- Test 1.3: Missing/Invalid Hermes Executable Path Scenario ---")
    from webui_server import MANAGER
    import hermes_manager
    orig_repo = hermes_manager.HERMES_REPO
    orig_finder = MANAGER.find_hermes_executable

    try:
        hermes_manager.HERMES_REPO = Path("C:/invalid_nonexistent_hermes_path")
        MANAGER.find_hermes_executable = lambda: None # Simulate missing binary

        res = MANAGER.start_service("dashboard")
        dash_svc = MANAGER.services["dashboard"]
        print(f"  Dashboard Start Result: {res}")
        print(f"  Dashboard Service Status: {dash_svc.status}, Error: {dash_svc.error}")

        missing_ok = (
            res.get("success") is False and
            dash_svc.status == "ERROR" and
            "Hermes binary not found" in (dash_svc.error or "")
        )
        results["test_1_3_missing_path"] = {
            "success": missing_ok,
            "status": dash_svc.status,
            "error_msg": dash_svc.error
        }
    finally:
        hermes_manager.HERMES_REPO = orig_repo
        MANAGER.find_hermes_executable = orig_finder
        MANAGER.stop_service("dashboard")

    # -------------------------------------------------------------
    # 4. Rapid 2x Click Start All
    # -------------------------------------------------------------
    print("\n--- Test 1.4: Rapid 2x Click Start All ---")
    click1_res = None
    click2_res = None

    def call1():
        nonlocal click1_res
        click1_res = http_post(f"{base_url}/api/services/start_all")

    def call2():
        nonlocal click2_res
        click2_res = http_post(f"{base_url}/api/services/start_all")

    t1 = threading.Thread(target=call1)
    t2 = threading.Thread(target=call2)
    t1.start()
    time.sleep(0.01) # 10ms gap
    t2.start()
    t1.join()
    t2.join()

    print(f"  Call 1: {click1_res}")
    print(f"  Call 2: {click2_res}")

    rapid_ok = (
        (click1_res.get("success") is True and click2_res.get("already_running") is True) or
        (click2_res.get("success") is True and click1_res.get("already_running") is True)
    )
    results["test_1_4_rapid_click"] = {
        "success": rapid_ok,
        "call1": click1_res,
        "call2": click2_res
    }

    # Wait for completion & stop
    time.sleep(10)
    http_post(f"{base_url}/api/services/stop_all")
    time.sleep(1.5)

    print("\n" + "=" * 60)
    print("BUG 1 TEST RESULTS SUMMARY:")
    print(json.dumps(results, indent=2))
    print("=" * 60)
    return results

if __name__ == "__main__":
    run_bug1_tests()
