"""
Hermes Agent Manager - Core Backend Controller
Manages Hermes Agent CLI, Gateway, Bot services, and configuration.
"""

import os
import sys
import subprocess
import threading
import time
import socket
import json
import re
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, List, Optional, Any
import psutil

# Configuration and Paths
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path(LOCALAPPDATA) / "hermes"))
HERMES_REPO = HERMES_HOME / "hermes-agent"
USER_HERMES_DIR = Path.home() / ".hermes"
LOGS_DIR = Path(__file__).parent / "logs"

# Ensure directories exist
USER_HERMES_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Secret masking patterns
SECRET_PATTERNS = [
    re.compile(r'(Bearer\s+)[A-Za-z0-9_\-\.]{8,}', re.IGNORECASE),
    re.compile(r'((?:api[_-]?key|token|secret|password)[\s=:\'"]+)[A-Za-z0-9_\-\.]{8,}', re.IGNORECASE),
    re.compile(r'(sk-[A-Za-z0-9_\-]{20,})', re.IGNORECASE),
    re.compile(r'([0-9]{8,11}:[A-Za-z0-9_\-]{30,})') # Telegram Bot Token pattern
]

def mask_secrets(text: str) -> str:
    """Masks potential API keys, passwords, and tokens before logging."""
    if not text:
        return ""
    result = str(text)
    for pat in SECRET_PATTERNS:
        result = pat.sub(r'\1[REDACTED]', result)
    return result

# Setup Rotating File Logger
panel_logger = logging.getLogger("HermesPanel")
panel_logger.setLevel(logging.INFO)
log_file_path = LOGS_DIR / "panel.log"
if not panel_logger.handlers:
    rf_handler = RotatingFileHandler(
        str(log_file_path),
        maxBytes=5 * 1024 * 1024, # 5 MB
        backupCount=3,
        encoding="utf-8"
    )
    rf_formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    rf_handler.setFormatter(rf_formatter)
    panel_logger.addHandler(rf_handler)

class ServiceInfo:
    def __init__(self, key: str, name: str, description: str, default_port: Optional[int] = None):
        self.key = key
        self.name = name
        self.description = description
        self.default_port = default_port
        self.process: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.status: str = "STOPPED" # STOPPED, STARTING, RUNNING, ERROR
        self.error: Optional[str] = None
        self.started_at: Optional[float] = None
        self.log_buffer: List[str] = []

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "port": self.default_port,
            "pid": self.pid,
            "status": self.status,
            "error": self.error,
            "uptime": int(time.time() - self.started_at) if (self.status == "RUNNING" and self.started_at) else 0
        }

class HermesManager:
    def __init__(self):
        self.services: Dict[str, ServiceInfo] = {
            "dashboard": ServiceInfo(
                "dashboard",
                "Hermes Web Dashboard",
                "Official web UI dashboard & management server (Port 9119)",
                9119
            ),
            "serve": ServiceInfo(
                "serve",
                "Hermes RPC Backend",
                "Headless JSON-RPC/WebSocket server for desktop & remote clients (Port 8642)",
                8642
            ),
            "gateway": ServiceInfo(
                "gateway",
                "Hermes Messaging Gateway",
                "Unified daemon for Telegram, Discord, and WhatsApp bots",
                None
            ),
            "webui": ServiceInfo(
                "webui",
                "Hermes Chat Workspace",
                "Local interactive browser chat workspace & prompt playground (Port 8645)",
                8645
            )
        }
        self.logs: List[dict] = []
        self.max_logs = 1000
        self._lock = threading.Lock()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        
        # Start All progress & cancellation state
        self.start_all_in_progress = False
        self.start_all_step = 0
        self.start_all_total = 4
        self.start_all_message = ""
        self.start_all_cancel_requested = False
        self._start_all_lock = threading.Lock()
        self._start_all_thread = None

        self.add_log("system", "INFO", "Hermes Manager initialized")

    def add_log(self, source: str, level: str, message: str):
        clean_msg = mask_secrets(message)
        with self._lock:
            entry = {
                "timestamp": time.strftime("%H:%M:%S"),
                "source": source,
                "level": level.upper(),
                "message": clean_msg
            }
            self.logs.append(entry)
            if len(self.logs) > self.max_logs:
                self.logs.pop(0)

        # Write to persistent log file
        try:
            log_line = f"[{source.upper()}] {clean_msg}"
            if level.upper() == "ERROR":
                panel_logger.error(log_line)
            elif level.upper() == "WARN":
                panel_logger.warning(log_line)
            else:
                panel_logger.info(log_line)
        except Exception:
            pass

    def get_logs(self, limit: int = 150) -> List[dict]:
        with self._lock:
            return list(self.logs[-limit:])

    def clear_logs(self):
        with self._lock:
            self.logs.clear()
            self.add_log("system", "INFO", "Console log buffer cleared")

    def find_hermes_executable(self) -> Optional[str]:
        """Locates the installed hermes binary or python venv wrapper."""
        candidates = [
            HERMES_HOME / "bin" / "hermes.exe",
            HERMES_HOME / "bin" / "hermes.cmd",
            HERMES_REPO / ".hermes" / "bin" / "hermes.exe",
            HERMES_REPO / ".hermes" / "bin" / "hermes.cmd",
            HERMES_REPO / "venv" / "Scripts" / "hermes.exe",
            HERMES_HOME / "tools" / "hermes.cmd",
            Path(sys.prefix) / "Scripts" / "hermes.exe",
        ]
        for c in candidates:
            if c.exists():
                return str(c)

        import shutil
        in_path = shutil.which("hermes")
        if in_path:
            return in_path

        return None

    def find_hermes_python(self) -> str:
        """Locates python inside hermes store, venv, or current python."""
        tools_dir = HERMES_HOME / "tools"
        if tools_dir.exists():
            for p in tools_dir.glob("python-*/python.exe"):
                if p.exists():
                    return str(p)

        installs_dir = HERMES_HOME / "installs"
        if installs_dir.exists():
            for p in installs_dir.glob("*/pm-runtime/generations/*/Scripts/python.exe"):
                if p.exists():
                    return str(p)

        venv_py = HERMES_REPO / "venv" / "Scripts" / "python.exe"
        if venv_py.exists():
            return str(venv_py)

        return sys.executable

    def is_port_in_use(self, port: int) -> bool:
        """Checks if a TCP port is currently listening."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(('127.0.0.1', port)) == 0

    def get_port_occupant(self, port: int) -> Optional[dict]:
        """Identifies PID and process name listening on a given port."""
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                    pid = conn.pid
                    if pid:
                        try:
                            p = psutil.Process(pid)
                            return {"pid": pid, "name": p.name()}
                        except Exception:
                            return {"pid": pid, "name": "Unknown Process"}
        except Exception:
            pass
        return None

    def find_pid_by_port(self, port: int) -> Optional[int]:
        """Finds process ID listening on a given port."""
        occ = self.get_port_occupant(port)
        return occ["pid"] if occ else None

    def wait_for_port(self, port: int, timeout: float = 8.0, check_interval: float = 0.3) -> bool:
        """Polls until port is bound and listening, or timeout expires."""
        start = time.time()
        while time.time() - start < timeout:
            if self.is_port_in_use(port):
                return True
            time.sleep(check_interval)
        return False

    def wait_for_port_freed(self, port: int, timeout: float = 4.0) -> bool:
        """Polls until port is released, or timeout expires."""
        start = time.time()
        while time.time() - start < timeout:
            if not self.is_port_in_use(port):
                return True
            time.sleep(0.2)
        return False

    def _monitor_loop(self):
        """Background loop to update process states and detect crashed/external processes."""
        while True:
            time.sleep(2)
            try:
                for key, svc in self.services.items():
                    if svc.process:
                        poll = svc.process.poll()
                        if poll is not None:
                            # Process died
                            if svc.status == "RUNNING":
                                svc.status = "STOPPED"
                                self.add_log(key, "WARN", f"{svc.name} process exited with code {poll}")
                            elif svc.status != "ERROR":
                                svc.status = "STOPPED"
                            svc.pid = None
                            svc.process = None
                        else:
                            svc.status = "RUNNING"
                            svc.pid = svc.process.pid
                    elif svc.default_port:
                        # Check if running externally (e.g. started from CLI)
                        if svc.status not in ("ERROR", "STARTING"):
                            occ = self.get_port_occupant(svc.default_port)
                            if occ and occ.get("pid"):
                                p_name = (occ.get("name") or "").lower()
                                if "hermes" in p_name or "python" in p_name:
                                    svc.status = "RUNNING"
                                    svc.pid = occ["pid"]
                                else:
                                    svc.status = "STOPPED"
                                    svc.pid = None
                            elif svc.status == "RUNNING" and not svc.process:
                                svc.status = "STOPPED"
                                svc.pid = None
            except Exception:
                pass

    def start_service(self, key: str, wait_ready: bool = True, timeout: float = 30.0) -> dict:
        """Starts a specified service with port pre-checks and readiness verification."""
        if key not in self.services:
            return {"success": False, "message": f"Unknown service: {key}"}

        svc = self.services[key]

        # Port Pre-check: if port is already occupied by another PID
        if svc.default_port:
            occupant = self.get_port_occupant(svc.default_port)
            if occupant:
                if svc.process and svc.process.pid == occupant["pid"]:
                    return {"success": True, "message": f"{svc.name} is already running (PID: {svc.pid})."}
                else:
                    err_msg = f"Port {svc.default_port} is already used by {occupant['name']} (PID: {occupant['pid']})"
                    svc.status = "ERROR"
                    svc.error = err_msg
                    self.add_log(key, "ERROR", f"Start blocked: {err_msg}")
                    return {"success": False, "message": err_msg}

        if svc.status == "RUNNING" and svc.process and svc.process.poll() is None:
            return {"success": True, "message": f"{svc.name} is already running (PID: {svc.pid})."}

        hermes_exe = self.find_hermes_executable()
        hermes_py = self.find_hermes_python()

        self.add_log(key, "INFO", f"Starting {svc.name}...")
        svc.status = "STARTING"
        svc.error = None

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        
        hermes_bin = HERMES_HOME / "bin"
        if hermes_bin.exists():
            env["PATH"] = f"{hermes_bin};{env.get('PATH', '')}"

        bootstrap_code = f"import sys; sys.path.insert(0, r'{HERMES_REPO}'); import hermes_bootstrap; from hermes_cli.main import main; sys.exit(main())"

        cmd = []
        if key in ("dashboard", "serve", "gateway"):
            if hermes_exe:
                if key == "dashboard":
                    cmd = [hermes_exe, "dashboard", "--skip-build", "--no-open", "--port", "9119"]
                elif key == "serve":
                    cmd = [hermes_exe, "serve", "--isolated", "--skip-build", "--port", "8642"]
                elif key == "gateway":
                    cmd = [hermes_exe, "gateway", "run", "--external-supervisor", "--accept-hooks"]
            elif (HERMES_REPO / "hermes_bootstrap.py").exists():
                if key == "dashboard":
                    cmd = [hermes_py, "-I", "-c", bootstrap_code, "dashboard", "--skip-build", "--no-open", "--port", "9119"]
                elif key == "serve":
                    cmd = [hermes_py, "-I", "-c", bootstrap_code, "serve", "--isolated", "--skip-build", "--port", "8642"]
                elif key == "gateway":
                    cmd = [hermes_py, "-I", "-c", bootstrap_code, "gateway", "run", "--external-supervisor", "--accept-hooks"]
            else:
                svc.status = "ERROR"
                svc.error = "Hermes binary not found (hermes.exe missing or path invalid)"
                self.add_log(key, "ERROR", f"{svc.name} start blocked: {svc.error}")
                return {"success": False, "message": svc.error}
        elif key == "webui":
            webui_script = Path(__file__).parent / "webui_server.py"
            cmd = [sys.executable, str(webui_script), "--port", "8645"]

        if not cmd:
            svc.status = "ERROR"
            svc.error = "Cannot determine launch command"
            self.add_log(key, "ERROR", svc.error)
            return {"success": False, "message": svc.error}

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=creationflags
            )
            svc.process = proc
            svc.pid = proc.pid
            svc.started_at = time.time()

            # Stream output with secret masking and error resilience
            def stream_out(p, s_key):
                try:
                    for line in iter(p.stdout.readline, ''):
                        clean_line = line.strip()
                        if clean_line:
                            clean_lower = clean_line.lower()
                            is_err = any(w in clean_lower for w in ["error", "traceback", "fatal", "failed"])
                            lvl = "ERROR" if is_err else "INFO"
                            self.add_log(s_key, lvl, clean_line)
                except Exception:
                    pass
                finally:
                    try:
                        p.stdout.close()
                    except Exception:
                        pass

            t = threading.Thread(target=stream_out, args=(proc, key), daemon=True)
            t.start()

            # Readiness check with timeout
            if wait_ready:
                if svc.default_port:
                    ready = self.wait_for_port(svc.default_port, timeout=timeout)
                    if ready:
                        svc.status = "RUNNING"
                        svc.error = None
                        self.add_log(key, "SUCCESS", f"{svc.name} is listening on port {svc.default_port} (PID: {svc.pid})")
                        return {"success": True, "message": f"{svc.name} started on port {svc.default_port} (PID: {svc.pid})"}
                    else:
                        poll = proc.poll()
                        if poll is not None:
                            svc.status = "ERROR"
                            svc.error = f"Process terminated prematurely (Exit Code: {poll})"
                            self.add_log(key, "ERROR", f"{svc.name} failed: {svc.error}")
                            return {"success": False, "message": svc.error}
                        else:
                            # Exceeded timeout
                            svc.status = "ERROR"
                            svc.error = f"Startup timeout: port {svc.default_port} not ready within {int(timeout)}s"
                            self.add_log(key, "ERROR", f"{svc.name} timed out after {int(timeout)}s")
                            return {"success": False, "message": svc.error}
                else:
                    # Gateway daemon worker check
                    time.sleep(1.5)
                    poll = proc.poll()
                    if poll is not None:
                        svc.status = "ERROR"
                        svc.error = f"Daemon exited prematurely (Exit Code: {poll})"
                        self.add_log(key, "ERROR", f"{svc.name} failed: {svc.error}")
                        return {"success": False, "message": svc.error}
                    svc.status = "RUNNING"
                    svc.error = None
                    self.add_log(key, "SUCCESS", f"{svc.name} daemon active (PID: {svc.pid})")
                    return {"success": True, "message": f"{svc.name} daemon started (PID: {svc.pid})"}
            else:
                svc.status = "RUNNING"
                return {"success": True, "message": f"{svc.name} started (PID: {svc.pid})"}

        except Exception as e:
            svc.status = "ERROR"
            svc.error = str(e)
            self.add_log(key, "ERROR", f"Failed to start {svc.name}: {str(e)}")
            return {"success": False, "message": str(e)}

    def stop_service(self, key: str) -> dict:
        """Stops a specified service, killing child process tree and verifying port is freed."""
        if key not in self.services:
            return {"success": False, "message": f"Unknown service: {key}"}

        svc = self.services[key]
        self.add_log(key, "INFO", f"Stopping {svc.name}...")

        # 1. Kill managed process tree
        if svc.process:
            pid = svc.process.pid
            try:
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except Exception:
                        pass
                parent.terminate()
                _, alive = psutil.wait_procs(children + [parent], timeout=2.5)
                for p in alive:
                    try:
                        p.kill()
                    except Exception:
                        pass
            except Exception:
                try:
                    if svc.process:
                        svc.process.kill()
                except Exception:
                    pass
            svc.process = None

        # 2. Check if external or zombie PID is still holding the port
        if svc.default_port:
            ext_pid = self.find_pid_by_port(svc.default_port)
            if ext_pid:
                try:
                    p = psutil.Process(ext_pid)
                    for child in p.children(recursive=True):
                        try:
                            child.kill()
                        except Exception:
                            pass
                    p.kill()
                except Exception:
                    pass
            # Verify port freed
            freed = self.wait_for_port_freed(svc.default_port, timeout=3.0)
            if not freed:
                self.add_log(key, "WARN", f"Port {svc.default_port} may still be busy after stopping {svc.name}")

        svc.status = "STOPPED"
        svc.pid = None
        svc.started_at = None
        svc.error = None
        self.add_log(key, "INFO", f"{svc.name} stopped successfully.")
        return {"success": True, "message": f"{svc.name} stopped."}

    def restart_service(self, key: str) -> dict:
        """Restarts a service."""
        self.stop_service(key)
        time.sleep(1)
        return self.start_service(key)

    def get_start_all_progress(self) -> dict:
        """Returns the current Start All background progress."""
        with self._start_all_lock:
            return {
                "in_progress": self.start_all_in_progress,
                "step": self.start_all_step,
                "total": self.start_all_total,
                "message": self.start_all_message
            }

    def cancel_start_all(self):
        """Signals background Start All loop to stop processing further modules."""
        with self._start_all_lock:
            if self.start_all_in_progress:
                self.start_all_cancel_requested = True
                self.add_log("system", "WARN", "Start All cancellation requested")

    def start_all_async(self) -> dict:
        """Initiates Start All in background thread without blocking the HTTP server."""
        with self._start_all_lock:
            if self.start_all_in_progress:
                return {
                    "success": False,
                    "message": "Start All is already running.",
                    "already_running": True
                }
            self.start_all_in_progress = True
            self.start_all_step = 0
            self.start_all_cancel_requested = False
            self.start_all_message = "Initializing Start All..."

            self._start_all_thread = threading.Thread(target=self._run_start_all_background, daemon=True)
            self._start_all_thread.start()

        return {"success": True, "message": "Start All started in background."}

    def _run_start_all_background(self):
        """Worker thread for sequential module startup with per-module 30s timeout and summary."""
        order = ["dashboard", "serve", "gateway", "webui"]
        results = {}

        self.add_log("system", "INFO", "=== Initiating Sequential Start All ===")

        for idx, key in enumerate(order):
            with self._start_all_lock:
                if self.start_all_cancel_requested:
                    self.add_log("system", "WARN", "Start All aborted by user request.")
                    break
                self.start_all_step = idx + 1
                svc_name = self.services[key].name
                self.start_all_message = f"Starting {svc_name} ({idx + 1}/4)..."

            # Set starting state immediately for UI responsiveness
            self.services[key].status = "STARTING"
            self.services[key].error = None

            # 30-second timeout per module
            res = self.start_service(key, wait_ready=True, timeout=30.0)
            results[key] = res

            if not res.get("success"):
                self.add_log("system", "WARN", f"Module [{key}] failed: {res.get('message', 'Error')}")

            # Short delay between startups
            time.sleep(0.5)

        # Generate summary
        running = [svc.name for svc in self.services.values() if svc.status == "RUNNING"]
        failed = [f"{svc.name} ({svc.error or 'Failed'})" for svc in self.services.values() if svc.status == "ERROR"]

        if failed:
            summary = f"Ringkasan Start All: {len(running)} berjalan, {len(failed)} gagal: {', '.join(failed)}"
            self.add_log("system", "WARN", summary)
        else:
            summary = f"Ringkasan Start All: Semua {len(running)} modul berhasil berjalan."
            self.add_log("system", "SUCCESS", summary)

        with self._start_all_lock:
            self.start_all_in_progress = False
            self.start_all_message = summary

    def start_all(self) -> dict:
        """Backwards compatibility: synchronous start_all (or delegates to async)."""
        return self.start_all_async()

    def stop_all(self) -> dict:
        """Stops all running or error services cleanly, cancels ongoing start_all, and frees ports."""
        self.cancel_start_all()
        self.add_log("system", "INFO", "=== Initiating Stop All ===")
        results = {}
        for key in self.services:
            svc = self.services[key]
            if svc.status in ("RUNNING", "STARTING", "ERROR") or svc.process or (svc.default_port and self.is_port_in_use(svc.default_port)):
                results[key] = self.stop_service(key)
        self.add_log("system", "INFO", "=== Stop All Completed ===")
        return {"success": True, "results": results}

    def get_status(self) -> dict:
        """Returns overall system, service statuses, and Start All progress."""
        hermes_installed = self.find_hermes_executable() is not None or (HERMES_REPO / "venv").exists()
        
        cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()

        return {
            "hermes_installed": hermes_installed,
            "hermes_path": self.find_hermes_executable() or "Not detected yet (Installer running)",
            "services": [svc.to_dict() for svc in self.services.values()],
            "start_all_progress": self.get_start_all_progress(),
            "system": {
                "cpu": f"{cpu_percent}%",
                "ram": f"{mem.percent}% ({round(mem.used / (1024**3), 1)}GB / {round(mem.total / (1024**3), 1)}GB)"
            }
        }

    # Configuration Handlers
    def _get_config_files(self):
        """Returns list of config paths in order of preference."""
        return [
            (HERMES_HOME / "config.yaml", HERMES_HOME / ".env"),
            (USER_HERMES_DIR / "config.yaml", USER_HERMES_DIR / ".env")
        ]

    def load_config(self) -> dict:
        """Loads Hermes configuration from config.yaml and .env."""
        config_data = {}
        env_data = {}

        for cfg_file, env_file in self._get_config_files():
            if cfg_file.exists() and not config_data:
                try:
                    import yaml
                    with open(cfg_file, "r", encoding="utf-8") as f:
                        config_data = yaml.safe_load(f) or {}
                except Exception as e:
                    self.add_log("config", "WARN", f"Failed reading {cfg_file}: {e}")

            if env_file.exists() and not env_data:
                try:
                    with open(env_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                k, v = line.split("=", 1)
                                env_data[k.strip()] = v.strip().strip("'\"")
                except Exception as e:
                    self.add_log("config", "WARN", f"Failed reading {env_file}: {e}")

        model_cfg = config_data.get("model", {})
        providers_cfg = config_data.get("providers", {})
        tg_cfg = providers_cfg.get("tokengateway", {}) or providers_cfg.get("custom", {})

        provider = model_cfg.get("provider", "tokengateway")
        model_name = model_cfg.get("default", "glm-5.3")
        base_url = model_cfg.get("base_url") or tg_cfg.get("base_url", "https://tokengateway.ai.id/v1")
        
        api_key = (
            tg_cfg.get("api_key")
            or env_data.get("TOKENGATEWAY_API_KEY")
            or env_data.get("CUSTOM_API_KEY")
            or env_data.get("HERMES_CUSTOM_TOKENGATEWAY_API_KEY")
            or env_data.get("OPENROUTER_API_KEY")
            or env_data.get("OPENAI_API_KEY")
            or ""
        )

        return {
            "provider": provider,
            "model_name": model_name,
            "base_url": base_url,
            "temperature": model_cfg.get("temperature", 0.7),
            "max_tokens": model_cfg.get("max_tokens", 4096),
            "api_key": api_key,
            "tokengateway_key": env_data.get("TOKENGATEWAY_API_KEY", api_key),
            "openrouter_key": env_data.get("OPENROUTER_API_KEY", ""),
            "openai_key": env_data.get("OPENAI_API_KEY", ""),
            "anthropic_key": env_data.get("ANTHROPIC_API_KEY", ""),
            "groq_key": env_data.get("GROQ_API_KEY", ""),
            "deepseek_key": env_data.get("DEEPSEEK_API_KEY", ""),
            "nous_portal_key": env_data.get("NOUS_PORTAL_KEY", ""),
            "telegram_token": env_data.get("TELEGRAM_BOT_TOKEN", ""),
            "discord_token": env_data.get("DISCORD_BOT_TOKEN", ""),
            "api_server_port": env_data.get("API_SERVER_PORT", "8642"),
            "api_server_key": env_data.get("API_SERVER_KEY", "")
        }

    def save_config(self, data: dict) -> dict:
        """Saves configuration back to config.yaml and .env across config directories."""
        provider = data.get("provider", "tokengateway")
        model_name = data.get("model_name", "glm-5.3")
        base_url = data.get("base_url", "")
        api_key = data.get("api_key", "").strip()

        try:
            import yaml
            for cfg_path, env_path in self._get_config_files():
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                existing_yaml = {}
                if cfg_path.exists():
                    try:
                        with open(cfg_path, "r", encoding="utf-8") as f:
                            existing_yaml = yaml.safe_load(f) or {}
                    except Exception:
                        pass

                if "model" not in existing_yaml:
                    existing_yaml["model"] = {}

                existing_yaml["model"]["provider"] = provider
                existing_yaml["model"]["default"] = model_name
                if base_url:
                    existing_yaml["model"]["base_url"] = base_url
                elif "base_url" in existing_yaml["model"] and not base_url:
                    del existing_yaml["model"]["base_url"]

                existing_yaml["model"]["temperature"] = float(data.get("temperature", 0.7))
                existing_yaml["model"]["max_tokens"] = int(data.get("max_tokens", 4096))

                if provider in ("tokengateway", "custom"):
                    if "providers" not in existing_yaml:
                        existing_yaml["providers"] = {}
                    
                    target_prov = provider
                    existing_yaml["providers"][target_prov] = {
                        "name": target_prov,
                        "base_url": base_url or "https://tokengateway.ai.id/v1",
                        "api_key": api_key,
                        "default_model": model_name,
                        "api_mode": "chat_completions"
                    }

                with open(cfg_path, "w", encoding="utf-8") as f:
                    yaml.dump(existing_yaml, f, default_flow_style=False, sort_keys=False)

                # Update .env
                env_map = {}
                if env_path.exists():
                    try:
                        with open(env_path, "r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if line and not line.startswith("#") and "=" in line:
                                    k, v = line.split("=", 1)
                                    env_map[k.strip()] = v.strip().strip("'\"")
                    except Exception:
                        pass

                if provider == "tokengateway" or "tokengateway" in base_url:
                    env_map["TOKENGATEWAY_API_KEY"] = api_key
                    env_map["CUSTOM_API_KEY"] = api_key
                    env_map["HERMES_CUSTOM_TOKENGATEWAY_API_KEY"] = api_key
                    env_map["HERMES_CUSTOM_API_KEY"] = api_key
                    env_map["CUSTOM_BASE_URL"] = base_url or "https://tokengateway.ai.id/v1"
                    env_map["OPENAI_API_KEY"] = api_key
                    env_map["OPENAI_BASE_URL"] = base_url or "https://tokengateway.ai.id/v1"

                keys_to_update = {
                    "OPENROUTER_API_KEY": data.get("openrouter_key"),
                    "OPENAI_API_KEY": data.get("openai_key") or (api_key if provider == "openai" else None),
                    "ANTHROPIC_API_KEY": data.get("anthropic_key"),
                    "GROQ_API_KEY": data.get("groq_key"),
                    "DEEPSEEK_API_KEY": data.get("deepseek_key"),
                    "NOUS_PORTAL_KEY": data.get("nous_portal_key"),
                    "TELEGRAM_BOT_TOKEN": data.get("telegram_token"),
                    "DISCORD_BOT_TOKEN": data.get("discord_token"),
                    "API_SERVER_PORT": str(data.get("api_server_port", "8642")),
                    "API_SERVER_KEY": data.get("api_server_key")
                }

                for k, val in keys_to_update.items():
                    if val:
                        env_map[k] = val
                    elif k in env_map and not val and provider != "tokengateway":
                        del env_map[k]

                with open(env_path, "w", encoding="utf-8") as f:
                    for k, v in env_map.items():
                        f.write(f"{k}={v}\n")

            self.add_log("config", "SUCCESS", "Configuration and API keys updated successfully")
            return {"success": True, "message": "Settings saved successfully."}

        except Exception as e:
            self.add_log("config", "ERROR", f"Failed saving configuration: {e}")
            return {"success": False, "message": str(e)}

    # Launcher actions (Keep interactive terminals visible for user interaction!)
    def launch_terminal(self, mode: str = "chat"):
        """Launches an interactive Hermes session in an external Windows Terminal / PowerShell."""
        hermes_bin_dir = str(HERMES_HOME / "bin")
        local_bin = str(HERMES_REPO / ".hermes" / "bin")
        setup_path_cmd = f"$env:Path = '{hermes_bin_dir};{local_bin};' + $env:Path"
        
        if mode == "chat":
            cmd = f"{setup_path_cmd}; hermes chat"
            title = "Hermes Agent - Interactive Chat"
        elif mode == "tui":
            cmd = f"{setup_path_cmd}; hermes --tui"
            title = "Hermes Agent - Terminal UI"
        elif mode == "yolo":
            cmd = f"{setup_path_cmd}; hermes --yolo"
            title = "Hermes Agent - YOLO Mode (Unrestricted)"
        elif mode == "model":
            cmd = f"{setup_path_cmd}; hermes model"
            title = "Hermes Agent - Model Configuration Wizard"
        elif mode == "setup":
            cmd = f"{setup_path_cmd}; hermes setup"
            title = "Hermes Agent - Setup Wizard"
        else: # Shell
            cmd = f"{setup_path_cmd}; Write-Host '=== Hermes Agent Shell Ready ===' -ForegroundColor Green; Write-Host 'Commands: hermes, hermes chat, hermes model, hermes tools' -ForegroundColor Cyan; hermes --version"
            title = "Hermes Agent - Shell Environment"

        import shutil
        wt = shutil.which("wt.exe")
        try:
            if wt:
                subprocess.Popen([wt, "-w", "0", "new-tab", "--title", title, "powershell", "-NoExit", "-Command", cmd])
            else:
                subprocess.Popen(["start", "powershell", "-NoExit", "-Command", cmd], shell=True)
            self.add_log("launcher", "INFO", f"Launched external terminal: {title}")
            return {"success": True, "message": f"Opened {title}"}
        except Exception as e:
            self.add_log("launcher", "ERROR", f"Failed to launch terminal: {e}")
            return {"success": False, "message": str(e)}

    def open_directory(self, target: str):
        """Opens directories in Windows Explorer."""
        path_map = {
            "hermes": HERMES_HOME,
            "agent": HERMES_REPO,
            "config": USER_HERMES_DIR,
            "logs": LOGS_DIR
        }
        dest = path_map.get(target, USER_HERMES_DIR)
        dest.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(dest))
            return {"success": True, "message": f"Opened folder: {dest}"}
        except Exception as e:
            return {"success": False, "message": str(e)}
