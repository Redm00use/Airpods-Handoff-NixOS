"""Retain proven native Discord calls using process-owned UDP socket lifetime.

Read kernel metadata only: never read socket payload, audio or credentials.
Only inode columns from UDP tables are used.
This cannot establish a new call and is deliberately not a browser heuristic.
"""
import os
from pathlib import Path
from itertools import islice
from dataclasses import dataclass

@dataclass(frozen=True)
class VoiceProcess:
    start: str
    sockets: frozenset

def process_udp(pid):
    if not str(pid).isdecimal():return None
    base=Path('/proc')/str(pid)
    try:
        def start():return (base/'stat').read_text().rsplit(') ',1)[1].split()[19]
        before=start();owned=set()
        with os.scandir(base/'fd') as entries:
            for index,entry in enumerate(islice(entries,513)):
                if index>=512:return None
                try:target=os.readlink(entry.path)
                except FileNotFoundError:continue
                if target.startswith('socket:[') and target.endswith(']'):owned.add(target[8:-1])
        udp=set()
        for kind in ('udp','udp6'):
            with (base/'net'/kind).open() as f:raw=f.read(524289)
            if len(raw)>524288:return None
            for line in raw.splitlines()[1:]:
                fields=line.split()
                if len(fields)>9 and fields[9] in owned:udp.add(fields[9])
        if start()!=before:return None
        return VoiceProcess(before,frozenset(udp))
    except (OSError,ValueError,IndexError):return None

class VoiceTransport:
    def __init__(self,probe=process_udp):
        self.probe=probe;self.records={};self.cache={};self.last_probe=None
    def reset(self):
        self.records.clear();self.cache.clear();self.last_probe=None
    def observe(self,now,objects,candidates,active):
        clients={}
        for key,obj in objects.items():
            if obj.get('type')!='PipeWire:Interface:Client':continue
            props=(obj.get('info') or {}).get('props') or {}
            if 'discord' not in str(props.get('application.process.binary','')).lower():continue
            if str(props.get('application.name','')).lower()!='webrtc voiceengine':continue
            serial=props.get('object.serial');pid=str(props.get('application.process.id',''))
            if serial is None or not pid.isdecimal():continue
            clients.setdefault(('discord',pid),set()).add((key,str(serial)))
        wanted=set(self.records)|{key for key in candidates if key in clients}
        wanted &= set(clients)
        if not wanted:self.reset();return {}
        if self.last_probe is None or now>=self.last_probe+2:
            self.cache={key:self.probe(key[1]) for key in wanted};self.last_probe=now
        else:
            for key in wanted-self.cache.keys():self.cache[key]=self.probe(key[1])
        for key in set(self.records)-wanted:self.records.pop(key,None)
        retained={}
        for key in wanted:
            snapshot=self.cache.get(key)
            if key in candidates and snapshot is not None:
                previous=self.records.get(key)
                # Never replace an established socket proof merely because a
                # different UDP socket appeared during an otherwise quiet call.
                sockets=snapshot.sockets if previous is None or previous[0]!=snapshot.start else previous[1]|snapshot.sockets
                self.records[key]=(snapshot.start,sockets,frozenset(clients[key]))
            record=self.records.get(key)
            if (active and record is not None and snapshot is not None and
                    record[0]==snapshot.start and record[1]&snapshot.sockets and
                    record[2]&clients[key] and key not in candidates):
                retained[key]={'input':False,'output':False,'running':False,
                               'app':'discord','explicit':False,'voice_transport':True}
        return retained
    def deadline(self,now):
        due=self.last_probe+2 if self.records and self.last_probe is not None else None
        return due if due is not None and due>now else None
