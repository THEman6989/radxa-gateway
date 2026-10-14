#!/bin/bash
# Forced-command entry for a dedicated no-forwarding SSH key on Unraid.
set -eu
if [[ -n ${SSH_ORIGINAL_COMMAND:-} ]]; then
 case "$SSH_ORIGINAL_COMMAND" in
  'radxa-power check') set -- check;;
  'radxa-power sleep') set -- sleep;;
  'radxa-power reboot') set -- reboot;;
  'radxa-power shutdown') set -- shutdown;;
  'radxa-power hold') set -- hold;;
  *) echo 'Unsupported command' >&2; exit 64;;
 esac
fi
[[ $# == 1 ]] || { echo 'Unsupported action' >&2; exit 64; }
plugin=/usr/local/emhttp/plugins/dynamix.s3.sleep/scripts/s3_sleep
case "$1" in
 check) test -x /sbin/poweroff; test -x /sbin/reboot; test -x "$plugin"; grep -qw mem /sys/power/state; echo 'unraid-power-ready';;
 sleep) /usr/sbin/ethtool -s eth1 wol g; exec "$plugin" -S -e eth1 -w g;;
 reboot) exec /sbin/reboot;;
 shutdown) exec /sbin/poweroff;;
 hold)
  # Pause only this plugin's automatic sleep processes, then restore exact PIDs.
  # Existing stopped processes are not ours and are left untouched.
  declare -A held
  resume() {
   for pid in "${!held[@]}"; do
    if read -ra fields < "/proc/$pid/stat" 2>/dev/null; then
     [[ ${fields[21]} == "${held[$pid]}" ]] && kill -CONT "$pid" 2>/dev/null || true
    fi
   done
  }
  trap resume EXIT
  trap 'exit 0' HUP INT TERM
  while :; do
   while read -r pid; do
    [[ -n $pid && -z ${held[$pid]:-} ]] || continue
    if read -ra fields < "/proc/$pid/stat" 2>/dev/null; then
     [[ ${fields[2]} != T && ${fields[2]} != t ]] || continue
     held[$pid]=${fields[21]}
     kill -STOP "$pid" 2>/dev/null || true
    fi
   done < <(pgrep -f '^(/bin/)?bash /usr/local/emhttp/plugins/dynamix.s3.sleep/scripts/s3_sleep( |$)|^/usr/local/emhttp/plugins/dynamix.s3.sleep/scripts/s3_sleep( |$)' || true)
   if [[ -z ${ready:-} ]]; then printf 'READY\n'; ready=1; fi
   if read -r -t 1 line; then break; else rc=$?; [[ $rc -gt 128 ]] || break; fi
  done
  ;;
 *) echo 'Unsupported action' >&2; exit 64;;
esac
