#!/usr/bin/env python3
"""Radxa Web Server mit PC-Power-Control."""
import http.server
import socket
import os
import json
import queue
import subprocess
import threading
import time

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
.btn-reboot { background: #3b82f6; }
.btn-reboot:hover { background: #2563eb; }
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
<button class="btn btn-alwayson" id="alwaysonBtn" onclick="toggleAlwaysOn()" title="PC-Standby blockieren + alle 10 Min WoL senden">🔄 Always On</button>
</div>
<div class="alwayson-status" id="alwaysonStatus"></div>

<div class="actions">
<button class="btn btn-wake" onclick="wakePC()" title="Magic Packet an PC senden">PC Aufwecken</button>
<button class="btn btn-sleep" onclick="sleepPC()" title="PC in Standby versetzen">PC Schlafen</button>
<button class="btn btn-reboot" onclick="rebootPC()" title="PC per SSH neu starten">PC Neustarten</button>
<button class="btn btn-shutdown" onclick="shutdownPC()" title="PC per SSH herunterfahren">PC Herunterfahren</button>
</div>
<div class="msg" id="msg"></div>

<p style="margin-top:1.5rem"><a href="/health">/health</a></p>
</div>

<script>
let alwaysOnActive = false;

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
  fetch("/alwayson").then(r=>r.json()).then(d=>{
    const btn = document.getElementById("alwaysonBtn");
    const s = document.getElementById("alwaysonStatus");
    if (d.active) {
      btn.classList.add("active");
      btn.textContent = "⏹ Always On (aktiv)";
      const h = Math.floor(d.remaining_min / 60);
      const m = d.remaining_min % 60;
      const protection = d.inhibitor_active
        ? "🛡 PC-Schlafschutz aktiv"
        : "⏳ WoL aktiv — verbinde PC-Schlafschutz";
      s.textContent = protection + " — noch " + (h>0 ? h+"h " : "") + m + "min";
      alwaysOnActive = true;
    } else {
      btn.classList.remove("active");
      btn.textContent = "🔄 Always On";
      s.textContent = "";
      alwaysOnActive = false;
    }
  });
}

function toggleAlwaysOn() {
  if (alwaysOnActive) {
    fetch("/alwayson/stop", {method:"POST"})
      .then(r=>r.json()).then(d=>{ msg(d.message || "Always On gestoppt.", d.status === "ok"); updateAlwaysOnStatus(); });
    return;
  }
  let hours = parseInt(prompt("Wie viele Stunden? (0 = unbegrenzt, Standard: 24)", "24"));
  if (isNaN(hours) || hours < 0) return;
  if (hours === 0) hours = 9999;
  if (!doubleConfirm("Always On für " + (hours===9999 ? "unbegrenzt" : hours+"h") + " starten?")) return;
  fetch("/alwayson/start", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({hours: hours})
  }).then(r=>r.json()).then(d=>{
    msg(d.message || "Always On gestartet.", d.status === "ok");
    updateAlwaysOnStatus();
  }).catch(e=>msg("Always-On-Fehler: " + e, false));
}

// Poll status every 30s + initial load
setInterval(updateAlwaysOnStatus, 30000);
updateAlwaysOnStatus();

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

async function rebootPC() {
  if (!doubleConfirm("PC wirklich neu starten?")) return;
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = "Starte neu...";
  msg("");
  try {
    const r = await fetch("/reboot", {method:"POST"});
    const d = await r.json();
    msg(d.message || "OK", d.status === "ok");
  } catch(e) {
    msg("Neustart wurde vermutlich bereits eingeleitet.", true);
  }
  btn.disabled = false;
  btn.textContent = "PC Neustarten";
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

# ── Server-side Always-On Timer ──────────────────────────────────────

WOL_MAC = os.environ.get("WOL_MAC", "10:7c:61:47:07:d9")
WOL_BROADCAST = os.environ.get("WOL_BROADCAST", "192.168.178.255")
WOL_PORT = os.environ.get("WOL_PORT", "9")
PC_SSH_USER = os.environ.get("PC_SSH_USER", "amin")
PC_SSH_PORT = os.environ.get("PC_SSH_PORT", "2222")
PC_UID = os.environ.get("PC_UID", "1000")
PC_INHIBIT_HELPER = os.environ.get(
    "PC_INHIBIT_HELPER",
    "/home/amin/.local/share/radxa-gateway/plasma_suspend_helper.py",
)

_alwayson_timer = None
_alwayson_end = 0
_alwayson_stop_event = None
_alwayson_inhibitor = None
_alwayson_inhibitor_error = ""
_alwayson_lock = threading.RLock()

def _wol_cmd():
    try:
        result = subprocess.run(
            ["/usr/bin/wakeonlan", "-i", WOL_BROADCAST, "-p", WOL_PORT, WOL_MAC],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            print(f"[Always-On] WoL failed: {result.stderr.strip()}", flush=True)
            return False
        return True
    except Exception as exc:
        print(f"[Always-On] WoL failed: {exc}", flush=True)
        return False

def _readline_with_timeout(stream, timeout=9.0):
    result = queue.Queue(maxsize=1)

    def read_line():
        try:
            result.put(stream.readline())
        except Exception:
            result.put("")

    threading.Thread(target=read_line, daemon=True).start()
    try:
        return result.get(timeout=timeout)
    except queue.Empty:
        return ""

def _pc_inhibitor_running():
    with _alwayson_lock:
        return _alwayson_inhibitor is not None and _alwayson_inhibitor.poll() is None

def _start_pc_inhibitor():
    """Start the same KDE suspend-only holder used by ComfyUI."""
    global _alwayson_inhibitor, _alwayson_inhibitor_error
    with _alwayson_lock:
        if _alwayson_inhibitor is not None and _alwayson_inhibitor.poll() is None:
            return True
        _alwayson_inhibitor = None
        command = [
            "ssh", "-T", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
            "-p", PC_SSH_PORT, f"{PC_SSH_USER}@localhost",
            "env", f"XDG_RUNTIME_DIR=/run/user/{PC_UID}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{PC_UID}/bus",
            "/usr/bin/python3", PC_INHIBIT_HELPER,
            "Radxa-Always-On", "Always-On-active",
        ]
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            cookie = _readline_with_timeout(process.stdout).strip() if process.stdout else ""
            if process.poll() is not None or not cookie.isdigit():
                try:
                    process.terminate()
                    _, stderr = process.communicate(timeout=2)
                except Exception:
                    process.kill()
                    stderr = ""
                _alwayson_inhibitor_error = stderr.strip() or "PC/PowerDevil noch nicht erreichbar"
                print(f"[Always-On] inhibitor pending: {_alwayson_inhibitor_error}", flush=True)
                return False
            _alwayson_inhibitor = process
            _alwayson_inhibitor_error = ""
            print(f"[Always-On] KDE suspend-only inhibitor active (cookie {cookie})", flush=True)
            return True
        except Exception as exc:
            _alwayson_inhibitor_error = str(exc)
            print(f"[Always-On] inhibitor failed: {exc}", flush=True)
            return False

def _stop_pc_inhibitor():
    global _alwayson_inhibitor, _alwayson_inhibitor_error
    with _alwayson_lock:
        process = _alwayson_inhibitor
        _alwayson_inhibitor = None
        _alwayson_inhibitor_error = ""
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.write("\n")
                process.stdin.flush()
            process.wait(timeout=3)
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        print("[Always-On] KDE suspend-only inhibitor released", flush=True)

def _alwayson_loop(end_time, stop_event):
    global _alwayson_timer, _alwayson_end, _alwayson_stop_event
    next_wol = time.time() + 600
    next_inhibitor_check = time.time() + 15
    try:
        while time.time() < end_time and not stop_event.is_set():
            now = time.time()
            if now >= next_wol:
                _wol_cmd()
                next_wol = now + 600
            if now >= next_inhibitor_check:
                if not _pc_inhibitor_running():
                    _start_pc_inhibitor()
                next_inhibitor_check = now + 15
            stop_event.wait(1)
    finally:
        with _alwayson_lock:
            if _alwayson_stop_event is stop_event:
                _alwayson_timer = None
                _alwayson_end = 0
                _alwayson_stop_event = None
                _stop_pc_inhibitor()

def start_alwayson(hours):
    global _alwayson_timer, _alwayson_end, _alwayson_stop_event
    stop_alwayson()
    end = time.time() + hours * 3600
    stop_event = threading.Event()
    thread = threading.Thread(target=_alwayson_loop, args=(end, stop_event), daemon=True)
    with _alwayson_lock:
        _alwayson_timer = thread
        _alwayson_end = end
        _alwayson_stop_event = stop_event
    _wol_cmd()
    inhibitor_active = _start_pc_inhibitor()
    thread.start()
    return inhibitor_active

def stop_alwayson():
    global _alwayson_timer, _alwayson_end, _alwayson_stop_event
    with _alwayson_lock:
        stop_event = _alwayson_stop_event
        _alwayson_timer = None
        _alwayson_end = 0
        _alwayson_stop_event = None
        if stop_event is not None:
            stop_event.set()
        _stop_pc_inhibitor()

def alwayson_status():
    with _alwayson_lock:
        active = _alwayson_timer is not None and _alwayson_timer.is_alive()
        remaining = max(0, int((_alwayson_end - time.time()) / 60)) if active else 0
        inhibitor_active = _pc_inhibitor_running()
        return {
            "active": active,
            "remaining_min": remaining,
            "inhibitor_active": inhibitor_active,
            "inhibitor_backend": "kde-powerdevil-suspend-only" if inhibitor_active else None,
            "inhibitor_error": _alwayson_inhibitor_error,
        }

# ── Handler ──────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self._json({"status":"ok","host":socket.gethostname()})
            return
        if self.path == "/alwayson":
            self._json(alwayson_status())
            return
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.end_headers()
        page = HTML.replace("{host}", socket.gethostname()).replace("{port}", str(self.server.server_address[1]))
        self.wfile.write(page.encode())

    def do_POST(self):
        if self.path == "/shutdown":
            self._run_ssh_shutdown()
        elif self.path == "/reboot":
            self._run_ssh_reboot()
        elif self.path == "/sleep":
            self._run_ssh_sleep()
        elif self.path == "/wake":
            self._run_wol()
        elif self.path == "/alwayson/start":
            self._alwayson_start()
        elif self.path == "/alwayson/stop":
            stop_alwayson()
            self._json({"status":"ok","message":"Always On gestoppt."})
        else:
            self.send_error(404)

    def _alwayson_start(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length)) if length > 0 else {}
            hours = int(data.get("hours", 24))
            if hours <= 0:
                self._json({"status":"error","message":"Stunden > 0 erforderlich"}, code=400)
                return
            inhibitor_active = start_alwayson(hours)
            message = (
                f"Always On gestartet ({hours}h): PC-Schlafschutz aktiv."
                if inhibitor_active else
                f"Always On gestartet ({hours}h): PC wird geweckt; Schlafschutz verbindet automatisch."
            )
            self._json({"status":"ok","message":message, **alwayson_status()})
        except Exception as e:
            self._json({"status":"error","message":str(e)}, code=500)

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
                "amin@localhost", "sudo -n /usr/bin/systemctl poweroff"
            ], capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                self._json({"status":"ok","message":"Shutdown eingeleitet."})
            else:
                self._json({"status":"error","message":r.stderr.strip() or "Fehler"}, code=500)
        except subprocess.TimeoutExpired:
            self._json({"status":"ok","message":"PC antwortet nicht mehr — vermutlich aus."})
        except Exception as e:
            self._json({"status":"error","message":str(e)}, code=500)

    def _run_ssh_reboot(self):
        try:
            r = subprocess.run([
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5", "-p", "2222",
                "amin@localhost", "reboot"
            ], capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                self._json({"status":"ok","message":"Neustart eingeleitet."})
            else:
                self._json({"status":"error","message":r.stderr.strip() or "Fehler"}, code=500)
        except subprocess.TimeoutExpired:
            self._json({"status":"ok","message":"PC antwortet nicht mehr — Neustart vermutlich eingeleitet."})
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
