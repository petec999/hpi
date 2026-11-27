#!/usr/bin/env python3
"""Stage GPIO + MQTT + WWW + adaptive preview. Default dry run. No config edits."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
CORE=runpy.run_path(str(ROOT/"tools/install-1454-core.py"))
GPIO=CORE["GPIO"]
AM=runpy.run_path(str(ROOT/"tools/patch-adaptive-preview.py"))
RES=runpy.run_path(str(ROOT/"tools/patch-core-resources.py"))
SERIAL=runpy.run_path(str(ROOT/"tools/patch-serial-charts.py"))
AUTH=runpy.run_path(str(ROOT/"tools/patch-local-auth.py"))
ENERGY=runpy.run_path(str(ROOT/"tools/patch-energy.py"))

def plan(root):
    result=[]
    for rel in ("HPi/GPIO.py","main.py"):
        p=root/rel
        if p.is_symlink() or not p.is_file():
            raise ValueError("Expected regular file: "+str(p))
        raw=p.read_bytes()
        old=raw.decode("utf-8")
        if rel=="main.py":
            base=CORE["MQTT"]["patch"](GPIO["patch_main"](CORE["WD"]["patch"](old)))
            new=ENERGY["patch"](AUTH["patch"](SERIAL["patch"](RES["patch"](AM["patch"](base)))))
        else:
            new=GPIO["patch_gpio"](old)
        compile(new,str(p),"exec")
        if new!=old:
            result.append((p,raw,new.encode("utf-8")))
    return result

def systemctl(*args):
    return subprocess.run(["systemctl",*args],check=True,timeout=150,
                          stdout=subprocess.PIPE,text=True).stdout.strip()

def recent_health():
    invocation=systemctl("show","-p","InvocationID","--value","haier")
    if len(invocation)!=32 or not all(c in "0123456789abcdef" for c in invocation):
        raise RuntimeError("Cannot identify new service invocation")
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        systemctl("is-active","--quiet","haier")
        log=subprocess.run(["journalctl","--no-pager","-o","cat","_SYSTEMD_INVOCATION_ID="+invocation],
                           check=True,capture_output=True,text=True,timeout=15).stdout
        ready=log.count("Adaptive integration: four complete recent frames")>=2
        snapshots=[]
        for l in log.splitlines():
            if "status_snapshot: " in l:
                try:
                    d=json.loads(l.split("status_snapshot: ",1)[1])
                    if (isinstance(d,dict) and isinstance(d.get("twitwo"),list) and len(d["twitwo"])==2
                        and isinstance(d.get("compinfo"),list) and len(d["compinfo"])>=2):
                        snapshots.append(d)
                except (ValueError,TypeError):
                    pass
        if ready and snapshots:
            return
        time.sleep(5)
    raise RuntimeError("Fresh pump telemetry not confirmed after restart")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path("/opt/haier"))
    p.add_argument("--apply",action="store_true")
    a=p.parse_args()
    if not a.apply:
        pending=plan(a.root)
        print("Dry-run OK. Files to update:",*[str(x[0]) for x in pending],sep="\n")
        print("No service restart or configuration changes.")
        return
    if os.geteuid()!=0 or a.root.resolve()!=Path("/opt/haier"):
        raise ValueError("Live installation requires root and /opt/haier")
    with open("/run/lock/haierpi-1454.lock","w") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        pending=plan(a.root)
        if not pending:
            print("Preview already installed; no restart.")
            return
        systemctl("is-active","--quiet","haier")
        for path,_,_ in pending:
            if os.statvfs(path).f_flag&os.ST_RDONLY:
                raise RuntimeError("Read-only storage; no remount: "+str(path))
        backup=Path(tempfile.mkdtemp(prefix=".before-adaptive-",dir=a.root))
        for path,_,_ in pending:
            dest=backup/path.relative_to(a.root)
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,dest)
        print("Rollback backup:",backup,flush=True)
        written=[]
        try:
            for path,raw,new in pending:
                if path.read_bytes()!=raw:
                    raise RuntimeError("File changed during installation: "+str(path))
                GPIO["atomic_write"](path,new)
                written.append((path,raw))
            systemctl("restart","haier")
            print("Checking new service and complete RS485 frames...",flush=True)
            recent_health()
        except BaseException:
            print("Preview startup failed: restoring backup.",flush=True)
            for path,raw in reversed(written):
                GPIO["atomic_write"](path,raw)
            if written:
                systemctl("restart","haier")
            raise
        print("Preview installed. Fresh pump telemetry confirmed. Check current owner in /v2/; saved Auto may resume.")
        print("Open /v2/ using the existing login. Check MQTT heartbeat separately.")
        print("Backup:",backup)

if __name__=="__main__":
    main()
