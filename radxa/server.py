#!/usr/bin/env python3
"""Radxa Web Server mit Shutdown-Button."""
import http.server
import socket
import os
import json
import subprocess

HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Radxa ROCK 2A - Gateway</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background: #0f0f0f; color: #f3f4f6; min-height: 100vh;
       display: flex; flex-direction: column; align-items: center; justify-content: center; }
.card { background: #1a1a1a; border: 1px solid #2d2d2d; border-radius: 12px;
        padding: 2rem; max-width: 600px; width: 90%; text-align: center; }
h1 { color: #2dd4bf; margin-bottom: 1rem; }
.status-dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%;
              background: #22c55e; margin-right: 8px; animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
.info { margin-top: 1.5rem; font-size: 0.9rem; color: #9ca3af; }
.info span { color: #f3f4f6; }
.actions { margin-top: 2rem; display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap; }
.btn { padding: 12px 28px; border: none; border-radius: 8px; font-size: 0.95rem;
       cursor: pointer; transition: background 0.2s; color: white; }
.btn-wake { background: #22c55e; }
.btn-wake:hover { background: #16a34a; }
.btn-shutdown { background: #ef4444; }
.btn-shutdown:hover { background: #dc2626; }
.btn:disabled { background: #4b5563 !important; cursor: not-allowed; }
.msg { margin-top: 1rem; font-size: 0.85rem; min-height: 1.2rem; }
.msg-ok { color: #22c55e; }
.msg-err { color: #ef4444; }
a { color: #2dd4bf; text-decoration: none; font-size: 0.85rem; }
</style>
</head>
<body>
<div class="card">
<h1><span class="status-dot"></span>Radxa ROCK 2A</h1>
<p>Gateway-Server</p>
<div class="info">
<p>Host: <span>{host}</span> &middot; Port: <span>{port}</span></p>
</div>

<div class="actions">
<button class="btn btn-wake" onclick="wakePC()" title="Magic Packet an PC senden">PC Aufwecken</button>
<button class="btn btn-shutdown" onclick="shutdownPC()" title="PC per SSH herunterfahren">PC Herunterfahren</button>
</div>
<div class="msg" id="msg"></div>

<p style="margin-top:1.5rem"><a href="/health">/health</a></p>
</div>

<script>
function msg(text, ok) {
  const m = document.getElementById("msg");
  m.textContent = text;
  m.className = "msg " + (ok ? "msg-ok" : "msg-err");
}

async function wakePC() {
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = "Sende...";
  msg("");
  try {
    const r = await fetch("/wake", {method:"POST"});
    const d = await r.json();
    msg(d.message || "OK", d.status === "ok");
  } catch(e) {
    msg("Fehler: " + e, false);
  }
  btn.disabled = false;
  btn.textContent = "PC Aufwecken";
}

async function shutdownPC() {
  if (!confirm("PC wirklich herunterfahren?")) return;
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = "Fahre herunter...";
  msg("");
  try {
    const r = await fetch("/shutdown", {method:"POST"});
    const d = await r.json();
    msg(d.message || "OK", d.status === "ok");
  } catch(e) {
    msg("PC vermutlich schon aus.", true);
  }
  btn.disabled = false;
  btn.textContent = "PC Herunterfahren";
}
</script>
</body>
</html>"""

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self._json({"status":"ok","host":socket.gethostname()})
            return
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.format(
            host=socket.gethostname(),
            port=self.server.server_port
        ).encode())

    def do_POST(self):
        if self.path == "/shutdown":
            self._run_ssh_shutdown()
        elif self.path == "/wake":
            self._run_wol()
        else:
            self.send_error(404)

    def _run_ssh_shutdown(self):
        try:
            r = subprocess.run([
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5", "-p", "2222",
                "amin@localhost", "loginctl poweroff"
            ], capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                self._json({"status":"ok","message":"Shutdown eingeleitet."})
            else:
                self._json({"status":"error","message":r.stderr.strip() or "Fehler"}, code=500)
        except subprocess.TimeoutExpired:
            self._json({"status":"ok","message":"PC antwortet nicht mehr — vermutlich aus."})
        except Exception as e:
            self._json({"status":"error","message":str(e)}, code=500)

    def _run_wol(self):
        try:
            r = subprocess.run([
                "wakeonlan", "10:7c:61:47:07:d9"
            ], capture_output=True, text=True, timeout=10)
            self._json({"status":"ok","message":"Magic Packet gesendet."})
        except FileNotFoundError:
            self._json({"status":"error","message":"wakeonlan nicht installiert"}, code=500)
        except Exception as e:
            self._json({"status":"error","message":str(e)}, code=500)

    def _json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 4000))
    import socketserver
    class RS(http.server.HTTPServer):
        allow_reuse_address = True
    server = RS(("0.0.0.0", PORT), Handler)
    print(f"Radxa server on 0.0.0.0:{PORT}")
    server.serve_forever()
