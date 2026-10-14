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

from pathlib import Path
from urllib.parse import urlsplit
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from devices import Fleet

FLEET = None

def get_fleet():
    global FLEET
    if FLEET is None:
        config = json.loads(Path(os.environ.get('DEVICE_CONFIG_FILE', str(Path(__file__).with_name('devices.json')))).read_text())
        FLEET = Fleet(config, {'start': start_alwayson, 'stop': stop_alwayson, 'status': alwayson_status})
    return FLEET

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/devices':
            self._json(get_fleet().status())
            return
        if self.path.startswith('/api/'):
            self._json({'status': 'error', 'message': 'Nicht gefunden'}, code=404)
            return
        if self.path == '/':
            page = Path(__file__).with_name('index.html').read_text()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(page.encode())
            return
        if self.path == "/health":
            self._json({"status":"ok","host":socket.gethostname()})
            return
        if self.path == "/alwayson":
            self._json(alwayson_status())
            return
        self._json({'status': 'error', 'message': 'Nicht gefunden'}, code=404)

    def do_POST(self):
        origin = self.headers.get('Origin')
        if (origin and urlsplit(origin).netloc != self.headers.get('Host')) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self._json({'status': 'error', 'message': 'Fremder Ursprung nicht erlaubt.'}, code=403)
            return
        if self.path.startswith('/api/devices/'):
            parts = self.path.split('/')
            key = parts[3] if len(parts) > 3 else ''
            fleet = get_fleet()
            if key not in fleet.config:
                self._json({'status': 'error', 'message': 'Unbekanntes Gerät'}, code=404)
                return
            action = '/'.join(parts[4:])
            try:
                if action == 'alwayson/start':
                    length = int(self.headers.get('Content-Length', 0))
                    if not 0 < length <= 1024:
                        raise ValueError('Ungültige Anfragegröße')
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise ValueError('JSON-Objekt erforderlich')
                    result = fleet.start(key, data.get('hours', 24))
                elif action == 'alwayson/stop':
                    fleet.stop(key)
                    result = {'status': 'ok', 'message': 'Always On für dieses Gerät beendet.'}
                elif action in ('wake', 'sleep', 'reboot', 'shutdown'):
                    if key == 'main':
                        if action != 'wake' and alwayson_status()['active']:
                            self._json({'status': 'error', 'message': 'Bitte zuerst Always On beenden.'}, code=409)
                            return
                        {'wake': self._run_wol, 'sleep': self._run_ssh_sleep,
                         'reboot': self._run_ssh_reboot, 'shutdown': self._run_ssh_shutdown}[action]()
                        return
                    result = fleet.action(key, action)
                else:
                    self._json({'status': 'error', 'message': 'Unbekannte Aktion'}, code=404)
                    return
                self._json(result, code=200 if result['status'] == 'ok' else 502)
            except (ValueError, TypeError) as exc:
                self._json({'status': 'error', 'message': str(exc)}, code=400)
            return
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
            self._json({"status":"unknown","message":"Keine sichere Rückmeldung. Gerätestatus prüfen, nicht blind wiederholen."}, code=504)
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
            self._json({"status":"unknown","message":"Keine sichere Rückmeldung. Gerätestatus prüfen, nicht blind wiederholen."}, code=504)
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
            self._json({"status":"unknown","message":"Keine sichere Rückmeldung. Gerätestatus prüfen, nicht blind wiederholen."}, code=504)
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
        self.send_header("Cache-Control", "no-store")
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
    print(f"Radxa server on 127.0.0.1:{PORT}")
    server.serve_forever()
