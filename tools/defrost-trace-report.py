#!/usr/bin/env python3
"""Read saved passive defrost traces and export CSV. Run with HaierPi Python."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import PyHaier

def optional(name,frame):
    try:
        return getattr(PyHaier,name)(frame)
    except (AttributeError,TypeError,ValueError,IndexError):
        return None

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path",type=Path,default=Path("/opt/haier/.adaptive-defrost-trace-v1.json"))
    args=parser.parse_args()
    if args.path.is_symlink() or args.path.stat().st_size>2*1024*1024:
        parser.error("invalid trace file")
    data=json.loads(args.path.read_text())
    if data["schema"]!=1:
        parser.error("unknown trace schema")
    out=csv.writer(sys.stdout,delimiter=";")
    out.writerow(["cycle","completion","time_utc","relative_s","target","twi","two","twi_minus_two",
                  "tao","tdef","fact","fset","defrost","heater_A4A","command_A04",
                  "R156_bit4","R156_bit11","R150H","R151H","R144H"])
    for t in data["traces"]:
        for stamp,a,b,c in t["samples"]:
            twi,two=PyHaier.GetTwiTwo(b)
            out.writerow([datetime.fromtimestamp(t["start"],timezone.utc).isoformat(),t["reason"],
                          datetime.fromtimestamp(stamp,timezone.utc).isoformat(),round(stamp-t["start"],3),
                          PyHaier.GetCHTemp(a),twi,two,round(twi-two,2),optional("GetTao",c),optional("GetTdef",c),
                          c[2]&255,c[3]>>8,int(bool(b[0]&0x2000)),int(bool(b[3]&0x100)),
                          int(bool(a[0]&8)),int(bool(b[15]&16)),int(bool(b[15]&2048)),b[9]>>8,b[10]>>8,b[3]>>8])

if __name__=="__main__":
    main()
