#!/usr/bin/env python3
"""Stage all 1.4.5_4 core patches before writing any live files."""
import argparse
import difflib
import fcntl
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
GPIO=runpy.run_path(str(ROOT/"patches/stable-gpio.py"))
MQTT=runpy.run_path(str(ROOT/"patches/stable-mqtt.py"))
WD=runpy.run_path(str(ROOT/"tools/install-mqtt-watchdog.py"))

def plan(root):
    result=[]
    for rel in ("HPi/GPIO.py","main.py"):
        p=root/rel
        if p.is_symlink() or not p.is_file():
            raise ValueError("Expected regular file: "+str(p))
        raw=p.read_bytes()
        old=raw.decode("utf-8")
        if rel=="main.py":
            new=MQTT["patch"](GPIO["patch_main"](WD["patch"](old)))
        else:
            new=GPIO["patch_gpio"](old)
        compile(new,str(p),"exec")
        if new!=old:
            result.append((p,raw,new.encode("utf-8")))
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",type=Path,default=Path("/opt/haier"))
    ap.add_argument("--apply",action="store_true")
    ap.add_argument("--diff",action="store_true")
    a=ap.parse_args()
    if a.apply and (os.geteuid()!=0 or a.root.resolve()!=Path("/opt/haier")):
        raise ValueError("Live install requires root and /opt/haier")
    if not a.apply:
        pending=plan(a.root)
        if a.diff:
            for p,old,new in pending:
                print("".join(difflib.unified_diff(old.decode().splitlines(True),new.decode().splitlines(True),str(p),str(p)+" (patched)")))
        print("Dry-run OK; %d file(s) would change"%len(pending))
        return
    with open("/run/lock/haierpi-1454.lock","w") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        pending=plan(a.root)
        if not pending:
            print("Core patches already installed; no restart.")
            return
        subprocess.run(["systemctl","is-active","--quiet","haier"],check=True)
        for p,_,_ in pending:
            if os.statvfs(p).f_flag & os.ST_RDONLY:
                raise RuntimeError("Read-only storage; no remount performed: "+str(p))
        backup=Path(tempfile.mkdtemp(prefix=".before-1454-",dir=a.root))
        for p,_,_ in pending:
            dst=backup/p.relative_to(a.root)
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p,dst)
        print("Rollback backup:",backup,flush=True)
        written=[]
        try:
            for p,raw,new in pending:
                if p.read_bytes()!=raw:
                    raise RuntimeError("File changed during installation: "+str(p))
                GPIO["atomic_write"](p,new)
                written.append((p,raw))
            subprocess.run(["systemctl","restart","haier"],check=True,timeout=120)
            import time
            time.sleep(5)
            subprocess.run(["systemctl","is-active","--quiet","haier"],check=True)
        except BaseException:
            for p,raw in reversed(written):
                GPIO["atomic_write"](p,raw)
            if written:
                subprocess.run(["systemctl","restart","haier"],check=False,timeout=120)
            raise
        print("Core service active. Check fresh pump telemetry and MQTT heartbeat manually.")

if __name__=="__main__":
    main()
