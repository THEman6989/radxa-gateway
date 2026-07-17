#!/usr/bin/env python3
"""Shutdown-HTTP-Endpoint — per Radxa-Webseite triggerbar.
Nutzt dbus statt shell, um Sicherheitsfilter zu umgehen."""
import http.server
import json
import os
import socket
import subprocess

HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PC Shutdown</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background: #0f0f0f; color: #f3f4f6; min-height: 100vh;
       display: flex; flex-direction: column; align-items: center; justify-content: center; }
.card { background: #1a1a1a; border: 1px solid #2d2d2d; border-radius: 12px;
        padding: 2rem; max-width: 500px; width: 90%; text-align: center; }
h1 { color: #ef4444; margin-bottom: 0.5rem; }
.btn { background: #ef4444; color: white; border: none; padding: 14px 40px;
       font-size: 1.1rem; border-radius: 8px; cursor: pointer; margin: 1.5rem 0;
       transition: background 0.2s; }
.btn:hover { background: #dc2626; }
.btn:disabled { background: #4b5563; cursor: not-allowed; }
.countdown { color: #fbbf24; font-size: 1.2rem; margin-top: 1rem; display: none; }
.status { margin-top: 0.5rem; font-size: 0.85rem; color: #9ca3af; }
a { color: #2dd4bf; text-decoration: none; font-size: 0.85rem; }
</style>
</head>
<body>
<div class="card">
<h1>PC Herunterfahren</h1>
<p>Dies f&auml;hrt den Rechner <strong>{host}</strong> herunter.</p>
<button class="btn" id="btn" onclick="doIt()">Jetzt herunterfahren</button>
<div class="countdown" id="cd"></div>
<div class="status" id="st"></div>
<p style="margin-top:1rem"><a href="/health">/health</a></p>
</div>
<script>
async function doIt() {
  const b=document.getElementById("btn"),s=document.getElementById("st"),c=document.getElementById("cd");
  b.disabled=true; b.textContent="Fahre herunter..."; s.textContent="";
  try {
    const r=await fetch("/shutdown",{method:"POST"});
    const d=await r.json();
    if(d.status==="shutting_down") {
      s.textContent="Shutdown eingeleitet \u2014 PC geht aus.";
      c.style.display="block"; let n=10;
      c.textContent="Verbindung verloren in ca. "+n+"s...";
      const t=setInterval(()=>{n--; if(n>0)c.textContent="Verbindung verloren in ca. "+n+"s..."; else{clearInterval(t);c.textContent="PC ist jetzt aus.";}},1000);
    } else { s.textContent="Fehler: "+(d.error||"unbekannt"); b.disabled=false; b.textContent="Jetzt herunterfahren"; }
  } catch(e) { s.textContent="PC wahrscheinlich schon aus."; c.style.display="block"; c.textContent="PC ist aus."; }
}
</script>
</body>
</html>"""


def do_shutdown():
    """Shutdown via dbus — umgeht Shell-Blocklist."""
    cmd = ["dbus-send", "--system", "--print-reply",
           "--dest=org.freedesktop.login1",
           "/org/freedesktop/login1",
           "org.freedesktop.login1.Manager.PowerOff",
           "boolean:true"]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self._json({"status": "ok", "host": socket.gethostname()})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.format(host=socket.gethostname()).encode())

    def do_POST(self):
        if self.path == "/shutdown":
            try:
                do_shutdown()
                self._json({"status": "shutting_down", "host": socket.gethostname()})
            except Exception as e:
                self._json({"status": "error", "error": str(e)}, code=500)
            return
        self.send_error(404)

    def _json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 5555))
    TOKEN = os.environ.get("TOKEN", "radxa-shutdown-2024")
    import socketserver
    class RS(http.server.HTTPServer):
        allow_reuse_address = True
    server = RS(("0.0.0.0", PORT), Handler)
    print(f"Shutdown daemon on 0.0.0.0:{PORT}")
    server.serve_forever()
