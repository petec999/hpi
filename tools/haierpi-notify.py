#!/usr/bin/env python3
"""Read-only experiment checkpoint monitor; sends push via existing HA API."""
import configparser
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT=Path("/opt/haier")
PY=ROOT/"env/bin/python"
SCRIPT=ROOT/"haierpi-notify.py"
CONFIG=ROOT/".adaptive-notify-config-v1.json"
STATE=ROOT/".adaptive-notify-state-v1.json"
CHECKPOINT=ROOT/".adaptive-experiment-v1.json"
UNIT="haierpi-notify"
LABELS=("Eco / OFF","Quiet / OFF","Quiet / ON","Eco / ON","Turbo / ON","Turbo / OFF")
DEFAULT={"progress":False,"shortfall":True,"finished":True,"stalled":True,"stall_hours":48}

def load(path,default=None):
    if path.is_symlink():
        raise ValueError("Invalid state path")
    try:
        if path.stat().st_size>32768:
            raise ValueError("State file too large")
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default

def atomic(path,data):
    if path.is_symlink():
        raise ValueError("Invalid output path")
    fd,tmp=tempfile.mkstemp(prefix=".hpi-notify-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,path)
        tmp=None
        fd=os.open(str(path.parent),os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if tmp is not None:
            os.unlink(tmp)

def save(path,data):
    atomic(path,json.dumps(data,ensure_ascii=True,allow_nan=False).encode("ascii"))

def api(method,path,payload=None):
    import requests
    c=configparser.ConfigParser(interpolation=None)
    if not c.read("/opt/config.ini"):
        raise ValueError("No HaierPi config")
    h=c["HOMEASSISTANT"]
    url=h["HAADDR"].rstrip("/") + ":" + h["HAPORT"]
    r=requests.request(method,url+path,headers={"Authorization":"Bearer "+h["KEY"]},
                       json=payload,timeout=(3,8),allow_redirects=False)
    if not 200<=r.status_code<300:
        raise RuntimeError("HA HTTP "+str(r.status_code))
    return r.json()

def targets():
    return sorted(s for d in api("GET","/api/services") if d["domain"]=="notify"
                  for s in d["services"] if re.fullmatch(r"mobile_app_[a-z0-9_]+",s))

def push(service,title,message):
    if not re.fullmatch(r"mobile_app_[a-z0-9_]+",service):
        raise ValueError("Invalid notify target")
    api("POST","/api/services/notify/"+service,{"title":title,"message":message})
    print("HA accepted notification",flush=True)

def session():
    d=load(CHECKPOINT,{})
    if not isinstance(d,dict) or d.get("schema")!=1:
        return None
    s=d.get("session")
    if s is None:
        return None
    if not isinstance(s,dict) or type(s.get("since")) not in (int,float) or not math.isfinite(s["since"]) or not 0<s["since"]<=time.time()+60:
        raise ValueError("Invalid experiment session")
    return s

def snapshot(s):
    counts=s.get("counts",[0]*6)
    continuous=s.get("continuous",[None]*6)
    deferred=s.get("deferred",[None]*6)
    if not isinstance(counts,list) or len(counts)!=6 or any(type(n) is not int or not 0<=n<=3 for n in counts):
        raise ValueError("Invalid cycle counts")
    if any(not isinstance(x,list) or len(x)!=6 for x in (continuous,deferred)):
        raise ValueError("Invalid experiment data")
    if any(x is not None and not isinstance(x,dict) for x in continuous+deferred):
        raise ValueError("Invalid experiment record")
    for x in deferred:
        if x is not None and (type(x.get("at")) not in (int,float) or not math.isfinite(x["at"])):
            raise ValueError("Invalid deferral")
    return {"session":s["since"],"counts":list(counts),
            "done":[counts[i]>=3 or continuous[i] is not None for i in range(6)],
            "continuous":[x is not None for x in continuous],
            "deferred":[x["at"] if x is not None else None for x in deferred],
            "finished":s.get("finished") is True}

def progress_text(cur):
    return ("Konfiguracje ukończone: %d/6. Pełne cykle: %d/18 (maks.). Próby ciągłe: %d. "
            "Nieukończone z odnotowanym odłożeniem: %d." %
            (sum(cur["done"]),sum(cur["counts"]),sum(cur["continuous"]),
             sum(not done and at is not None for done,at in zip(cur["done"],cur["deferred"]))))

def evaluate(s,old,cfg,now):
    """Pure transition logic. Return notification lines and next dedup state."""
    cur=snapshot(s)
    same=bool(old and old.get("session")==cur["session"])
    if not same:
        old={"session":cur["session"],"counts":[0]*6,"done":[False]*6,
             "continuous":[False]*6,"deferred":[None]*6,"finished":False,
             "last_progress":now,"stall_sent":False}
    # Migrate the old monitor's saved dedup state without repeating a
    # continuous trial that was already known to be a completed configuration.
    old_cont=old.get("continuous",[d and n<3 for d,n in zip(old["done"],old["counts"])])
    lines=[]
    progress=any(cur[k]!=old.get(k) for k in ("counts","done","deferred","finished")) or cur["continuous"]!=old_cont
    last_progress=now if progress else old.get("last_progress",now)
    stall_sent=False if progress else bool(old.get("stall_sent"))
    finished=cfg["finished"] and cur["finished"] and not old.get("finished")
    if cfg["shortfall"] and not cur["finished"]:
        for i,rec in enumerate(s.get("deferred",[None]*6)):
            if rec is not None and cur["deferred"][i]!=old["deferred"][i]:
                outdoor=rec.get("outdoor")
                weather=(" przy %.1f°C"%outdoor) if type(outdoor) in (float,int) else ""
                lines.append("Ochrona komfortu: odłożono "+LABELS[i]+weather+
                             " (%d/3 pełnych cykli)."%cur["counts"][i])
    if cfg["progress"]:
        for i,label in enumerate(LABELS):
            delta=cur["counts"][i]-old["counts"][i]
            trial=cur["continuous"][i] and not old_cont[i]
            if delta>0 or trial:
                parts=[]
                if delta>0:
                    parts.append(("Zaliczono cykl" if delta==1 else "Zaliczono %d cykle"%delta)+
                                 " – %d/3 pełnych cykli"%cur["counts"][i])
                if trial:
                    parts.append("Zaliczono próbę ciągłą 3 h")
                if cur["done"][i] and not old["done"][i]:
                    parts.append("konfiguracja ukończona")
                lines.append(label+": "+"; ".join(parts)+".")
    if finished:
        lines.append("Eksperyment zakończony. Raport Adaptive jest dostępny w WWW v2.")
    if not cur["finished"] and cfg["stalled"] and not stall_sent and now-last_progress>=cfg["stall_hours"]*3600:
        lines.append("Od %d h bez nowego wyniku zapisanej sesji. Test może być wstrzymany, czekać na postój lub pogodę. Sprawdź WWW v2."%cfg["stall_hours"])
        stall_sent=True
    if lines:
        # Keep the totals in the same push, including when several checkpoint
        # changes are coalesced by one poll.
        lines[-1]+="\n"+progress_text(cur)
    cur.update(last_progress=last_progress,stall_sent=stall_sent)
    return lines,cur

def settings():
    c=load(CONFIG)
    if not isinstance(c,dict):
        raise ValueError("Run --setup first")
    cfg=dict(DEFAULT,**c)
    if not re.fullmatch(r"mobile_app_[a-z0-9_]+",cfg.get("service","")):
        raise ValueError("Invalid notify service")
    if any(type(cfg[k]) is not bool for k in ("progress","shortfall","finished","stalled")) or type(cfg["stall_hours"]) is not int or not 12<=cfg["stall_hours"]<=168:
        raise ValueError("Invalid notification settings")
    return cfg

def poll():
    cfg=settings()
    s=session()
    if s is None:
        return
    old=load(STATE)
    lines,new=evaluate(s,old,cfg,time.time())
    if lines:
        push(cfg["service"],"HaierPi – eksperyment","\n".join(lines))
    if new!=old:
        save(STATE,new)

def setup():
    if os.geteuid()!=0:
        raise ValueError("Run setup as root")
    devices=targets()
    if not devices:
        raise ValueError("No notify.mobile_app service. Register HA Companion app and allow notifications.")
    old=load(CONFIG,{})
    if len(devices)==1:
        service=devices[0]
    else:
        for i,s in enumerate(devices,1):
            print("%d. notify.%s"%(i,s))
        choice=int(input("Numer telefonu: "))
        if not 1<=choice<=len(devices):
            raise ValueError("Invalid choice")
        service=devices[choice-1]
    # Send the real test before installing the monitor. HTTP acceptance is
    # not proof that the phone displayed the push.
    push(service,"HaierPi – TEST","Powiadomienia z HaierPi przez Home Assistant działają. Potwierdź odbiór na telefonie.")
    cfg=dict(DEFAULT,**old)
    cfg["service"]=service
    save(CONFIG,cfg)
    # Baseline the present session to avoid a storm of historical messages.
    s=session()
    if s is not None and load(STATE) is None:
        initial=snapshot(s)
        initial.update(last_progress=time.time(),stall_sent=False,finished=False)
        save(STATE,initial)
    if Path(__file__).resolve()!=SCRIPT:
        atomic(SCRIPT,Path(__file__).read_bytes())
    service_unit="""[Unit]
Description=HaierPi experiment push notifications
After=network-online.target haier.service
[Service]
Type=oneshot
ExecStart=/opt/haier/env/bin/python /opt/haier/haierpi-notify.py --poll
TimeoutStartSec=30
NoNewPrivileges=true
"""
    timer_unit="""[Unit]
Description=Check HaierPi experiment notifications every minute
[Timer]
OnBootSec=60s
OnUnitInactiveSec=60s
AccuracySec=10s
[Install]
WantedBy=timers.target
"""
    for suffix,data in (("service",service_unit),("timer",timer_unit)):
        p=Path("/etc/systemd/system")/(UNIT+"."+suffix)
        if p.is_symlink():
            raise ValueError("Unit path is a symlink")
        atomic(p,data.encode("ascii"))
        p.chmod(0o644)
    subprocess.run(["systemctl","daemon-reload"],check=True)
    subprocess.run(["systemctl","enable","--now",UNIT+".timer"],check=True)
    subprocess.run(["systemctl","is-active",UNIT+".timer"],check=True)
    print("OK: notify."+service+"; monitoring enabled. No HaierPi restart.")

def upgrade():
    """Update an existing installation without reselecting phone/resetting state."""
    if os.geteuid()!=0:
        raise ValueError("Run upgrade as root")
    cfg=settings()
    cfg["progress"]=True
    subprocess.run(["systemctl","stop",UNIT+".timer"],check=True)
    try:
        # Let any in-flight push finish before changing code or configuration.
        deadline=time.monotonic()+35
        while True:
            status=subprocess.check_output(["systemctl","show","-p","ActiveState","--value",UNIT+".service"],text=True).strip()
            if status in ("inactive","failed"):
                break
            if time.monotonic()>=deadline:
                raise RuntimeError("Monitor is still busy")
            time.sleep(.5)
        atomic(SCRIPT,Path(__file__).read_bytes())
        save(CONFIG,cfg)
    finally:
        subprocess.run(["systemctl","start",UNIT+".timer"],check=True)
    print("OK: cycle and configuration notifications enabled; existing state preserved.")

def selftest():
    s={"since":100,"counts":[0]*6,"continuous":[None]*6,"deferred":[None]*6}
    cfg=dict(DEFAULT,progress=True)
    lines,old=evaluate(s,None,cfg,100)
    assert not lines
    s["counts"][0]=1
    lines,old=evaluate(s,old,cfg,150)
    assert len(lines)==1 and "1/3" in lines[0] and "0/6" in lines[0] and "1/18" in lines[0]
    lines,old=evaluate(s,old,cfg,151)
    assert not lines
    s["counts"][0]=3
    lines,old=evaluate(s,old,cfg,200)
    assert len(lines)==1 and "Eco / OFF" in lines[0] and "1/6" in lines[0] and "3/18" in lines[0]
    lines,old=evaluate(s,old,cfg,201)
    assert not lines
    s["deferred"][2]={"at":210,"outdoor":-2}
    lines,old=evaluate(s,old,cfg,210)
    assert len(lines)==1 and "Ochrona komfortu" in lines[0]
    lines,old=evaluate(s,old,cfg,210+48*3600)
    assert len(lines)==1 and "48 h" in lines[0]
    lines,old=evaluate(s,old,cfg,211+48*3600)
    assert not lines
    s["continuous"][1]={}
    lines,old=evaluate(s,old,cfg,215+48*3600)
    assert len(lines)==1 and "próbę ciągłą" in lines[0] and "2/6" in lines[0]
    legacy=dict(old)
    del legacy["continuous"]
    lines,old=evaluate(s,legacy,cfg,216+48*3600)
    assert not lines
    s["counts"]=[3,0,3,3,3,3]
    s["finished"]=True
    lines,old=evaluate(s,old,cfg,220+48*3600)
    assert len(lines)==5 and "6/6" in lines[-1] and "15/18" in lines[-1]
    lines,old=evaluate(s,old,cfg,221+48*3600)
    assert not lines
    print("Self-test OK")

if __name__=="__main__":
    try:
        cmd=sys.argv[1] if len(sys.argv)==2 else ""
        if cmd=="--selftest": selftest()
        elif cmd=="--setup": selftest(); setup()
        elif cmd=="--upgrade": selftest(); upgrade()
        elif cmd=="--poll": poll()
        elif cmd=="--test": push(settings()["service"],"HaierPi – TEST","Test powiadomienia.")
        else: raise ValueError("Use --setup, --upgrade, --poll, --test or --selftest")
    except Exception as e:
        # Never print token, URL, response body or request headers.
        if isinstance(e,(ValueError,RuntimeError)) and not type(e).__module__.startswith("requests"):
            print("ERROR: "+str(e),file=sys.stderr)
        else:
            print("ERROR: "+type(e).__name__,file=sys.stderr)
        sys.exit(1)
