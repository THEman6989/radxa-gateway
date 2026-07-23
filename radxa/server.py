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
.btn-sleep { background: #f59e0b; }
.btn-sleep:hover { background: #d97706; }
.btn-shutdown { background: #ef4444; }
.btn-shutdown:hover { background: #dc2626; }
.btn-alwayson { background: #8b5cf6; }
.btn-alwayson:hover { background: #7c3aed; }
.btn-alwayson.active { background: #ec4899; animation: glow 2s infinite; }
@keyframes glow { 0%, 100% { box-shadow: 0 0 8px #ec4899; } 50% { box-shadow: 0 0 20px #ec4899; } }
.btn:disabled { background: #4b5563 !important; cursor: not-allowed; }
.alwayson-status { margin-top: 0.5rem; font-size: 0.8rem; color: #ec4899; min-height: 1rem; }
.setup-row { display: flex; gap: 0.5rem; align-items: center; justify-content: center; margin: 0.5rem 0; flex-wrap: wrap; }
.setup-row input { background: #2d2d2d; border: 1px solid #4b5563; color: #f3f4f6; padding: 6px 10px; border-radius: 6px; width: 60px; text-align: center; font-size: 0.9rem; }
.setup-row label { font-size: 0.85rem; color: #9ca3af; cursor: pointer; }
.setup-row input[type=checkbox] { width: auto; margin: 0; }
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
<button class="btn btn-alwayson" id="alwaysonBtn" onclick="toggleAlwaysOn()" title="Alle 10 Min WoL senden">🔄 Always On</button>
</div>
<div class="alwayson-status" id="alwaysonStatus"></div>

<div class="actions">
<button class="btn btn-wake" onclick="wakePC()" title="Magic Packet an PC senden">PC Aufwecken</button>
<button class="btn btn-sleep" onclick="sleepPC()" title="PC in Standby versetzen">PC Schlafen</button>
<button class="btn btn-shutdown" onclick="shutdownPC()" title="PC per SSH herunterfahren">PC Herunterfahren</button>
</div>
<div class="msg" id="msg"></div>

<p style="margin-top:1.5rem"><a href="/health">/health</a></p>
</div>

<script>
let alwaysOnTimer = null;
let alwaysOnEndTime = null;

function msg(text, ok) {
  const m = document.getElementById("msg");
  m.textContent = text;
  m.className = "msg " + (ok ? "msg-ok" : "msg-err");
}

function doubleConfirm(question) {
  if (!confirm(question)) return false;
  if (!confirm("WIRKLICH? Nochmal bestätigen.")) return false;
  return true;
}

function updateAlwaysOnStatus() {
  const s = document.getElementById("alwaysonStatus");
  if (!alwaysOnEndTime) { s.textContent = ""; return; }
  const now = Date.now();
  if (now >= alwaysOnEndTime) { stopAlwaysOn(); return; }
  const min = Math.ceil((alwaysOnEndTime - now) / 60000);
  const h = Math.floor(min / 60);
  const m = min % 60;
  s.textContent = "Aktiv — noch " + (h>0 ? h+"h " : "") + m + "min";
}

async function sendWoL() {
  try { await fetch("/wake", {method:"POST"}); } catch(e) {}
}

function toggleAlwaysOn() {
  if (alwaysOnTimer) { stopAlwaysOn(); return; }
  let hours = parseInt(prompt("Wie viele Stunden? (0 = unbegrenzt, Standard: 24)", "24"));
  if (isNaN(hours) || hours < 0) return;
  if (hours === 0) hours = 9999;
  if (!doubleConfirm("Always On für " + (hours===9999 ? "unbegrenzt" : hours+"h") + " starten?")) return;
  const btn = document.getElementById("alwaysonBtn");
  btn.classList.add("active");
  btn.textContent = "⏹ Always On (aktiv)";
  alwaysOnEndTime = Date.now() + hours * 3600000;
  sendWoL();
  alwaysOnTimer = setInterval(sendWoL, 10 * 60 * 1000);
  updateAlwaysOnStatus();
  alwaysOnTimer._si = setInterval(updateAlwaysOnStatus, 30000);
}

function stopAlwaysOn() {
  if (alwaysOnTimer) {
    clearInterval(alwaysOnTimer);
    if (alwaysOnTimer._si) clearInterval(alwaysOnTimer._si);
    alwaysOnTimer = null;
  }
  alwaysOnEndTime = null;
  const btn = document.getElementById("alwaysonBtn");
  btn.classList.remove("active");
  btn.textContent = "🔄 Always On";
  document.getElementById("alwaysonStatus").textContent = "";
  msg("Always On deaktiviert.", true);
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

async function sleepPC() {
  if (!doubleConfirm("PC in Standby versetzen?")) return;
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = "Standby...";
  msg("");
  try {
    const r = await fetch("/sleep", {method:"POST"});
    const d = await r.json();
    msg(d.message || "OK", d.status === "ok");
  } catch(e) {
    msg("PC schläft jetzt.", true);
  }
  btn.disabled = false;
  btn.textContent = "PC Schlafen";
}

async function shutdownPC() {
  if (!doubleConfirm("PC wirklich herunterfahren?")) return;
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
        page = HTML.replace("{host}", socket.gethostname()).replace("{port}", str(self.server.server_address[1]))
        self.wfile.write(page.encode())

    def do_POST(self):
        if self.path == "/shutdown":
            self._run_ssh_shutdown()
        elif self.path == "/sleep":
            self._run_ssh_sleep()
        elif self.path == "/wake":
            self._run_wol()
        else:
            self.send_error(404)

    def _run_ssh_sleep(self):
        try:
            r = subprocess.run([
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5", "-p", "2222",
                "amin@localhost", "sudo systemctl suspend"
            ], capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                self._json({"status":"ok","message":"PC geht in Standby."})
            else:
                err = r.stderr.strip() or f"Exit-Code {r.returncode}"
                self._json({"status":"error","message":err}, code=500)
        except subprocess.TimeoutExpired:
            self._json({"status":"ok","message":"PC antwortet nicht mehr — vermutlich im Standby."})
        except Exception as e:
            self._json({"status":"error","message":str(e)}, code=500)

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
        mac = os.environ.get("WOL_MAC", "10:7c:61:47:07:d9")
        broadcast = os.environ.get("WOL_BROADCAST", "192.168.178.255")
        port = os.environ.get("WOL_PORT", "9")
        try:
            r = subprocess.run(
                ["/usr/bin/wakeonlan", "-i", broadcast, "-p", port, mac],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0:
                msg = r.stdout.strip() or f"Magic Packet an {mac} über {broadcast}:{port} gesendet."
                self._json({"status":"ok","message":msg})
            else:
                err = r.stderr.strip() or r.stdout.strip() or f"wakeonlan Exit-Code {r.returncode}"
                self._json({"status":"error","message":err}, code=500)
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
    server = RS(("127.0.0.1", PORT), Handler)
    print(f"Radxa server on 0.0.0.0:{PORT}")
    server.serve_forever()
