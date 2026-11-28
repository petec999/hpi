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
            "notes":["CPU percentage is relative to one core, not all cores.",
                     "write_bytes is process-attributed kernel I/O, not measured physical SD wear.",
                     "A short sample does not prove or rule out a memory leak. Compare over time.",
                     "Inventory shows apparent file sizes, not allocated blocks. No cleanup performed."]}
    print(json.dumps(result,indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()
