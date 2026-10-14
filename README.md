# Radxa ROCK 2A Gateway

Webserver auf dem Radxa ROCK 2A mit PC-Wake, Standby, Reboot und Shutdown per Web-UI. Reboot und andere destruktive Aktionen verwenden eine doppelte Bestätigung.

**Always On** sendet weiterhin alle 10 Minuten WoL und hält zusätzlich denselben KDE-PowerDevil-Suspend-only-Inhibitor wie der ComfyUI Queue Guard. Dadurch wird der automatische PC-Standby blockiert, während Bildschirmabschaltung und Sperren erlaubt bleiben.

## Aufbau

```
Browser ──→ Radxa (192.168.178.159:4000) ──→ PC-Steuerung
                 │                              │
                 ├─ Wake-on-LAN ────────────────┘
                 └─ Reverse-SSH-Tunnel ─────────┘ (Port 2222)
```

## Installation Radxa

```bash
# Dateien auf den Radxa kopieren:
scp radxa/server.py radxa/devices.py radxa/devices.json radxa/index.html radxa@192.168.178.159:~/www/
scp radxa/radxa-webserver.service radxa@192.168.178.159:~/.config/systemd/user/

# Service aktivieren:
ssh radxa@192.168.178.159
systemctl --user daemon-reload
systemctl --user enable --now radxa-webserver.service
loginctl enable-linger radxa  # überlebt Logout
```

## Installation PC

```bash
# User-SSH-Daemon (Port 2222):
mkdir -p ~/.ssh/user-sshd
ssh-keygen -t ed25519 -f ~/.ssh/user-sshd/ssh_host_ed25519_key -N ""
# sshd_config mit Port 2222 + PasswordAuth yes in ~/.ssh/user-sshd/
cp pc/user-sshd.service ~/.config/systemd/user/
systemctl --user enable --now user-sshd.service

# SSH-Key vom Radxa → PC:
cat radxa_id_ed25519.pub >> ~/.ssh/authorized_keys

# Reverse-Tunnel:
cp pc/radxa-tunnel.service ~/.config/systemd/user/
# PowerDevil Suspend-only Helper (benötigt systemweites Python mit dbus):
install -Dm755 pc/plasma_suspend_helper.py ~/.local/share/radxa-gateway/plasma_suspend_helper.py
/usr/bin/python3 -c 'import dbus'
# Key-Pair für Tunnel generieren:
ssh-keygen -t ed25519 -f ~/.ssh/radxa_tunnel -N ""
ssh-copy-id -i ~/.ssh/radxa_tunnel.pub radxa@192.168.178.159
systemctl --user enable --now radxa-tunnel.service
sudo loginctl enable-linger amin

# Power-Aktionen funktionieren damit auch vor dem ersten Desktop-Login:
echo "amin ALL=(root) NOPASSWD: /usr/bin/systemctl suspend, /usr/bin/systemctl poweroff" \
  | sudo tee /etc/sudoers.d/amin-radxa-power
sudo chmod 440 /etc/sudoers.d/amin-radxa-power
sudo visudo -cf /etc/sudoers.d/amin-radxa-power
```

## WoL aktivieren (PC, einmalig)

```bash
sudo ethtool -s eno1 wol g
# + BIOS: Wake on LAN / PCIe Wake einschalten
```

## Tailscale

```bash
# Auf dem Radxa:
sudo tailscale up --accept-routes --ssh
# Dann Auth-Link im Browser öffnen
```

Danach erreichbar unter: `http://rock-2a.<tailnet>.ts.net:4000`

## Tailscale HTTPS

Der Server bindet nur an `127.0.0.1:4000` — nicht im lokalen Netzwerk erreichbar.
Zugriff ausschließlich über Tailscale:

```bash
# Einmalig auf dem Radxa:
sudo tailscale up --accept-routes --ssh --operator=radxa
sudo tailscale serve --bg --https=4443 http://localhost:4000
```

Danach erreichbar unter: **https://rock-2a.tail852b38.ts.net:4443/**

## Mehrere PCs

Oben stehen Haupt-PC, MI50-PC und Unraid-PC mit unabhängigem Erreichbarkeitsstatus.
Der Status prüft parallel per Ping die jeweilige LAN-Adresse (`status_host`,
sonst `host`); er beweist keine physische Stromversorgung und keine API-Bereitschaft.
So erzeugt das Polling keine wiederholten unauthentifizierten SSH-Verbindungen. Die Anzeige aktualisiert sich alle fünf Sekunden und zeigt bei
fehlgeschlagener Gateway-Abfrage ausdrücklich „Status unbekannt“.

`radxa/devices.json` enthält ausschließlich serverseitige Gerätezuordnungen.
`DEVICE_CONFIG_FILE` kann einen anderen Pfad setzen. Neue Endpunkte:

- `GET /api/devices`: alle Geräte, Erreichbarkeit, Always-On-Zustand und Watchdog-Pause.
- `POST /api/devices/{main|mi50|unraid}/{wake|sleep|reboot|shutdown}`
- `POST /api/devices/{id}/alwayson/start` mit `{"hours": 24}` (0 = unbegrenzt, maximal 9999).
- `POST /api/devices/{id}/alwayson/stop`

Die bisherigen Endpunkte bleiben für den Haupt-PC erhalten. Destruktive Aktionen
benötigen weiterhin zwei Bestätigungen; bei aktivem Always On sind sie im neuen
Geräte-API bis zum Beenden des Schutzes gesperrt. Ein SSH-Timeout bedeutet
„Ergebnis unklar“, niemals einen bestätigten Shutdown.

### Zusätzliche Ziel-Helper

MI50: `pc/linux-power.sh` root-owned als `/usr/local/sbin/radxa-power` installieren.
Nur diesen geprüften Helper per sudo freigeben (kein beliebiges systemd-inhibit
als root!). Der Helper akzeptiert ausschließlich check, sleep, reboot, shutdown
und hold. hold hält einen sleep-Inhibitor bis zum Schließen der SSH-Eingabe.
Wake-on-LAN muss auf der tatsächlichen NIC und im BIOS aktiviert sein.

Unraid: `pc/unraid-power.sh` nach `/boot/config/radxa-gateway/power.sh` kopieren.
Einen separaten SSH-Key mit folgender Einschränkung in der persistenten
`/boot/config/ssh/root/authorized_keys` ergänzen:

```text
restrict,command="/bin/bash /boot/config/radxa-gateway/power.sh" ssh-ed25519 <PUBLIC-KEY>
```

Der Helper verwendet Unraids `/sbin/poweroff` bzw. `/sbin/reboot` und das bereits
installierte Dynamix-S3-Plugin für Standby. Unraid-Always-On pausiert vorhandene
automatische S3-Pluginprozesse und setzt nur selbst pausierte Prozesse mit noch
passender PID-Startzeit beim Beenden fort. Neue Pluginprozesse werden sekündlich
überprüft; dies ist kein universeller Kernel-Inhibitor und verhindert keine
extern ausgelösten Sleep-/Power-Aktionen. Standby pausiert auch VMs/Container.

MI50-Power-Aktionen setzen vor sleep, reboot oder shutdown die lokale Pause-Datei
des externen Radxa-Watchdogs. Diese Pause bleibt sichtbar und wird nicht beim
Aufwecken ungefragt aufgehoben. Die globale Watchdog-Konfiguration bleibt unverändert.
Always-On-Timer laufen serverseitig, überleben aber keinen Gateway-Service-Neustart.

Tests: `python3 -m unittest discover -s tests -v`. Destruktive Befehle werden im
HTTP-Test gemockt; ein erfolgreicher Test ist kein realer Power-Cycle-Nachweis.
