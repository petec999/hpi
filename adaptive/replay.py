"""Offline HA history replay, never connects to a pump or broker.

Usage: python -m adaptive.replay /path/to/aligned.csv
CSV input: UTC timestamp, preset, flimiton, twi, two, heating_curve_value,
compressor_fact, compressor_fset, connected, r141_telemetry_fresh,
r241_telemetry_fresh, heat_demand, pch, ch_heating_active, defrost,
3_way_valve, active_error. One row per 30s.
Missing freshness is rejected unless explicitly enabled for exploratory replay.
No counterfactual claim: we cannot observe the response to an unexecuted proposal.
"""
import argparse
import csv
from collections import Counter, deque
from datetime import datetime
import json
import math
from statistics import median

from adaptive.regulator import Regulator, Sample, LEVELS, adjacent

def on(row,key):
    return row.get(key)=="on"

def num(row,key):
    try:
        return float(row[key])
    except (ValueError,KeyError,TypeError):
        return float("nan")

def fresh(row,exploratory):
    flags=[row.get(k,"") for k in ("r141_telemetry_fresh","r241_telemetry_fresh")]
    if not on(row,"connected"):
        return False
    return all(v=="on" for v in flags) or (exploratory and all(v in ("","nan") for v in flags))

def sample(row,exploratory):
    ts=datetime.fromisoformat(row["timestamp"].replace("Z","+00:00")).timestamp()
    relay=row.get("flimiton")
    mode=row.get("preset") if relay in ("on","off") else "unknown"
    return Sample(ts,num(row,"heating_curve_value"),num(row,"twi"),num(row,"two"),
                  num(row,"compressor_fact"),num(row,"compressor_fset"),mode,relay=="on",
                  all(on(row,k) for k in ("heat_demand","pch","ch_heating_active")),
                  row.get("defrost")!="off",fresh(row,exploratory),
                  num(row,"active_error"),row.get("3_way_valve")!="CH")

def replay(rows,exploratory=False):
    reg=Regulator()
    counts=Counter()
    history=deque()
    events=[]
    previous=None
    for row in rows:
        s=sample(row,exploratory)
        if previous and s.now<=previous.now:
            raise ValueError("History must be strictly chronological")
        d=reg.step(s)
        counts["samples"]+=1
        counts["freshness_eligible"]+=int(s.fresh)
        counts[d.risk]+=1
        if d.current is not None and d.proposed!=d.current:
            counts["proposal_samples"]+=1
            if d.proposed==adjacent(d.current,"down"):
                counts["reduce_samples"]+=1
            else:
                counts["increase_or_restore_samples"]+=1
        # Candidate stop: active CO, demand stays on, no defrost, fresh
        # on both sides, actual frequency goes to zero. CH active may turn off.
        if previous and 0<s.now-previous.now<=65 and previous.hz>0 and s.hz==0:
            eligible=(previous.fresh and s.fresh and previous.heating and
                on(row,"heat_demand") and on(row,"pch") and not s.defrost and
                not previous.defrost and not s.dhw and not previous.dhw and
                s.error==0 and previous.error==0 and previous.mode==s.mode and
                previous.relay==s.relay and abs(previous.target-s.target)<0.25)
            if eligible and len(history)>=10:
                recent=[(p,q) for p,q in history if 0<s.now-p.now<=900]
                pre5=[(p,q) for p,q in recent if s.now-p.now<=300]
                valid=lambda p: p.fresh and p.heating and p.hz>0 and not p.defrost and not p.dhw and p.error==0 and p.mode==previous.mode and p.relay==previous.relay and abs(p.target-previous.target)<0.25
                if len(pre5)>=10 and all(valid(p) for p,q in pre5):
                    proposals=[p.now for p,q in recent if valid(p) and q.current is not None and q.proposed!=q.current and q.proposed==adjacent(q.current,"down")]
                    level=LEVELS.index((previous.mode,previous.relay)) if (previous.mode,previous.relay) in LEVELS else None
                    events.append({"timestamp":row["timestamp"],"mode":previous.mode,"relay":previous.relay,
                        "at_minimum":level==0,"supply_surplus":round(previous.supply_temp-previous.target,2),
                        "reduce_proposal_lead_seconds":round(s.now-min(proposals)) if proposals else None,
                        "freshness_confirmed":not exploratory or all(on(row,k) for k in ("r141_telemetry_fresh","r241_telemetry_fresh"))})
        history.append((s,d))
        while history and s.now-history[0][0]>900:
            history.popleft()
        previous=s
    nonminimum=[e for e in events if not e["at_minimum"]]
    lead=[e["reduce_proposal_lead_seconds"] for e in nonminimum if e["reduce_proposal_lead_seconds"] is not None]
    return {"counts":dict(counts),"candidate_stops":len(events),
            "stops_at_minimum":sum(e["at_minimum"] for e in events),
            "other_stops":len(nonminimum),"other_stops_with_prior_reduce_proposal":len(lead),
            "median_lead_seconds":median(lead) if lead else None,
            "exploratory_missing_freshness":exploratory,
            "events":events,
            "note":"Observed history only; proposals were not executed. Missing service/override history is a limitation."}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv")
    p.add_argument("--exploratory-missing-freshness",action="store_true")
    args=p.parse_args()
    with open(args.csv,newline="",encoding="utf-8") as f:
        print(json.dumps(replay(csv.DictReader(f),args.exploratory_missing_freshness),indent=2,allow_nan=False))

if __name__=="__main__":
    main()
