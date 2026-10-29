"""Conservative event-driven fallback for playback without a usable MPRIS session.

Running graph state is not proof of audible samples. Untagged unknown applications
are intentionally excluded; MPRIS pause always takes precedence over this fallback.
"""
from dataclasses import dataclass, field
from airpods_call_detection import app_family

EXCLUDED_ROLES={'notification','event','communication','production','filter','dsp','test','accessibility','screen','camera'}
MEDIA_ROLES={'music','movie','video','game'}
MEDIA_BINARIES=('cider','spotify','firefox','zen','chromium','chrome','vlc','mpv','celluloid','rhythmbox','strawberry','audacious','lollypop')

def stream_props(objects,obj):
    info=obj.get('info') or {};p=info.get('props') or {}
    client=(objects.get(p.get('client.id'),{}).get('info') or {}).get('props') or {}
    return {**client,**p}

def muted(info):
    return any(p.get('mute') is True or p.get('softMute') is True or
               p.get('channelVolumes') and max(p['channelVolumes'])<=0
               for p in (info.get('params') or {}).get('Props',[]))

def candidates(objects,covered):
    result={}
    for key,obj in objects.items():
        info=obj.get('info') or {};p=stream_props(objects,obj)
        if key in covered or p.get('media.class')!='Stream/Output/Audio':continue
        role=str(p.get('media.role','')).lower()
        if role in EXCLUDED_ROLES or muted(info):continue
        if app_family(p) and role not in MEDIA_ROLES:continue
        identity=' '.join(str(p.get(k,'')) for k in ('application.name','application.process.binary','application.id')).lower()
        if role not in MEDIA_ROLES and not any(word in identity for word in MEDIA_BINARIES):continue
        if any(word in identity for word in ('noctalia','easyeffects','pipewire')):continue
        serial=p.get('object.serial',key)
        result[f'pw:{key}:{serial}']=info.get('state')=='running'
    return result

@dataclass
class PlaybackTracker:
    pending: dict = field(default_factory=dict)
    active: set = field(default_factory=set)
    baseline: set = field(default_factory=set)
    seen_baseline: bool = False
    debounce: float = 1.0
    stop_grace: float = .25
    stopping: dict = field(default_factory=dict)

    def reset(self):
        self.pending.clear();self.active.clear();self.baseline.clear();self.stopping.clear();self.seen_baseline=False

    def observe(self,now,streams):
        if not self.seen_baseline:
            self.baseline={key for key,running in streams.items() if running}
            self.seen_baseline=True
        # A known stop clears baseline; a future resume is an actual playback edge.
        self.baseline.intersection_update(key for key,running in streams.items() if running)
        for key,running in streams.items():
            if running:
                self.stopping.pop(key,None)
                self.pending.setdefault(key,now+self.debounce)
            else:self.pending.pop(key,None)
        for key in set(self.pending)-streams.keys():self.pending.pop(key,None)
        for key in list(self.active):
            if not streams.get(key,False):self.stopping.setdefault(key,now+self.stop_grace)
        for key,deadline in list(self.pending.items()):
            if now>=deadline:self.active.add(key)
        for key,deadline in list(self.stopping.items()):
            if now>=deadline:self.active.discard(key);self.stopping.pop(key,None)
        return set(self.active)

    def deadline(self,now):
        deadlines=[deadline for key,deadline in self.pending.items() if key not in self.active]
        deadlines.extend(self.stopping.values())
        return min((deadline for deadline in deadlines if deadline>now),default=None)
