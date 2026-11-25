#!/usr/bin/env python3
"""Read-only inspection of KamiloStatek's pinned HaierPi stable release.

Usage: python3 tools/inspect_stable_145.py PATH_TO_STABLE_TAR [PATH_TO_ALPHA13_TAR]
Never modifies or extracts into an installed HaierPi.
"""
import ast
from collections import Counter
from pathlib import Path
import difflib
import hashlib
import sys
import tarfile

EXPECTED_SHA256 = "ca803a3f8777efa75a40739d2efeb0362365ffa4291d3eb76d9a231c6cb53976"
U2 = ("GetTao.py","GetTdef.py","GetTdTs.py","GetTSatPd.py","GetTSatPs.py","GetThiTho.py")

def contents(path):
    with tarfile.open(path,"r:gz") as tf:
        entries={}
        for m in tf.getmembers():
            n=m.name.removeprefix("./")
            if m.issym() or m.islnk() or m.isdev():
                raise ValueError("Unsafe special archive member: "+m.name)
            if n.startswith("/") or ".." in Path(n).parts:
                raise ValueError("Unsafe archive path: "+m.name)
            if m.isfile():
                if n in entries: raise ValueError("Duplicate "+n)
                entries[n]=tf.extractfile(m).read()
        return entries

def main():
    stable=Path(sys.argv[1])
    digest=hashlib.sha256(stable.read_bytes()).hexdigest()
    print("UPSTREAM_STABLE_SHA256", digest)
    if digest!=EXPECTED_SHA256: raise SystemExit("UPSTREAM HASH MISMATCH")
    s=contents(stable)
    a=contents(Path(sys.argv[2])) if len(sys.argv)>2 else {}
    print("STABLE_FILE_COUNT",len(s),"ALPHA_FILE_COUNT",len(a))
    print("STABLE_TOP_LEVEL",sorted(set(p.split("/")[0] for p in s)))
    main=s.get("main.py",b"").decode()
    ast.parse(main,filename="stable/main.py")
    checks={
        "stable_version": 'version="1.4.5"' in main,
        "freshness_tick": "def mqtt_pump_freshness_tick():" in main,
        "r141_fresh_topic": "/haierpi/r141_fresh" in main,
        "r241_fresh_topic": "/haierpi/r241_fresh" in main,
        "mqtt_r141_fresh": "HaierPi_R141Fresh" in main,
        "mqtt_r241_fresh": "HaierPi_R241Fresh" in main,
        "compressor_fact_template_correct": '''"HaierPi_Compfact", "Hz", "frequency", "measurement", "{{ value_json[1] | float }}"''' in main,
        "compressor_set_template_correct": '''"HaierPi_Compfset", "Hz", "frequency", "measurement", "{{ value_json[0] | float }}"''' in main,
        "superheat_signed": 'superheat = f"{Ts - TsatPs_act:.1f}"' in main,
        "subcooling_signed": 'subcooling = f"{TsatPd_act - Thi:.1f}"' in main,
        "old_superheat_abs_absent": 'abs(Ts - TsatPs_act)' not in main,
        "old_subcool_abs_absent": 'abs(TsatPd_act - Thi)' not in main,
        "legacy_cleanup": "HaierPi_CH_daily_kWh" in main and "_clear(" in main,
        "old_alpha_label_absent": "alpha13" not in main.lower(),
        "raw_rs485_t141": "R141=T141" in main,
        "raw_rs485_t241": "R241=T241" in main,
    }
    print("FEATURE_CHECKS",checks)
    print("DISCOVERY_CLEANUP_CONTEXT")
    lines = main.splitlines()
    for phrase in ("HaierPi_DHWSet", "HaierPi_Pd", "HaierPi_CH_daily_kWh", "HaierPi_DeltaTempEco", "def cleanup_"):
        for pos in [i for i, line in enumerate(lines) if phrase in line][:2]:
            print("DISCOVERY_MATCH", repr(phrase), "line", pos+1,
                  repr(lines[max(0,pos-1):pos+2])[:550])
    for k,v in checks.items():
        if not v: print("VERIFY_MANUALLY",k)
    for name in U2:
        arr=[(p,b) for p,b in s.items() if p.endswith("/PyHaier/"+name)]
        if len(arr)!=1: raise ValueError("Missing or duplicate "+name)
        raw=arr[0][1]
        ast.parse(raw,filename=name)
        print("U2",name, "old_4095",raw.count(b"-= 4095"),"new_4096",raw.count(b"-= 4096"))
    if a:
        different=[x for x in sorted(set(s)|set(a)) if s.get(x)!=a.get(x)]
        print("DIFF_FILE_COUNT",len(different))
        print("DIFF_FILE_PATHS",different[:90])
        for name in ["main.py"]:
            if name in a:
                da=a[name].decode().splitlines()
                ds=main.splitlines()
                print("SOURCE_LINES",name,"alpha",len(da),"stable",len(ds))
                # No hundreds-of-KB diffs in build logs.
                h=list(difflib.unified_diff(da,ds,fromfile="alpha13/"+name,tofile="stable/"+name,n=1))
                print("MAIN_DIFF_LINE_COUNT",len(h))
                print("MAIN_DIFF_FIRST_120_LINES")
                print("\n".join(h[:120]))
    print("INSPECTION COMPLETE")

if __name__=="__main__":
    main()
