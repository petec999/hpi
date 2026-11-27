#!/usr/bin/env python3
"""Private bounded HaierPi application backup; not a system image."""
import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone

ROOT=Path("/opt/haier")
STORE=ROOT/".hpi-backups"
LOCK=Path("/run/lock/haierpi-1454.lock")
NAME=re.compile(r"haierpi-\d{8}T\d{6}Z-[a-f0-9]{8}\.tar\.gz")
MAX_FILE=32*1024*1024
MAX_TOTAL=64*1024*1024
MAX_MEMBERS=128
REQUIRED={"opt/config.ini","opt/haier/main.py","opt/haier/HPi/GPIO.py"}
FIXED=REQUIRED|{"opt/haier/charts.pkl","opt/haier/.hpi-web-secret-v1",
                "opt/haier/haierpi-notify.py","opt/haier/schedule_ch.json",
                "opt/haier/schedule_dhw.json","opt/haier/.adaptive-owner-v1",
                "opt/haier/.adaptive-heater-owned-v1"}
def allowed(name):
    return name in FIXED or bool(re.fullmatch(r"opt/haier/\.adaptive-[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*\.json",name)) or bool(re.fullmatch(r"opt/haier/HPi/[A-Za-z0-9_]+\.py",name))
def directory():
    STORE.mkdir(mode=0o700,exist_ok=True)
    st=STORE.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.geteuid() or st.st_mode&0o077:
        raise ValueError("Unsafe backup directory")
    return STORE
@contextlib.contextmanager
def locked():
    with open(LOCK,"a") as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
def digest(b):
    return hashlib.sha256(b).hexdigest()
def atomic(p,b,mode=0o600):
    if p.is_symlink():
        raise ValueError("Refusing symlink target")
    fd,tmp=tempfile.mkstemp(prefix=".hpi-backup-",dir=p.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            os.fchmod(f.fileno(),mode)
            f.write(b)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,p)
        tmp=None
        d=os.open(str(p.parent),os.O_RDONLY)
        try: os.fsync(d)
        finally: os.close(d)
    finally:
        if tmp is not None: os.unlink(tmp)
def stable_read(p):
    for _ in range(3):
        fd=os.open(str(p),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,"rb") as f:
            a=os.fstat(f.fileno())
            if not stat.S_ISREG(a.st_mode) or a.st_size>MAX_FILE:
                raise ValueError("Unexpected file type or size")
            b=f.read(MAX_FILE+1)
            z=os.fstat(f.fileno())
        if len(b)==a.st_size and len(b)<=MAX_FILE and (a.st_mtime_ns,a.st_size)==(z.st_mtime_ns,z.st_size):
            return b
    raise ValueError("File changed during backup; retry")
def sources(base=Path("/")):
    root=base/"opt/haier"
    names=set(FIXED)
    names.update(str(p.relative_to(base)) for p in root.glob(".adaptive-*.json"))
    names.update(str(p.relative_to(base)) for p in (root/"HPi").glob("*.py"))
    result={}
    for name in sorted(names):
        if not allowed(name): continue
        p=base/name
        if not p.exists() and not p.is_symlink():
            if name in REQUIRED: raise ValueError("Required file missing: "+name)
            continue
        result[name]=stable_read(p)
        if sum(map(len,result.values()))>MAX_TOTAL or len(result)>=MAX_MEMBERS:
            raise ValueError("Backup size limit exceeded")
    return result
def validate_payload(data):
    if not REQUIRED.issubset(data):
        raise ValueError("Missing essential files")
    import configparser
    parser=configparser.ConfigParser(interpolation=None)
    parser.read_string(data["opt/config.ini"].decode("utf-8"))
    if not parser.sections():
        raise ValueError("Empty config")
    for n,b in data.items():
        if n.endswith(".py"):
            b.decode("utf-8")
            compile(b,n,"exec")
        elif n.endswith(".json"):
            json.loads(b.decode("utf-8"))
def validate(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_TOTAL+1024*1024:
        raise ValueError("Invalid archive")
    data={}
    manifest=None
    total=0
    with tarfile.open(path,"r:gz") as t:
        for i,m in enumerate(t):
            if i>=MAX_MEMBERS or not m.isfile() or not 0<=m.size<=MAX_FILE:
                raise ValueError("Invalid archive entry")
            if m.name!="manifest.json" and not allowed(m.name):
                raise ValueError("Unexpected archive path")
            if m.name in data or (m.name=="manifest.json" and manifest is not None):
                raise ValueError("Duplicate archive entry")
            total+=m.size
            if total>MAX_TOTAL+65536: raise ValueError("Archive expanded size limit")
            with t.extractfile(m) as f:
                b=f.read(m.size+1)
            if len(b)!=m.size: raise ValueError("Truncated archive")
            if m.name=="manifest.json":
                if m.size>65536: raise ValueError("Manifest too large")
                manifest=json.loads(b)
            else: data[m.name]=b
    if not isinstance(manifest,dict) or manifest.get("schema")!=1 or manifest.get("files")!={n:digest(b) for n,b in data.items()}:
        raise ValueError("Manifest checksum mismatch")
    validate_payload(data)
    return data
def archives():
    root=directory()
    result=[]
    for p in root.iterdir():
        if NAME.fullmatch(p.name) and not p.is_symlink() and p.is_file():
            s=p.stat()
            result.append({"name":p.name,"size":s.st_size,"created":s.st_mtime})
    return sorted(result,key=lambda r:r["name"],reverse=True)
def archive_path(name):
    if not isinstance(name,str) or not NAME.fullmatch(name):
        raise ValueError("Invalid backup name")
    p=directory()/name
    if p.is_symlink() or not p.is_file(): raise ValueError("Backup missing")
    return p
def create(rotate=True):
    root=directory()
    data=sources()
    validate_payload(data)
    if shutil.disk_usage(root).free<sum(map(len,data.values()))+32*1024*1024:
        raise ValueError("Insufficient free disk space")
    name="haierpi-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+os.urandom(4).hex()+".tar.gz"
    fd,tmp=tempfile.mkstemp(prefix=".creating-",dir=root)
    os.close(fd)
    try:
        with tarfile.open(tmp,"w:gz",compresslevel=3) as t:
            manifest={"schema":1,"files":{n:digest(b) for n,b in data.items()}}
            for n,b in list(data.items())+[("manifest.json",json.dumps(manifest).encode("utf-8"))]:
                m=tarfile.TarInfo(n)
                m.size=len(b); m.mode=0o600; m.mtime=int(time.time())
                t.addfile(m,io.BytesIO(b))
        validate(Path(tmp))
        with open(tmp,"rb") as f: os.fsync(f.fileno())
        p=root/name
        os.replace(tmp,p)
        tmp=None
        d=os.open(str(root),os.O_RDONLY)
        try: os.fsync(d)
        finally: os.close(d)
        if rotate:
            for old in archives()[7:]:
                archive_path(old["name"]).unlink()
        return name
    finally:
        if tmp is not None: os.unlink(tmp)
def ctl(*args):
    return subprocess.run(["systemctl",*args],check=True,timeout=90,stdout=subprocess.PIPE,text=True).stdout.strip()
def active(unit):
    return subprocess.run(["systemctl","is-active","--quiet",unit],timeout=10).returncode==0
def health():
    invocation=ctl("show","-p","InvocationID","--value","haier.service")
    if not re.fullmatch(r"[a-f0-9]{32}",invocation):
        raise RuntimeError("Missing invocation")
    until=time.monotonic()+180
    while time.monotonic()<until:
        if not active("haier.service"): raise RuntimeError("HaierPi not active")
        log=subprocess.run(["journalctl","--no-pager","-o","cat","_SYSTEMD_INVOCATION_ID="+invocation],
                           capture_output=True,text=True,timeout=15,check=True).stdout
        if log.count("Adaptive integration: four complete recent frames")>=2 and "status_snapshot: " in log:
            return
        time.sleep(5)
    raise RuntimeError("No fresh pump telemetry")
def status(operation,state,message):
    atomic(directory()/".last-operation.json",json.dumps({"operation":operation,"state":state,"message":message,"at":time.time()}).encode("utf-8"))
def last_operation():
    try:
        return json.loads(stable_read(directory()/".last-operation.json"))
    except (OSError,ValueError):
        return None
def restore(name):
    # Only local private backups. Never restore an uploaded or untrusted
    # archive: application Python and pickle are executable content.
    with locked():
        data=validate(archive_path(name))
        if not active("haier.service"): raise ValueError("Restore requires a working installation")
        notify=active("haierpi-notify.timer")
        pre=None
        touched=[]
        stopped=False
        try:
            if notify: ctl("stop","haierpi-notify.timer","haierpi-notify.service")
            ctl("stop","haier.service")
            stopped=True
            # Snapshot after shutdown, including last writes made by the
            # service. Keep the pre-restore archive even if restore fails.
            pre=create(rotate=False)
            old=validate(archive_path(pre))
            for n,b in data.items():
                p=Path("/")/n
                if p.is_symlink(): raise ValueError("Unexpected symlink")
                mode=stat.S_IMODE(p.stat().st_mode) if p.exists() else 0o600
                touched.append((p,old.get(n),mode))
                atomic(p,b,mode)
            # Files created after the backup remain; do not silently delete
            # newer state. Restore is an overlay on the same installed base.
            ctl("start","haier.service")
            health()
            print("Restore OK; pre-restore backup: "+pre)
            return pre
        except BaseException:
            if stopped:
                if touched:
                    ctl("stop","haier.service")
                    for p,b,mode in reversed(touched):
                        if b is None: p.unlink(missing_ok=True)
                        else: atomic(p,b,mode)
                ctl("start","haier.service")
            print("Restore failed; rollback attempted. Backup: "+str(pre))
            raise
        finally:
            if notify: ctl("start","haierpi-notify.timer")
def setup():
    if os.geteuid()!=0: raise ValueError("Run as root")
    directory()
    target=ROOT/"haierpi-backup.py"
    if Path(__file__).resolve()!=target:
        atomic(target,Path(__file__).read_bytes())
    service="[Unit]\nDescription=HaierPi private daily backup\n[Service]\nType=oneshot\nExecStart=/opt/haier/env/bin/python /opt/haier/haierpi-backup.py --create\nTimeoutStartSec=120\nNice=10\nIOSchedulingClass=idle\nUMask=0077\n"
    timer="[Unit]\nDescription=Daily HaierPi backup\n[Timer]\nOnCalendar=*-*-* 03:15:00\nPersistent=true\n[Install]\nWantedBy=timers.target\n"
    for suffix,data in (("service",service),("timer",timer)):
        atomic(Path("/etc/systemd/system/haierpi-backup."+suffix),data.encode("ascii"),0o644)
    with locked():
        print("Backup:",create())
    ctl("daemon-reload")
    ctl("enable","--now","haierpi-backup.timer")
    print("Daily backup enabled. Last seven archives retained.")
def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--setup",action="store_true")
    g.add_argument("--create",action="store_true")
    g.add_argument("--restore")
    g.add_argument("--verify")
    g.add_argument("--list",action="store_true")
    a=p.parse_args()
    if a.setup: setup()
    elif a.create:
        with locked():
            status("backup","running","Tworzenie kopii")
            try:
                name=create()
                status("backup","success","Utworzono: "+name)
                print(name)
            except Exception:
                status("backup","error","Nie utworzono kopii. Sprawdź dziennik usługi.")
                raise
    elif a.restore:
        # The restore unit is singleton. A lock conflict or failure is visible.
        status("restore","running","Przywracanie: "+a.restore)
        try:
            pre=restore(a.restore)
            status("restore","success","Przywrócono kopię. Kopia sprzed przywrócenia: "+pre)
        except Exception:
            status("restore","error","Przywracanie nieudane. Sprawdź dziennik i stan HaierPi; podjęto próbę rollbacku, jeśli zmieniono pliki.")
            raise
    elif a.verify: print("OK:",len(validate(archive_path(a.verify))),"files")
    else: print(json.dumps(archives()))
if __name__=="__main__":
    try: main()
    except Exception as e:
        print("Backup operation failed:",type(e).__name__)
        raise SystemExit(1)
