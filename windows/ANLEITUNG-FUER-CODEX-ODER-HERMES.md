# Auftrag: SSH für das Radxa-Gateway auf diesem Windows-PC einrichten

Du (Codex oder Hermes) läufst auf **Amins Haupt-PC unter Windows** (Dual-Boot mit CachyOS,
Tailscale-Name `desptop-pc`, erwartete Tailscale-IP `100.105.45.44`).
Ziel: Das Radxa-ROCK-2A-Gateway soll per SSH „Windows schlafen / neu starten /
herunterfahren“ auslösen können. Alles ist vorbereitet. **Nicht nachdenken, nur ausführen:**

## Schritte

1. Administrator-PowerShell öffnen (oder in deiner Shell mit Adminrechten arbeiten).
2. Skript herunterladen und ausführen:

```powershell
$d = "$env:USERPROFILE\Downloads\radxa-setup"; New-Item -ItemType Directory -Force $d | Out-Null
$u = 'https://raw.githubusercontent.com/THEman6989/radxa-gateway/main/windows'
Invoke-WebRequest "$u/setup-haupt-pc-ssh.ps1" -OutFile "$d\setup-haupt-pc-ssh.ps1" -UseBasicParsing
Invoke-WebRequest "$u/setup-haupt-pc-ssh.cmd" -OutFile "$d\setup-haupt-pc-ssh.cmd" -UseBasicParsing
powershell -NoProfile -ExecutionPolicy Bypass -File "$d\setup-haupt-pc-ssh.ps1"
```

   Ohne Adminrechte stattdessen `setup-haupt-pc-ssh.cmd` per Doppelklick starten und die
   UAC-Abfrage bestätigen (Amin muss dann einmal auf „Ja“ klicken).

3. Die letzte Zeile muss lauten: `ERGEBNIS: OK - SSH fuer das Gateway ist eingerichtet.`
4. Inhalt von `C:\Users\Public\radxa-ssh-setup-result.txt` Amin zeigen (Benutzername,
   Tailscale-IP, MAC). Die Datei bleibt liegen, damit Hermes unter Linux sie später prüfen kann.

## Regeln

- **Keinen** Neustart, kein Herunterfahren, keinen Standby auslösen. Auch nicht „zum Testen“.
- Bootreihenfolge, Defender, Firewall-Profil oder UAC **nicht** ändern. Das Skript legt nur
  zwei eng begrenzte Firewall-Regeln an (SSH + Ping, nur Tailscale `100.64.0.0/10` und Heimnetz
  `192.168.2.0/24`).
- Der eingetragene Schlüssel ist nur ein **öffentlicher** Schlüssel des Gateways. Keine
  Passwörter oder privaten Schlüssel anfassen oder erzeugen.
- Bei `ERGEBNIS: FEHLER`: Ausgabe unverändert an Amin geben, nichts weiter improvisieren.
  Bekannter Fall: Wenn das Windows-Feature hängt, lädt das Skript automatisch das signierte
  offizielle OpenSSH-MSI von GitHub (PowerShell/Win32-OpenSSH).

## Danach (macht Hermes unter CachyOS, nicht du)

Hermes testet vom Gateway aus `hostname` per SSH an `100.105.45.44` und schaltet dann in der
PC-Steuerung (`https://rock-2a.tail852b38.ts.net:4443/`, Tab Haupt-PC → Windows) die Knöpfe frei.
