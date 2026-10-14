"""Read-only external health evidence and explicitly requested MI50 hard-off."""
import json
import os
from pathlib import Path
import threading
import time
import urllib.request


def classify(w, intent, online, now):
    age = now - w.get('last_heartbeat', 0)
    same_intent = bool(intent and intent.get('boot') == w.get('boot'))
    fault = w.get('observed_fault', {})
    relevant_fault = fault.get('boot') == w.get('boot') and (
        0 <= now - fault.get('at', 0) <= 300 or
        (same_intent and fault.get('at', 0) >= intent.get('at', now)))
    if relevant_fault:
        return {'level':'danger','code':'gpu-fault','message':'AMD/GPU-Fehler erkannt — PC kann hängen. KVM prüfen.', 'evidence':str(fault.get('evidence',''))[:400]}
    if same_intent and intent.get('action') in ('shutdown','reboot','sleep'):
        elapsed = now - intent.get('at', now)
        if intent['action'] == 'reboot' and elapsed > 180:
            return {'level':'warning','code':'reboot-unconfirmed','message':'Neustart nicht bestätigt: kein neuer Boot erkannt. KVM prüfen.'}
        if elapsed > 90:
            if online or age < 12:
                return {'level':'danger','code':'shutdown-stalled','message':'Power-Aktion dauert zu lange — PC noch erreichbar; Herunterfahren/Standby hängt möglicherweise.'}
            return {'level':'warning','code':'shutdown-unconfirmed','message':'Keine Antwort nach Power-Aktion: ausgeschaltet, Standby oder eingefroren — ohne Stromsensor nicht unterscheidbar. KVM prüfen.'}
        return {'level':'info','code':'stopping','message':'Power-Aktion läuft. Abschluss wird überwacht (bis 90 Sekunden).'}
    if not 0 <= age < 15:
        return {'level':'warning','code':'heartbeat-lost','message':'Lebenszeichen fehlt: PC aus, Netzwerkproblem oder eingefroren. Ping allein beweist keinen gesunden PC.'}
    return {'level':'ok','code':'healthy','message':'Lebenszeichen aktuell · kein aktueller AMD-Fehler gemeldet.'}


def hardoff(request, sleep=time.sleep):
    status=request('/status')
    if status.get('device_id') != 'nodemcu-v3-main' or not status.get('wifi_connected') or status.get('pending_action') != 'none':
        raise RuntimeError('Controller nicht eindeutig, offline oder beschäftigt. Kein Hard-Off gesendet.')
    payload={'action':'power-off','reason':'radxa-web-manual-hard-off','hold_seconds':8,'wait_seconds':0,'delay_before_action_seconds':0}
    ack=request('/action',payload)
    if not ack.get('ok') or ack.get('status') != 'queued' or any(ack.get(k)!=payload[k] for k in ('action','hold_seconds','wait_seconds','delay_before_action_seconds')):
        raise RuntimeError('Hard-Off-Rückmeldung unklar. Nicht wiederholen; Controller/KVM prüfen.')
    sleep(9)
    status=request('/status')
    done=(status.get('device_id')=='nodemcu-v3-main' and status.get('pending_action')=='none' and status.get('action_status')=='done' and status.get('last_action')=='power-off done')
    return {'ok':done,'last_error':str(status.get('last_error',''))[:200],
            'message':'8-Sekunden-Power-Tastendruck bestätigt. Physischer Aus-Zustand nicht gemessen.' if done else 'Hard-Off-Abschluss unklar. Controller/KVM prüfen; nicht blind wiederholen.'}


class Safety:
    def __init__(self, config_path, state_path):
        self.config_path=Path(config_path)
        self.path=Path(state_path)
        self.lock=threading.RLock()

    @staticmethod
    def read(path):
        try:
            data=json.loads(Path(path).read_text())
            return data if isinstance(data,dict) else {}
        except (OSError,ValueError):return {}

    def save(self,data):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix('.next')
        tmp.write_text(json.dumps(data));tmp.chmod(0o600);os.replace(tmp,self.path)

    def watchdog(self):
        config=self.read(self.config_path)
        return self.read(Path(config.get('state_dir','/nonexistent'))/'state.json')

    def intent(self,action):
        with self.lock:
            state=self.read(self.path)
            state['intent']={'action':action,'at':time.time(),'boot':self.watchdog().get('boot')}
            self.save(state)

    def status(self,online):
        state=self.read(self.path);watchdog=self.watchdog()
        health=classify(watchdog,state.get('intent',{}),online,time.time())
        health.update(heartbeat_age_sec=max(0,int(time.time()-watchdog['last_heartbeat'])) if watchdog.get('last_heartbeat') else None,
                      hardoff=state.get('hardoff',{}))
        return health

    def pending(self):
        return self.read(self.path).get('hardoff',{}).get('status') == 'pending'

    def request(self,path,payload=None):
        if self.config_path.stat().st_mode & 0o077:raise RuntimeError('Controller-Konfiguration muss privat sein')
        c=self.read(self.config_path)
        req=urllib.request.Request(c['controller_url']+path,data=json.dumps(payload).encode() if payload else None,
            headers={'Authorization':'Bearer '+c['controller_token'],'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=5) as response:return json.loads(response.read(65536))

    def start_hardoff(self,pause):
        with self.lock:
            state=self.read(self.path)
            prior=state.get('hardoff',{})
            if prior.get('status') in ('pending','unknown'):
                return {'status':'error','message':'Vorheriger Hard-Off läuft oder sein Ergebnis ist unklar. Kein erneuter Tastendruck.'}
            if time.time()-prior.get('at',0)<15:
                return {'status':'error','message':'Hard-Off wurde gerade ausgeführt. Status/KVM prüfen.'}
            # Pause is sticky: this is an intentional power-off, not automatic recovery.
            pause()
            state['hardoff']={'status':'pending','at':time.time(),'message':'Hard-Off angefordert; Controller wird geprüft.'}
            self.save(state)  # Persist before any dispatch, also across service restart.
            threading.Thread(target=self._run,daemon=True).start()
            return {'status':'ok','message':'Hard-Off läuft unabhängig vom MI50. Abschluss erscheint im Status.'}

    def _run(self):
        try:
            result=hardoff(self.request)
            status='done' if result['ok'] else 'unknown'
        except Exception:
            result={'message':'Hard-Off nicht sicher bestätigt. Kein automatischer Wiederholungsversuch. Controller/KVM prüfen.'}
            status='unknown'
        with self.lock:
            state=self.read(self.path)
            state['hardoff'].update(status=status,**result)
            self.save(state)
