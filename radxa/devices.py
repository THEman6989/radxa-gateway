"""Named power targets; no device identity is accepted from HTTP clients."""
from concurrent.futures import ThreadPoolExecutor

import subprocess
import threading
from pathlib import Path
import shlex
import time
from mi50_safety import Safety


class Fleet:
    def __init__(self, config, main):
        self.config = config
        self.main = main
        self.locks = {key: threading.Lock() for key in config}
        self.holders = {}
        mi50 = config.get('mi50', {})
        self.safety = Safety(mi50['watchdog_config'], mi50['power_state']) if mi50.get('watchdog_config') else None

    def ssh(self, device, command):
        args = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'ConnectTimeout=5', '-o', 'ServerAliveInterval=10',
                '-o', 'ServerAliveCountMax=2', '-p', str(device.get('port', 22))]
        if device.get('identity'):
            args += ['-i', device['identity'], '-o', 'IdentitiesOnly=yes']
        return args + [device['user'] + '@' + device['host'], command]

    def pause_watchdog(self, device):
        if device.get('pause_file'):
            path = Path(device['pause_file'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(mode=0o600)
            if not path.is_file():
                raise RuntimeError('MI50-Watchdog konnte nicht pausiert werden')

    def action(self, key, action):
        if key not in self.config or action not in ('wake', 'sleep', 'reboot', 'shutdown'):
            raise ValueError('Unbekanntes Gerät oder Aktion')
        d = self.config[key]
        if not self.locks[key].acquire(blocking=False):
            return {'status': 'error', 'message': 'Für dieses Gerät läuft bereits eine Aktion.'}
        try:
            if key == 'mi50' and self.safety and self.safety.pending():
                return {'status': 'error', 'message': 'Hard-Off läuft oder sein Ergebnis muss nach Gateway-Neustart geprüft werden. Keine überlappende Power-Aktion.'}
            if action != 'wake' and self.alwayson(key)['active']:
                return {'status': 'error', 'message': 'Bitte zuerst Always On für dieses Gerät beenden.'}
            if action in ('sleep', 'shutdown', 'reboot'):
                self.pause_watchdog(d)
                if key == 'mi50' and self.safety:
                    self.safety.intent(action)
            if action == 'wake':
                cmd = ['/usr/bin/wakeonlan', '-i', d.get('broadcast', '192.168.178.255'),
                       '-p', '9', d['mac']]
            else:
                cmd = self.ssh(d, d.get('prefix', 'sudo -n ') + shlex.quote(d['helper']) + ' ' + action)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode:
                return {'status': 'error', 'message': r.stderr.strip() or 'Steuerbefehl fehlgeschlagen.'}
            message = 'Magic Packet gesendet; Start noch nicht bestätigt.' if action == 'wake' else 'Befehl angenommen; Status wird aktualisiert.'
            if d.get('pause_file') and action != 'wake':
                message += ' MI50-Watchdog pausiert, damit kein automatisches Wiedereinschalten erfolgt.'
            return {'status': 'ok', 'message': message}
        except subprocess.TimeoutExpired:
            return {'status': 'unknown', 'message': 'Zeitüberschreitung: Ergebnis unklar. Status prüfen, nicht blind wiederholen.'}
        except (OSError, RuntimeError) as exc:
            return {'status': 'error', 'message': str(exc)}
        finally:
            self.locks[key].release()

    def alwayson(self, key):
        if key == 'main' and self.main:
            return self.main['status']()
        holder = self.holders.get(key)
        return {'active': bool(holder), 'remaining_min': max(0, int((holder['end'] - time.time()) / 60)) if holder else 0,
                'inhibitor_active': bool(holder and holder.get('process') and holder['process'].poll() is None)}


    def start(self, key, hours):
        if key not in self.config or type(hours) is not int or not 0 <= hours <= 9999:
            raise ValueError('Stunden müssen eine ganze Zahl zwischen 0 und 9999 sein.')
        if key == 'main':
            self.main['start'](hours or 9999)
            return {'status': 'ok', 'message': 'Always On gestartet.', **self.alwayson(key)}
        self.stop(key)
        wake = self.action(key, 'wake')
        if wake['status'] != 'ok':
            return wake
        state = {'end': time.time() + (hours or 9999) * 3600,
                 'stop': threading.Event(), 'process': None, 'error': ''}
        self.holders[key] = state
        thread = threading.Thread(target=self._hold_loop, args=(key, state), daemon=True)
        state['thread'] = thread
        thread.start()
        return {'status': 'ok', 'message': 'Always On gestartet; Schlafschutz wird verbunden.', **self.alwayson(key)}

    @staticmethod
    def _release(state):
        process = state.get('process')
        state['process'] = None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def stop(self, key):
        if key not in self.config:
            raise ValueError('Unbekanntes Gerät')
        if key == 'main':
            self.main['stop']()
            return
        state = self.holders.pop(key, None)
        if state:
            state['stop'].set()
            if state.get('thread'):
                state['thread'].join(timeout=10)
            self._release(state)

    def _hold_loop(self, key, state):
        import selectors
        d = self.config[key]
        next_wake = time.time() + 600
        try:
            while not state['stop'].is_set() and time.time() < state['end']:
                if not state.get('process') or state['process'].poll() is not None:
                    self._release(state)
                    try:
                        command = d.get('prefix', 'sudo -n ') + shlex.quote(d['helper']) + ' hold'
                        p = subprocess.Popen(self.ssh(d, command), stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                        state['process'] = p
                        assert p.stdout is not None
                        with selectors.DefaultSelector() as selector:
                            selector.register(p.stdout, selectors.EVENT_READ)
                            ready = bool(selector.select(7))
                        if not ready or p.stdout.readline().strip() != 'READY':
                            self._release(state)
                            state['error'] = 'Schlafschutz nicht verbunden; neuer Versuch folgt.'
                        else:
                            state['error'] = ''
                    except OSError as exc:
                        state['error'] = str(exc)
                if time.time() >= next_wake:
                    self.action(key, 'wake')
                    next_wake = time.time() + 600
                state['stop'].wait(10)
        finally:
            self._release(state)
            if self.holders.get(key) is state:
                self.holders.pop(key, None)

    @staticmethod
    def probe(device):
        try:
            result = subprocess.run(['ping', '-n', '-c', '1', '-W', '1',
                                     device.get('status_host', device['host'])],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def status(self):
        entries = list(self.config.items())
        with ThreadPoolExecutor(max_workers=3) as pool:
            online = list(pool.map(self.probe, [d for _, d in entries]))
        return {'checked_at': time.time(), 'devices': [
            {'id': key, 'name': device['name'], 'online': up,
             'alwayson': self.alwayson(key), 'note': device.get('note', ''),
             'health': self.safety.status(up) if key == 'mi50' and self.safety else None,
             'watchdog_paused': Path(device['pause_file']).exists() if device.get('pause_file') else None}
            for (key, device), up in zip(entries, online)
        ]}
