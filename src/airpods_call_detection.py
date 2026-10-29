"""Recognize duplex communications without assuming applications set media.role."""
from dataclasses import dataclass, field

def app_family(props):
    binary=str(props.get('application.process.binary','')).lower()
    name=str(props.get('application.name','')).lower()
    for key in ('discord','telegram','zoom','teams','signal','jami','element'):
        if key in binary or key in name:return key
    return ''

def call_sessions(objects):
    clients={key:(o.get('info') or {}).get('props',{}) for key,o in objects.items() if o.get('type')=='PipeWire:Interface:Client'}
    groups={}
    for key,obj in objects.items():
        info=obj.get('info') or {};p=info.get('props') or {}
        cls=p.get('media.class','')
        if cls not in ('Stream/Input/Audio','Stream/Output/Audio'):continue
        if info.get('state') not in ('running','idle','error'):continue
        merged=dict(clients.get(p.get('client.id'),{}));merged.update(p)
        role=str(merged.get('media.role','')).lower();name=str(merged.get('node.name','')).lower()
        app=app_family(merged)
        # Spectrum, monitor and notification streams never establish a call lease.
        target=str(merged.get('target.object','')).lower()
        if role in ('notification','event','music','movie','video','game','dsp','filter'):continue
        if 'spectrum' in str(merged.get('application.name','')).lower():continue
        if str(merged.get('stream.capture.sink','')).lower() in ('true','1') or (cls=='Stream/Input/Audio' and ('bluez_output.' in target or target.endswith('.monitor') or target=='easyeffects_sink')):continue
        if not (app or role=='communication' or 'webrtc voiceengine' in name):continue
        pid=merged.get('application.process.id')
        identity=(app or str(merged.get('application.process.binary','unknown')),str(pid if pid is not None else p.get('client.id',key)))
        group=groups.setdefault(identity,{'input':False,'output':False,'running':False,'app':app or 'communication','explicit':False})
        group['input' if cls=='Stream/Input/Audio' else 'output']=True
        group['running'] |= info.get('state')=='running'
        group['explicit'] |= role=='communication'
    return {key:value for key,value in groups.items() if value['explicit'] or value['input'] and value['output']}

@dataclass
class CallTracker:
    active: bool = False
    candidates: dict = field(default_factory=dict)
    onset: float | None = None
    expiry: float | None = None
    evidence: tuple = ()

    def observe(self,now,objects):
        self.candidates=call_sessions(objects)
        present=bool(self.candidates) and (self.active or any(x['running'] for x in self.candidates.values()))
        if present:
            self.expiry=None
            self.evidence=tuple(sorted({x['app'] for x in self.candidates.values()}))
            if self.onset is None:self.onset=now
        else:
            self.onset=None
            if self.active and self.expiry is None:self.expiry=now+1.25
        return self.tick(now)

    def tick(self,now):
        if self.onset is not None and now>=self.onset+.2:self.active=True
        if self.expiry is not None and now>=self.expiry:
            self.active=False;self.expiry=None;self.evidence=()
        return self.active

    def deadline(self,now):
        values=[]
        if not self.active and self.onset is not None:values.append(self.onset+.2)
        if self.expiry is not None:values.append(self.expiry)
        return min((x for x in values if x>now),default=None)
