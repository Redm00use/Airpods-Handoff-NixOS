#!/usr/bin/env python3
"""User-only status and controls; never opens a Bluetooth control channel."""
import argparse,json,os,socket,sys
from pathlib import Path

def request(action='status'):
    watch=action=='watch'
    runtime=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(runtime/'airpods-handoff.control'))
            connection.sendall(json.dumps({'action':action}).encode()+b'\n')
            connection.settimeout(None if watch else 4)
            with connection.makefile('rb') as stream:
                while True:
                    line=stream.readline(16384)
                    if not line:raise ConnectionError('Handoff service stopped')
                    result=json.loads(line)
                    print(json.dumps(result,ensure_ascii=False),flush=True)
                    if not watch:return 0 if result.get('ok',False) else 1
    except (OSError,ValueError) as error:
        print(json.dumps({'ok':False,'available':False,'title':'AirPods Handoff unavailable',
                          'detail':'Start the user handoff service.','error':str(error)},ensure_ascii=False),flush=True)
        return 1

def main():
    parser=argparse.ArgumentParser(description='AirPods status, manual return and Linux priority')
    parser.add_argument('action',nargs='?',default='status',choices=('status','watch','pin','auto','return'))
    return request(parser.parse_args().action)

if __name__=='__main__':sys.exit(main())
