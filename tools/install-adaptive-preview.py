#!/usr/bin/env python3
"""Stage GPIO + MQTT + WWW + adaptive preview. Default dry run. No config edits."""
import argparse
import ast
import hashlib
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
BACKUP=runpy.run_path(str(ROOT/"tools/patch-backup.py"))

def safe_literals(source):
    # Keep generated long HTML and embedded module literals ASCII on disk,
    # without changing their decoded Unicode contents.
    tree=ast.parse(source)
    lines=source.splitlines(keepends=True)
    for n in reversed(tree.body):
        if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id.startswith("_WV_") and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str):
            lines[n.lineno-1:n.end_lineno]=[n.targets[0].id+" = "+ascii(n.value.value)+"\n"]
        elif isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=="exec":
            args=n.value.args
            if len(args)==2 and isinstance(args[0],ast.Call) and isinstance(args[0].func,ast.Name) and args[0].func.id=="compile" and len(args[0].args)==3 and all(isinstance(a,ast.Constant) and isinstance(a.value,str) for a in args[0].args) and ast.unparse(args[1])=="_am_module.__dict__":
                values=[ascii(a.value) for a in args[0].args]
                lines[n.lineno-1:n.end_lineno]=["exec(compile("+", ".join(values)+"), _am_module.__dict__)\n"]
    return "".join(lines)

def validate_bytes(data,path,interpreter=None):
    data.decode("utf-8",errors="strict")
    compile(data,str(path),"exec")
    if interpreter is not None:
        # Validate exact bytes with the interpreter used by haier.service.
        # Compilation only: never import or execute the application.
        subprocess.run([str(interpreter),"-c",
                        "import sys; b=sys.stdin.buffer.read(); b.decode('utf-8'); compile(b,sys.argv[1],'exec')",
                        str(path)],input=data,check=True,timeout=30)
    return hashlib.sha256(data).hexdigest()

def verify_installed(path,expected,interpreter):
    actual=path.read_bytes()
    if actual!=expected:
        raise RuntimeError("Written bytes differ from staged file: "+str(path))
    return validate_bytes(actual,path,interpreter)

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
            new=BACKUP["patch"](ENERGY["patch"](AUTH["patch"](SERIAL["patch"](RES["patch"](AM["patch"](base))))))
        else:
            new=GPIO["patch_gpio"](old)
        if rel=="main.py":
            new=safe_literals(new)
        data=new.encode("utf-8")
        validate_bytes(data,p)
        if data!=raw:
            result.append((p,raw,data))
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
    interpreter=a.root/"env/bin/python"
    if not a.apply:
        pending=plan(a.root)
        for path,_,data in pending:
            digest=validate_bytes(data,path,interpreter if interpreter.is_file() else None)
            print("Validated SHA256:",digest,path)
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
        if not interpreter.is_file():
            raise RuntimeError("Service interpreter not found: "+str(interpreter))
        for path,_,data in pending:
            print("Validated SHA256:",validate_bytes(data,path,interpreter),path,flush=True)
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
        stopped=False
        try:
            # Avoid concurrent shutdown/startup access to the application file.
            systemctl("stop","haier")
            stopped=True
            for path,raw,new in pending:
                if path.read_bytes()!=raw:
                    raise RuntimeError("File changed during installation: "+str(path))
                # Record rollback before writing: an exception after replace
                # must still restore the original bytes.
                written.append((path,raw))
                GPIO["atomic_write"](path,new)
                print("Verified on disk SHA256:",verify_installed(path,new,interpreter),path,flush=True)
            systemctl("start","haier")
            print("Checking new service and complete RS485 frames...",flush=True)
            recent_health()
        except BaseException:
            print("Preview startup failed: restoring backup.",flush=True)
            # Print startup errors before rollback replaces the failed invocation.
            try:
                invocation=systemctl("show","-p","InvocationID","--value","haier")
                if len(invocation)==32 and all(c in "0123456789abcdef" for c in invocation):
                    log=subprocess.run(["journalctl","--no-pager","-o","cat","_SYSTEMD_INVOCATION_ID="+invocation],capture_output=True,text=True,errors="replace",timeout=15).stdout
                    for line in log.splitlines():
                        if any(x in line for x in ("SyntaxError:","Traceback","NameError:","ImportError:","AttributeError:","TypeError:","PermissionError:","UnicodeDecodeError:","ValueError:")):
                            # Never print source lines or configuration secrets.
                            print(line[:300],flush=True)
            except Exception:
                pass
            if stopped:
                systemctl("stop","haier")
            for path,raw in reversed(written):
                GPIO["atomic_write"](path,raw)
                verify_installed(path,raw,interpreter)
            if stopped or written:
                systemctl("start","haier")
            raise
        print("Preview installed. Fresh pump telemetry confirmed. Check current owner in /v2/; saved Auto may resume.")
        print("Open /v2/ using the existing login. Check MQTT heartbeat separately.")
        print("Backup:",backup)

if __name__=="__main__":
    main()
