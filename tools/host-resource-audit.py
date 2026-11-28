#!/usr/bin/env python3
"""Read-only Linux HaierPi resource audit. No credentials, writes, bus or API calls."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

def kv(path):
    out={}
    for line in path.read_text().splitlines():
        key,sep,value=line.partition(":")
        if sep:
            fields=value.split()
            if fields and fields[0].isdigit():
                out[key]=int(fields[0])*(1024 if len(fields)>1 and fields[1]=="kB" else 1)
    return out

def snapshot(pid,proc=Path("/proc")):
    p=proc/str(pid)
    fields=(p/"stat").read_text().rsplit(")",1)[1].split()
    status=kv(p/"status")
    io=kv(p/"io")
    return dict(at=time.monotonic(),start_ticks=int(fields[19]),
                cpu_ticks=int(fields[11])+int(fields[12]),
                rss_bytes=status.get("VmRSS"),rss_peak_bytes=status.get("VmHWM"),
                threads=status.get("Threads"),fds=len(list((p/"fd").iterdir())),
                write_bytes=io.get("write_bytes"),read_bytes=io.get("read_bytes"),
                logical_write_bytes=io.get("wchar"),
                voluntary_switches=status.get("voluntary_ctxt_switches"),
                involuntary_switches=status.get("nonvoluntary_ctxt_switches"))

def difference(a,b,hz):
    dt=b["at"]-a["at"]
    if a["start_ticks"]!=b["start_ticks"] or dt<=0:
        raise ValueError("process changed during sample")
    result={"seconds":round(dt,2)}
    for k in ("cpu_ticks","write_bytes","read_bytes","logical_write_bytes",
              "voluntary_switches","involuntary_switches"):
        x,y=a.get(k),b.get(k)
        result[k+"_delta"]=y-x if x is not None and y is not None and y>=x else None
    d=result["cpu_ticks_delta"]
    result["cpu_pct_one_core"]=round(100*d/hz/dt,2) if d is not None else None
    for k in ("rss_bytes","threads","fds"):
        x,y=a.get(k),b.get(k)
        result[k+"_delta"]=y-x if x is not None and y is not None else None
    return result

def inventory(root):
    groups={}
    # Metadata only, never follow directory or file symlinks.
    for p in root.iterdir():
        name=p.name
        if name.startswith(".adaptive-"):
            group="adaptive_state"
        elif name=="charts.pkl":
            group="charts"
        elif name.startswith("crashlog-"):
            group="crash_logs"
        elif name.startswith(".before-") or ".before-" in name:
            group="upgrade_rollback"
        elif name==".hpi-backups":
            group="daily_backup"
        else:
            continue
        row=groups.setdefault(group,{"files":0,"bytes":0,"directories":0,"unreadable":0})
        stack=[p]
        visited=0
        while stack and visited<10000:
            q=stack.pop()
            visited+=1
            try:
                st=q.lstat()
                if stat.S_ISREG(st.st_mode):
                    row["files"]+=1
                    row["bytes"]+=st.st_size
                elif stat.S_ISDIR(st.st_mode):
                    row["directories"]+=1
                    # Bound even the pending traversal list.
                    with os.scandir(q) as entries:
                        for e in entries:
                            if len(stack)+visited>=10000:
                                row["truncated"]=True
                                break
                            stack.append(Path(e.path))
            except OSError:
                row["unreadable"]+=1
        if stack:
            row["truncated"]=True
    return groups

def register_evidence(path):
    """Summarize only already retained passive candidate changes, not decoding."""
    masks={144:0xfe00,150:0xff00,151:0xff00,155:0x001f,156:0xffff}
    try:
        if path.is_symlink() or path.stat().st_size>512*1024:
            raise ValueError("invalid register history")
        with path.open("rb") as f:
            raw=f.read(512*1024+1)
        if len(raw)>512*1024:
            raise ValueError("oversized register history")
        data=json.loads(raw)
        events=data["events"]
        if data["schema"]!=1 or not isinstance(events,list) or len(events)>256:
            raise ValueError("invalid register history")
        counts={}
        pairs=0
        for e in events:
            before,after=e["before"],e["after"]
            if before is None:
                continue
            old,new=before["R141"],after["R141"]
            if len(old)!=16 or len(new)!=16 or any(type(v) is not int or not 0<=v<=65535 for v in old+new):
                raise ValueError("invalid R141")
            flags=e["flags"]
            known=("heater_command","heater_readback","valve_dhw","valve_ch","pdhw",
                   "dhw_heating","dhw_heater_assist_active","anti_legionella_active","dhw_enabled")
            if not isinstance(flags,list) or any(x not in known for x in flags):
                raise ValueError("invalid flags")
            pairs+=1
            for reg,mask in masks.items():
                a,b=old[reg-141],new[reg-141]
                change=(a^b)&mask
                for bit in range(16):
                    if change&(1<<bit):
                        row=counts.setdefault((reg,bit),{"register":reg,"bit":bit,"rising":0,"falling":0,
                            "with_known_edge":0,"known_edges":{}})
                        row["rising" if b&(1<<bit) else "falling"]+=1
                        if flags:
                            row["with_known_edge"]+=1
                        for flag in set(flags):
                            row["known_edges"][flag]=row["known_edges"].get(flag,0)+1
        return {"retained_events":len(events),"valid_pairs":pairs,
                "candidates":sorted(counts.values(),key=lambda x:(-(x["rising"]+x["falling"]),x["register"],x["bit"])),
                "note":"Selected event pairs only; association is not a decoded signal, causation or duty cycle."}
    except FileNotFoundError:
        return {"available":False,"reason":"no saved register history"}
    except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError):
        return {"available":False,"reason":"invalid or unreadable register history"}

def service():
    keys=("MainPID","NRestarts","ActiveState","SubState")
    command=["systemctl","show","haier.service"]+["--property="+k for k in keys]
    raw=subprocess.run(command,capture_output=True,text=True,timeout=10,check=True).stdout
    return dict(line.split("=",1) for line in raw.splitlines() if "=" in line)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds",type=int,default=60,choices=range(5,601),metavar="5..600")
    parser.add_argument("--root",type=Path,default=Path("/opt/haier"))
    args=parser.parse_args()
    state=service()
    pid=int(state["MainPID"])
    if pid<=0 or state.get("ActiveState")!="active":
        parser.error("haier.service not active")
    a=snapshot(pid)
    print("Sampling active service for %d s; no restart or writes."%args.seconds,flush=True)
    time.sleep(args.seconds)
    b=snapshot(pid)
    after=service()
    if after.get("MainPID")!=str(pid) or after.get("NRestarts")!=state.get("NRestarts"):
        parser.error("service restarted during observation; repeat")
    disk=shutil.disk_usage(args.root)
    mem=kv(Path("/proc/meminfo"))
    result={"service":after,"process":{k:v for k,v in b.items() if k not in ("at","start_ticks")},
            "interval":difference(a,b,os.sysconf("SC_CLK_TCK")),
            "host_memory":{k:mem.get(k) for k in ("MemTotal","MemAvailable","SwapTotal","SwapFree")},
            "disk":{"total_bytes":disk.total,"free_bytes":disk.free},
            "files":inventory(args.root),
            "register_evidence":register_evidence(args.root/".adaptive-register-watch-v1.json"),
            "notes":["CPU percentage is relative to one core, not all cores.",
                     "write_bytes is process-attributed kernel I/O, not measured physical SD wear.",
                     "A short sample does not prove or rule out a memory leak. Compare over time.",
                     "Inventory shows apparent file sizes, not allocated blocks. No cleanup performed."]}
    print(json.dumps(result,indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()
