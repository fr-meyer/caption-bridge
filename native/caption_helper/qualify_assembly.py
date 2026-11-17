"""Hosted macOS CI only; noaudio evidence, never admission."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
root = Path(sys.argv[1]).resolve()
receipt = dict(schema=5, qualification='NO_AUDIO_ONLY', images={}, rows=[])
for name in ('GuardianA','GuardianB','SyntheticHelper','NoAudioController'):
    p=root/name
    subprocess.run(['/usr/bin/codesign','--verify','--strict',str(p)],check=True,timeout=2)
    receipt['images'][name]=hashlib.sha256(p.read_bytes()).hexdigest()
subprocess.run([str(root/'StateMatrix')],check=True,timeout=2)
assert subprocess.run([str(root/'NoAudioController'),'--capture'],timeout=2).returncode==64
for mode in ('deadline','guardian_a','guardian_b','helper','suspend','parent_death'):
    child=subprocess.Popen([str(root/'NoAudioController'),'--noaudio',str(root),mode],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    owned=[]
    try:
        selector=selectors.DefaultSelector()
        selector.register(child.stdout,selectors.EVENT_READ)
        try:
            if not selector.select(3): raise RuntimeError('start_timeout')
            first=child.stdout.readline(1024)
        finally:
            selector.close()
        started=json.loads(first)
        assert set(started)=={'event','pids'} and started['event']=='started'
        owned=started['pids']
        assert len(owned)==3 and len(set(owned))==3 and all(type(p) is int and p>1 for p in owned)
        if mode=='parent_death':
            child.kill()  # only our direct controller; roles must self-close
        out,err=child.communicate(timeout=7)
        assert len(out)<=4096 and len(err)<=4096
        if mode=='parent_death':
            assert child.returncode==-signal.SIGKILL
            end=time.monotonic()+3
            pending=set(owned)
            while pending and time.monotonic()<end:
                for pid in list(pending):
                    try: os.kill(pid,0)
                    except ProcessLookupError: pending.remove(pid)
                time.sleep(.01)
            assert not pending, 'OS reaper did not retire descendants'
            row=dict(mode=mode,pids=owned,observation='ESRCH_AFTER_OS_REAPER',controller_wait=child.returncode)
        else:
            terminal=json.loads(out)
            assert child.returncode==0 and terminal['noaudio_exit']==0
            assert terminal['terminal']=='HOLD' and terminal['pids']==owned
            statuses=terminal['wait_status']
            for i,status in enumerate(statuses):
                injected=(mode=='guardian_a' and i==0) or (mode=='guardian_b' and i==1) or (mode=='helper' and i==2)
                if injected:
                    assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
                else:
                    expected=71 if i==2 and mode in ('guardian_a','guardian_b') else 72
                    assert os.WIFEXITED(status) and (os.WEXITSTATUS(status)==expected or (i==2 and expected==72 and os.WEXITSTATUS(status)==71))
            row=dict(mode=mode,terminal=terminal)
        receipt['rows'].append(row)
        owned=[]  # verified retired; never signal a potentially recycled PID
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
        # Grandchildren cannot be safely signalled by stale PID after controller reaping.
        # Roles self-close on parent change/deadline. Observe ESRCH, never claim wait ownership.
        pending=set(owned)
        until=time.monotonic()+3
        while pending and time.monotonic()<until:
            for pid in list(pending):
                try: os.kill(pid,0)
                except ProcessLookupError: pending.remove(pid)
            time.sleep(.01)
        if pending:
            print(json.dumps(dict(schema=5,failure='UNKNOWN_DESCENDANT_CLOSURE',pids=sorted(pending))))
            raise RuntimeError('unknown descendant closure, HOLD')
print(json.dumps(receipt,sort_keys=True))
