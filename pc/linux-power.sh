#!/bin/bash
# Root-owned, fixed-action helper. Never accepts shell text.
set -eu
[[ $# == 1 ]] || { echo 'Unsupported action' >&2; exit 64; }
case "$1" in
 check) test -x /usr/bin/systemctl; test -x /usr/bin/systemd-inhibit; echo 'linux-power-ready';;
 sleep) exec /usr/bin/systemctl suspend;;
 reboot) exec /usr/bin/systemctl reboot;;
 shutdown) exec /usr/bin/systemctl poweroff;;
 hold) exec /usr/bin/systemd-inhibit --what=sleep --mode=block --who=Radxa-Gateway --why=Always-On /bin/sh -c 'printf "READY\n"; cat >/dev/null';;
 *) echo 'Unsupported action' >&2; exit 64;;
esac
