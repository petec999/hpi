"""Foreground, read-only shadow observer: journal snapshots plus MQTT freshness.

Never publishes MQTT, writes GPIO, invokes HaierPi controls, or changes config.
The source availability flags have Stable's 180-second freshness granularity.
They do not provide per-frame timestamps or a confirmed setpoint readback.
"""
import argparse
import json
import math
import queue
import re
import subprocess
import threading
from collections import deque
from statistics import median
import time
from pathlib import Path

from adaptive.regulator import Regulator, Sample, LEVELS
from diagnostics.derive_mqtt_env import derive

MARK="status_snapshot: "
MAX_AGE=45
MAX_HEARTBEAT_AGE=90

def number(value):
    if isinstance(value,bool):
        raise ValueError("boolean is not numeric telemetry")
    v=float(value)
    if not math.isfinite(v):
        raise ValueError("nonfinite telemetry")
    return v

def flag(value):
    if value in (True,1,"1","on","ON"):
        return True
    if value in (False,0,"0","off","OFF"):
        return False
    raise ValueError("unknown boolean state")

def decode(record, now, fresh, wall):
    # journalctl -b restricts entries to this boot. Reject old/delayed entries.
    age=wall-number(record["__REALTIME_TIMESTAMP"])/1e6
    if not 0<=age<=MAX_AGE:
        raise ValueError("stale journal entry")
    message=record["MESSAGE"]
    if not isinstance(message,str) or MARK not in message:
        return None
    data=json.loads(message.split(MARK,1)[1])
    ci=data["compinfo"]
    water=data["twitwo"]
    mode=str(data["mode"]).strip().lower()
    if mode not in ("quiet","eco","turbo"):
        raise ValueError("unknown preset")
    threeway=str(data["threeway"]).strip().upper()
    if threeway not in ("CH","DHW"):
        raise ValueError("unknown valve state")
    error=number(data["error"])
    if error!=int(error):
        raise ValueError("invalid error code")
    # Do not assume service/anti-freeze states are inactive when missing.
    override=any(flag(data[key]) for key in
                 ("service_set_pump","service_set_heater","antifreeze","antifreeze_custom",
                  "anti_legionella_active","ch_cooling"))
    relay=flag(data["flimiton"])
    if relay!=flag(data["flrelay"]):
        raise ValueError("conflicting relay readback")
    s=Sample(now=now,target=number(data["hcurve"]),return_temp=number(water[0]),
             supply_temp=number(water[1]),hz=number(ci[1]),requested_hz=number(ci[0]),
             mode=mode,relay=relay,heating=flag(data["pch"]) and flag(data["heatdemand"]) and flag(data["ch_heating"]),
             defrost=flag(data["defrost"]),fresh=fresh,error=int(error),dhw=threeway=="DHW",override=override)
    return s,data

class Availability:
    def __init__(self):
        self.lock=threading.Lock()
        self.states=dict.fromkeys(("connected","r141_fresh","r241_fresh"),False)
        self.last_live=None
        self.generation=0

    def reset(self):
        with self.lock:
            self.states=dict.fromkeys(self.states,False)
            self.last_live=None
            self.generation+=1

    def update(self,key,payload,retained,now):
        with self.lock:
            value=payload.strip().lower()=="online"
            if not value and self.states[key]:
                self.generation+=1
            self.states[key]=value
            if key=="connected":
                if not value:
                    self.last_live=None
                elif not retained:
                    self.last_live=now

    def status(self,now):
        with self.lock:
            fresh=all(self.states.values()) and self.last_live is not None and 0<=now-self.last_live<=MAX_HEARTBEAT_AGE
            return fresh,self.generation,dict(self.states)

class Observation:
    """Measure all six combinations; never infer their capacity ordering."""
    def __init__(self):
        self.history=deque()
        self.context=None

    def reset(self):
        self.history.clear()
        self.context=None

    def update(self,s):
        if not (s.fresh and s.heating and s.hz>0 and not s.defrost and
                not s.dhw and not s.override and s.error==0):
            self.reset()
            return {}
        context=(s.mode,s.relay,s.target)
        if context!=self.context or (self.history and
                not 0<s.now-self.history[-1][0]<=65):
            self.reset()
        self.context=context
        self.history.append((s.now,s.target-s.return_temp,s.target-s.supply_temp,s.hz))
        while self.history and s.now-self.history[0][0]>300:
            self.history.popleft()
        h=list(self.history)
        result={"return_deficit":round(h[-1][1],2),"supply_deficit":round(h[-1][2],2),
                "water_delta":round(s.supply_temp-s.return_temp,2),
                "observed_seconds":round(h[-1][0]-h[0][0]),
                "median_hz":median(x[3] for x in h),"return_trend_k_min":None}
        if len(h)>=3 and h[-1][0]-h[0][0]>=90:
            n=len(h)//2
            first,last=h[:n],h[n:]
            dt=median(x[0] for x in last)-median(x[0] for x in first)
            if dt>0:
                result["return_trend_k_min"]=round((median(x[1] for x in last)-median(x[1] for x in first))*60/dt,3)
        return result

def describe(s,data,d,states,observed=None):
    label=lambda x: None if x is None else LEVELS[x][0]+("+FLimit" if LEVELS[x][1] else "")
    return dict(actual=s.mode+("+FLimit" if s.relay else ""),
                proposed=label(d.proposed),reason=d.reason,target=s.target,
                twi=s.return_temp,two=s.supply_temp,hz=s.hz,fset=s.requested_hz,
                delta=d.delta,trend_k_min=None if d.trend is None else round(d.trend,3),
                fresh=s.fresh,availability=states,zone=data.get("tempzone"),
                legacy_antionoff=data.get("antionoff"),control="shadow",
                risk=d.risk,supply_error=d.supply_error,
                supply_trend_k_min=None if d.supply_trend is None else round(d.supply_trend,3),
                predicted_surplus=d.predicted_surplus,prediction_basis="Twi",deficit_k_min=round(d.deficit_integral,2),
                retry_block_seconds=round(d.blocked_seconds),observation=observed or {})

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",default="/opt/config.ini")
    args=p.parse_args()
    import paho.mqtt.client as mqtt
    cfg=derive(args.config)
    base=cfg["HPI_TOPIC"].rstrip("/")+"/haierpi/"
    a=Availability()
    c=mqtt.Client(client_id="")  # broker-assigned / unique; never reuse core ID
    if cfg["HPI_MQTT_USERNAME"]:
        c.username_pw_set(cfg["HPI_MQTT_USERNAME"],cfg["HPI_MQTT_PASSWORD"])
    def connected(cl,ud,flags,rc):
        a.reset()
        if rc==0:
            for key in a.states:
                cl.subscribe(base+key,qos=1)
    def disconnected(cl,ud,rc):
        a.reset()
    def message(cl,ud,msg):
        key=msg.topic[len(base):] if msg.topic.startswith(base) else ""
        if key in a.states:
            try:
                a.update(key,msg.payload.decode("utf-8"),bool(msg.retain),time.monotonic())
            except UnicodeError:
                a.reset()
    c.on_connect=connected
    c.on_disconnect=disconnected
    c.on_message=message
    c.reconnect_delay_set(1,30)
    c.connect_async(cfg["HPI_MQTT_HOST"],int(cfg["HPI_MQTT_PORT"]),60)
    c.loop_start()
    proc=None
    try:
        proc=subprocess.Popen(["journalctl","-b","-u","haier","-n","0","-f","-o","json","--no-pager"],
                              stdout=subprocess.PIPE,text=True,bufsize=1)
        q=queue.Queue(maxsize=128)
        def read():
            for line in proc.stdout:
                if MARK not in line:
                    continue
                try:
                    q.put_nowait(line)
                except queue.Full:
                    a.reset()  # dropped data => restart policy history
        threading.Thread(target=read,daemon=True).start()
        r=Regulator()
        obs=Observation()
        generation=None
        invocation=None
        last_snapshot=time.monotonic()
        print("Shadow only; waiting for new snapshots and live MQTT availability.",flush=True)
        while True:
            try:
                line=q.get(timeout=10)
            except queue.Empty:
                if proc.poll() is not None:
                    raise RuntimeError("journalctl exited")
                if time.monotonic()-last_snapshot>MAX_AGE:
                    r.reset()
                    obs.reset()
                    print("SHADOW paused: no recent snapshot",flush=True)
                    last_snapshot=time.monotonic()
                continue
            try:
                now=time.monotonic()
                record=json.loads(line)
                identity=(record.get("_SYSTEMD_INVOCATION_ID"),record.get("_PID"))
                if not identity[1]:
                    raise ValueError("missing source process")
                fresh,gen,states=a.status(now)
                if generation!=gen or invocation!=identity:
                    r=Regulator()
                    obs.reset()
                    generation=gen
                    invocation=identity
                parsed=decode(record,now,fresh,time.time())
                if parsed is None:
                    continue
                s,data=parsed
                d=r.step(s,control="shadow")
                print(json.dumps(describe(s,data,d,states,obs.update(s)),allow_nan=False),flush=True)
                last_snapshot=now
            except (ValueError,KeyError,TypeError,IndexError,OverflowError):
                r=Regulator()
                obs.reset()
                print("SHADOW paused: invalid or stale snapshot",flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        c.disconnect()
        c.loop_stop()

if __name__=="__main__":
    main()
