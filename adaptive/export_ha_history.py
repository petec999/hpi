#!/usr/bin/env python3
"""Export HaierPi entity history via read-only HA REST API, in bounded batches."""
import argparse
import configparser
from datetime import datetime, timedelta, timezone
import gzip
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urlencode, quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

ENTITY=re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
DOMAINS={"sensor","binary_sensor","switch","select","number","climate","input_number","input_select","input_boolean"}

def discover(states,ha,extra):
    chosen={}
    configured={ha.get(k,"").strip().lower() for k in ("insidesensor","outsidesensor","humiditysensor")}
    explicit=set(extra)|{x for x in configured if ENTITY.fullmatch(x)}
    for row in states:
        eid=row.get("entity_id","")
        attrs=row.get("attributes",{})
        name=str(attrs.get("friendly_name",""))
        if not ENTITY.fullmatch(eid):
            continue
        match=re.search(r"haier[ _-]*pi|pompa[ _-]*ciep[łl]a",eid+" "+name,re.I)
        if eid in explicit or (match and eid.split(".")[0] in DOMAINS):
            chosen[eid]={"name":name,"unit":attrs.get("unit_of_measurement")}
    missing=set(extra)-set(chosen)
    if missing:
        raise ValueError("Extra entities not found: "+", ".join(sorted(missing)))
    return chosen

def base_url(ha):
    base=ha.get("HAADDR","").strip().rstrip("/")
    port=ha.get("HAPORT","").strip()
    if "://" not in base:
        base="http://"+base
    parts=urlsplit(base)
    if parts.scheme not in ("http","https") or not parts.hostname or parts.username or parts.password or parts.path or parts.query or parts.fragment:
        raise ValueError("Invalid HA address")
    if port:
        if not port.isdecimal() or not 1<=int(port)<=65535:
            raise ValueError("Invalid HA port")
        if parts.port is None:
            base+=":"+port
        elif parts.port!=int(port):
            raise ValueError("Conflicting HA ports")
    return base

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days",type=int,default=30)
    p.add_argument("--config",default="/opt/config.ini")
    p.add_argument("--output",default="/tmp/haier-history.json.gz")
    p.add_argument("--extra",action="append",default=[])
    p.add_argument("--list",action="store_true")
    args=p.parse_args()
    if not 1<=args.days<=90:
        p.error("days must be between 1 and 90")
    cfg=configparser.ConfigParser(interpolation=None)
    if not cfg.read(args.config,encoding="utf-8"):
        raise ValueError("Cannot read HaierPi configuration")
    ha=cfg["HOMEASSISTANT"]
    base=base_url(ha)
    token=ha.get("KEY","").strip()
    if not token:
        raise ValueError("Missing HA token in existing configuration")
    opener=build_opener(NoRedirect())
    def get(path):
        for attempt in range(3):
            try:
                request=Request(base+path,headers={"Authorization":"Bearer "+token,"Accept":"application/json"},method="GET")
                with opener.open(request,timeout=120) as response:
                    return json.load(response)
            except HTTPError as e:
                if e.code not in (429,500,502,503,504) or attempt==2:
                    raise RuntimeError("HA API HTTP "+str(e.code)) from None
            except (URLError,TimeoutError):
                if attempt==2:
                    raise RuntimeError("HA API connection failed") from None
            time.sleep(2**attempt)
    entities=discover(get("/api/states"),ha,args.extra)
    if not entities:
        raise ValueError("No matching HaierPi entities; use --extra ENTITY")
    ids=sorted(entities)
    print("Selected entities:",len(ids),flush=True)
    for eid in ids:
        print(" ",eid,flush=True)
    if args.list:
        return
    end=datetime.now(timezone.utc)
    start=end-timedelta(days=args.days)
    target=Path(args.output)
    fd,tmp=tempfile.mkstemp(prefix=".haier-history-",dir=target.parent)
    os.close(fd)
    count=0
    days_with_data=0
    try:
        with gzip.open(tmp,"wt",encoding="utf-8",compresslevel=5) as out:
            out.write(json.dumps({"type":"metadata","format":"haier-history-jsonl-v1","start":start.isoformat(),"end":end.isoformat(),"entities":entities,"notes":"Recorder state history, not a uniform sampling grid. Initial states at chunk boundaries may repeat."},ensure_ascii=False)+"\n")
            a=start
            while a<end:
                b=min(a+timedelta(days=1),end)
                daily=0
                for i in range(0,len(ids),12):
                    group=ids[i:i+12]
                    params=urlencode({"filter_entity_id":",".join(group),"end_time":b.isoformat(),"minimal_response":"","no_attributes":"","significant_changes_only":"0"})
                    data=get("/api/history/period/"+quote(a.isoformat(),safe="")+"?"+params)
                    if not isinstance(data,list):
                        raise ValueError("Unexpected history response")
                    for series in data:
                        if not series:
                            continue
                        eid=series[0].get("entity_id")
                        if eid not in group:
                            raise ValueError("Unexpected history entity")
                        # Do not export attributes or context IDs.
                        values=[{k:row[k] for k in ("state","last_changed","last_updated") if k in row} for row in series]
                        out.write(json.dumps({"type":"history","entity_id":eid,"start":a.isoformat(),"end":b.isoformat(),"states":values},ensure_ascii=False,separators=(",",":"))+"\n")
                        daily+=len(values)
                    time.sleep(0.15)
                count+=daily
                days_with_data+=int(daily>0)
                print(a.date(),"records:",daily,"total:",count,flush=True)
                a=b
            out.write(json.dumps({"type":"summary","records":count,"nonempty_day_chunks":days_with_data})+"\n")
        if not count:
            raise ValueError("No recorded history returned")
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print("Export complete:",target,"bytes:",target.stat().st_size,flush=True)

if __name__=="__main__":
    try:
        main()
    except (ValueError,KeyError,RuntimeError,OSError) as exc:
        print("ERROR:",exc,file=sys.stderr)
        sys.exit(1)
