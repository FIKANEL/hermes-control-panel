"""
Hermes Control Panel - Embedded HTTP & REST API Server
Provides non-blocking multi-threaded REST endpoints and static file serving.
"""

import os
import sys
import json
import socket
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import urllib.request
import urllib.parse

from hermes_manager import HermesManager

MANAGER = HermesManager()
STATIC_DIR = Path(__file__).parent / "ui"

class HermesAPIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format, *args):
        # Override to silence polling HTTP request noise (/api/status, /api/logs)
        # Only log warning/error status codes (>= 400)
        if len(args) >= 2:
            try:
                code = int(args[1])
                if code >= 400:
                    MANAGER.add_log("server", "WARN", f"HTTP {args[0]} -> {code}")
            except Exception:
                pass

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                raw = self.rfile.read(length).decode("utf-8")
                return json.loads(raw)
        except Exception:
            pass
        return {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/status":
            self._send_json(MANAGER.get_status())
            return
        elif path == "/api/services/start_all_progress":
            self._send_json(MANAGER.get_start_all_progress())
            return
        elif path == "/api/config":
            self._send_json(MANAGER.load_config())
            return
        elif path == "/api/logs":
            self._send_json({"logs": MANAGER.get_logs()})
            return
        elif path == "/api/health":
            self._send_json({"status": "ok", "app": "hermes-control-panel"})
            return

        # Fallback to static UI file serving
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_json_body()

        if path.startswith("/api/service/"):
            parts = path.strip("/").split("/")
            if len(parts) >= 4:
                svc_key = parts[2]
                action = parts[3]
                if action == "start":
                    res = MANAGER.start_service(svc_key)
                elif action == "stop":
                    res = MANAGER.stop_service(svc_key)
                elif action == "restart":
                    res = MANAGER.restart_service(svc_key)
                else:
                    res = {"success": False, "message": "Unknown action"}
                self._send_json(res)
                return

        elif path == "/api/services/start_all":
            # Non-blocking async start all
            self._send_json(MANAGER.start_all_async())
            return

        elif path == "/api/services/stop_all":
            self._send_json(MANAGER.stop_all())
            return

        elif path == "/api/config":
            self._send_json(MANAGER.save_config(body))
            return

        elif path == "/api/logs/clear":
            MANAGER.clear_logs()
            self._send_json({"success": True})
            return

        elif path == "/api/terminal/launch":
            mode = body.get("mode", "chat")
            self._send_json(MANAGER.launch_terminal(mode))
            return

        elif path == "/api/open_folder":
            target = body.get("target", "hermes")
            self._send_json(MANAGER.open_directory(target))
            return

        elif path == "/api/chat/test":
            prompt = body.get("prompt", "Hello Hermes! Introduce yourself briefly.")
            model = body.get("model", "default")
            port = body.get("port", 8642)

            gateway_url = f"http://127.0.0.1:{port}/v1/chat/completions"
            req_data = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 256
            }
            try:
                req = urllib.request.Request(
                    gateway_url,
                    data=json.dumps(req_data).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    resp_json = json.loads(resp.read().decode("utf-8"))
                    answer = resp_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                    self._send_json({"success": True, "response": answer})
                    return
            except Exception as e:
                self._send_json({"success": False, "error": f"API request failed: {e}. Ensure Hermes RPC Backend is running on port {port}."})
                return

        self._send_json({"error": "Endpoint not found"}, status=404)

def run_server(port: int = 8640):
    server_address = ("127.0.0.1", port)
    try:
        # ThreadingHTTPServer handles each HTTP request in a separate thread,
        # preventing slow operations or polling from blocking the server.
        httpd = ThreadingHTTPServer(server_address, HermesAPIHandler)
        MANAGER.add_log("server", "INFO", f"Control Panel Server active at http://127.0.0.1:{port}")
        httpd.serve_forever()
    except OSError as e:
        MANAGER.add_log("server", "ERROR", f"Failed to bind port {port}: {e}")
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8640)
    args = parser.parse_args()
    run_server(args.port)
