#!/usr/bin/env python3
"""Read-only handoff evidence; no pairing files, credentials or raw AACP packets."""
import subprocess,json,re,statistics,math
commands=[['systemctl','--user','show','airpodsctl','airpods-auto-switch','-p','ActiveState','-p','NRestarts','-p','ExecStart'],['journalctl','--user','-b','-u','airpods-auto-switch','--no-pager','-n','300'],['wpctl','status']]
for cmd in commands:
 print('\n$ '+' '.join(cmd))
 r=subprocess.run(cmd,capture_output=True,text=True,timeout=10);print(r.stdout)
 if 'journalctl' in cmd:
  values=[int(x) for x in re.findall(r'play_to_ack_ms=(\d+)','\n'.join(line for line in r.stdout.splitlines() if 'command=take confirmed=True applied=True' in line))]
  if values:
   values.sort();print(json.dumps({'play_to_ack_samples':len(values),'median_ms':statistics.median(values),'p95_ms':values[max(0,math.ceil(len(values)*.95)-1)]}))
