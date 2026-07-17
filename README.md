# Radxa ROCK 2A Gateway

Webserver auf dem Radxa ROCK 2A mit PC-Shutdown/Steuerung per Web-UI.

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
scp radxa/server.py radxa@192.168.178.159:~/www/
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
# Key-Pair für Tunnel generieren:
ssh-keygen -t ed25519 -f ~/.ssh/radxa_tunnel -N ""
ssh-copy-id -i ~/.ssh/radxa_tunnel.pub radxa@192.168.178.159
systemctl --user enable --now radxa-tunnel.service
loginctl enable-linger
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
