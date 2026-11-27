"""Optional read-only energy accounting. No actuator calls, no periodic disk writes."""
import json
import math
import os
import re
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from collections import deque

DEFAULT={"enabled":False,"source":"ha","energy":"","energy_unit":"kWh",
         "power":"","power_unit":"W","flow_source":"none","flow":"",
         "flow_unit":"m3/h","manual_flow":0.0,"interval":30}
FIELDS=("energy","power","flow")
FACTORS={"energy":{"kWh":1,"Wh":.001},"power":{"W":.001,"kW":1},
         "flow":{"m3/h":1,"l/min":.06,"l/h":.001}}
MAX_READ_AGE=180

def validate(data):
    if not isinstance(data,dict) or set(data)!=set(DEFAULT):
        raise ValueError("Invalid configuration")
    d=dict(data)
    if type(d["enabled"]) is not bool or d["source"] not in ("ha","mqtt") or d["flow_source"] not in ("none","manual","ha","mqtt"):
        raise ValueError("Invalid source")
    if type(d["interval"]) is not int or d["interval"] not in (30,60):
        raise ValueError("Invalid interval")
    for field in FIELDS:
        unit=d[field+"_unit"]
        if unit not in FACTORS[field]:
            raise ValueError("Invalid unit")
        v=d[field]
        if not isinstance(v,str) or len(v)>180:
            raise ValueError("Invalid entity/topic")
        d[field]=v.strip()
        source=d["flow_source"] if field=="flow" else d["source"]
        if d[field] and source=="ha" and not re.fullmatch(r"sensor\.[a-z0-9_]+",d[field]):
            raise ValueError("Invalid HA entity")
        if d[field] and source=="mqtt" and (not re.fullmatch(r"[A-Za-z0-9_./:-]+",d[field]) or d[field].startswith("$")):
            raise ValueError("Invalid MQTT topic")
    v=d["manual_flow"]
    if type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=30:
        raise ValueError("Invalid manual flow")
    if d["enabled"] and not d["energy"] and not d["power"]:
        raise ValueError("Specify energy or power")
    if d["enabled"] and d["flow_source"]=="manual" and v<=0:
        raise ValueError("Specify manual flow")
    if d["enabled"] and d["flow_source"] in ("ha","mqtt") and not d["flow"]:
        raise ValueError("Specify flow sensor")
    return d

def convert(field,value,unit):
    if isinstance(value,bool):
        raise ValueError("Invalid value")
    v=float(value)*FACTORS[field][unit]
    maximum={"energy":1e9,"power":100,"flow":30}[field]
    if not math.isfinite(v) or not 0<=v<=maximum:
        raise ValueError("Value out of range")
    return v

class EnergyMonitor:
    def __init__(self,g,path=None):
        self.g=g
        self.path=Path(path) if path else None
        self.lock=threading.RLock()
        self.sync_lock=threading.Lock()
        self.cfg=dict(DEFAULT)
        self.generation=0
        self.busy=False
        self.last_poll=None
        self.last=None
        self.current={}
        self.current_at=None
        self.error=None
        self.mqtt_values={}
        self.subscribed=set()
        self.client=None
        self.rows=deque(maxlen=2881)
        self.session=None
        self.experiment={}
        self.cycle_path=self.path.with_name('.adaptive-energy-cycles-v1.json') if self.path else None
        self.cycle_session=None
        self.cycles={}
        self.cycle_error=None
        try:
            if self.path and self.path.exists():
                if self.path.is_symlink() or self.path.stat().st_size>4096:
                    raise ValueError("Invalid file")
                self.cfg=validate(json.loads(self.path.read_text()))
        except (OSError,ValueError,TypeError):
            self.error="Nie można odczytać ustawień energii"
        self.load_cycles()

    def mqtt_topics(self,cfg):
        return {cfg[k] for k in FIELDS if cfg["enabled"] and cfg[k] and
                (cfg["flow_source"] if k=="flow" else cfg["source"])=="mqtt"}

    def check_topics(self,cfg):
        base=str(self.g.get("mqtt_topic","")).strip("/")
        prefix=str(self.g.get("ha_mqtt_discovery_prefix","homeassistant")).strip("/")
        for topic in self.mqtt_topics(cfg):
            t=topic.strip("/")
            if any(t==p or t.startswith(p+"/") for p in (base,prefix,"hass") if p):
                raise ValueError("Use external measurement topics, not control topics")

    def settings(self):
        with self.lock:
            return dict(self.cfg)

    def save(self,data):
        d=validate(data)
        self.check_topics(d)
        with self.lock:
            if d==self.cfg:
                return
            if self.path:
                if self.path.is_symlink():
                    raise ValueError("Invalid config path")
                fd,tmp=tempfile.mkstemp(prefix=".energy-",dir=self.path.parent)
                try:
                    with os.fdopen(fd,"w",encoding="utf-8") as f:
                        json.dump(d,f,allow_nan=False)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp,self.path)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            self.cfg=d
            self.generation+=1
            self.last_poll=self.last=None
            self.current={}
            self.current_at=None
            self.error=None
            self.mqtt_values={}
            self.rows.clear()
            self.session=None
            self.experiment={}
            self.cycle_session=None
            self.cycles={}
            self.cycle_error=None

    def mqtt_connect(self,client):
        with self.lock:
            self.client=client
            self.subscribed=set()
            self.mqtt_values={}
        self.sync_mqtt()

    def mqtt_disconnect(self,client):
        with self.lock:
            if self.client is client:
                self.client=None
                self.subscribed=set()
                self.mqtt_values={}

    def sync_mqtt(self):
        # Never invoke Paho while holding the measurement lock: callbacks
        # can run on a different thread with Paho's internal locks held.
        if not self.sync_lock.acquire(blocking=False):
            return
        try:
            with self.lock:
                client=self.client
                wanted=self.mqtt_topics(self.cfg)
                self.check_topics(self.cfg)
                subscribed=set(self.subscribed)
            if client is None or not client.is_connected():
                return
            for topic in subscribed-wanted:
                rc,_=client.unsubscribe(topic)
                if rc==0:
                    with self.lock:
                        if self.client is client:
                            self.subscribed.discard(topic)
            for topic in wanted-subscribed:
                rc,_=client.subscribe(topic,qos=0)
                if rc==0:
                    with self.lock:
                        if self.client is client:
                            self.subscribed.add(topic)
        except Exception:
            pass
        finally:
            self.sync_lock.release()

    def mqtt_message(self,client,msg):
        with self.lock:
            if client is not self.client or msg.topic not in self.mqtt_topics(self.cfg):
                return False
            try:
                self.check_topics(self.cfg)
            except ValueError:
                return False
            try:
                if not msg.retain and len(msg.payload)<=64:
                    self.mqtt_values[msg.topic]=(time.monotonic(),msg.payload.decode("ascii"))
            except (ValueError,UnicodeError):
                pass
            return True

    def read_ha(self,entity,field,unit):
        from urllib.parse import urlsplit
        base=str(self.g.get("haaddr","")).rstrip("/")
        port=str(self.g.get("haport",""))
        p=urlsplit(base)
        if p.scheme not in ("http","https") or not p.hostname or p.username or p.password or p.path or p.query or p.fragment:
            raise ValueError("Invalid HA address")
        if p.port is None and port:
            if not port.isdecimal() or not 1<=int(port)<=65535:
                raise ValueError("Invalid HA port")
            base+=":"+port
        headers={"Authorization":"Bearer "+str(self.g.get("hakey","")),"Accept":"application/json"}
        with self.g["requests"].get(base+"/api/states/"+entity,headers=headers,
                                    timeout=(2,3),allow_redirects=False,stream=True) as resp:
            if resp.status_code!=200:
                raise ValueError("HA request failed")
            raw=bytearray()
            deadline=time.monotonic()+5
            for chunk in resp.iter_content(4096):
                if time.monotonic()>deadline:
                    raise ValueError('HA response deadline')
                raw.extend(chunk)
                if len(raw)>32768:
                    raise ValueError("HA response too large")
            data=json.loads(raw)
        attrs=data.get("attributes",{})
        actual=attrs.get("unit_of_measurement")
        normalized=str(actual).replace("³","3").replace("L/","l/")
        if normalized!=unit:
            raise ValueError("Unit mismatch")
        stamp=data.get("last_reported") or data.get("last_updated")
        t=datetime.fromisoformat(stamp.replace("Z","+00:00")).timestamp()
        if not -5<=time.time()-t<=MAX_READ_AGE:
            raise ValueError("Stale HA value")
        return convert(field,data["state"],unit)

    def read_values(self,cfg):
        values={}
        failures=[]
        for field in FIELDS:
            source=cfg["flow_source"] if field=="flow" else cfg["source"]
            if field=="flow" and source=="manual":
                values[field]=cfg["manual_flow"]
                continue
            if source=="none" or not cfg[field]:
                continue
            try:
                if source=="ha":
                    values[field]=self.read_ha(cfg[field],field,cfg[field+"_unit"])
                else:
                    with self.lock:
                        row=self.mqtt_values.get(cfg[field])
                    if not row or not 0<=time.monotonic()-row[0]<=MAX_READ_AGE:
                        raise ValueError("No fresh MQTT value")
                    values[field]=convert(field,row[1],cfg[field+"_unit"])
            except Exception:
                failures.append(field)
        return values,failures

    def probe(self,data):
        cfg=validate(data)
        self.check_topics(cfg)
        # MQTT testing uses existing subscriptions; never subscribe to draft topics.
        with self.lock:
            if self.busy or (getattr(self,"last_probe",None) is not None and time.monotonic()-self.last_probe<10):
                raise ValueError("Odczyt zajęty lub test wykonywany zbyt często")
            self.last_probe=time.monotonic()
            self.busy=True
        try:
            values,failures=self.read_values(cfg)
            return {"values":values,"missing":failures,"mqtt_requires_saved_settings":bool(self.mqtt_topics(cfg)-self.mqtt_topics(self.settings()))}
        finally:
            with self.lock:
                self.busy=False

    def poll(self,now,state,cycles=(),session=None):
        self.sync_mqtt()
        with self.lock:
            if not self.cfg["enabled"] or self.busy or (self.last_poll is not None and now-self.last_poll<self.cfg["interval"]):
                return
            self.busy=True
            self.last_poll=now
            cfg=dict(self.cfg)
            generation=self.generation
            wall=time.time()
        def run():
            try:
                values,failures=self.read_values(cfg)
                ended=time.monotonic()
                with self.lock:
                    if generation==self.generation:
                        self.current=values if ended-now<=20 else {}
                        self.current_at=ended
                        self.error=("Brak świeżych danych: "+", ".join(failures)) if failures else None
                        self.accept(now,state,values,wall) if ended-now<=20 else self.accept(now,None,{},wall)
                        self.record_cycles(session,cycles)
            finally:
                with self.lock:
                    self.busy=False
        try:
            threading.Thread(target=run,name="hpi-energy",daemon=True).start()
        except BaseException:
            with self.lock:
                self.busy=False
            raise

    def accept(self,now,state,values,wall=None):
        # Caller holds lock. No interpolation across missing samples or mode transitions.
        old=self.last
        self.last=(now,state,dict(values),wall)
        session=state[3] if state else None
        if session is not None and session!=self.session:
            self.session=session
            self.experiment={}
        if old is None:
            return
        t,prev,a,old_wall=old
        dt=now-t
        if not 0<dt<=self.cfg["interval"]+35:
            return
        if "energy" in a and "energy" in values:
            e=values["energy"]-a["energy"]
            if not 0<=e<=100*dt/3600:
                return
        elif not self.cfg["energy"] and "power" in a and "power" in values:
            e=(a["power"]+values["power"])*dt/7200
        else:
            return
        stable=bool(state and prev and state[:2]==prev[:2] and state[3]==prev[3])
        group=state[0] if stable else "unassigned"
        mode=state[1] if stable else None
        heat=None
        if stable and group=="co_run" and "flow" in a and "flow" in values:
            if 0<=prev[2]<=30 and 0<=state[2]<=30:
                heat=1.163*(a["flow"]*prev[2]+values["flow"]*state[2])*dt/7200
        end_wall=wall if wall is not None and old_wall is not None and abs((wall-old_wall)-dt)<=5 else None
        row=(now,group,mode,dt,e,heat,end_wall)
        self.rows.append(row)
        if stable and session is not None and group in ("co_run","co_idle"):
            self.add(self.experiment,mode,row)
        while self.rows and self.rows[0][0]<now-86400:
            self.rows.popleft()

    @staticmethod
    def add(target,key,row):
        if key is None:
            return
        _,_,_,dt,e,heat=row[:6]
        b=target.setdefault(key,{"seconds":0,"kwh":0.0,"paired_kwh":0.0,"heat_kwh":0.0,"paired_seconds":0})
        b["seconds"]+=dt
        b["kwh"]+=e
        if heat is not None:
            b["heat_kwh"]+=heat
            b["paired_kwh"]+=e
            b["paired_seconds"]+=dt


    def load_cycles(self):
        if self.cycle_path is None:
            return
        try:
            if self.cycle_path.is_symlink() or self.cycle_path.stat().st_size>16384:
                raise ValueError("Invalid cycle file")
            d=json.loads(self.cycle_path.read_text())
            if d["schema"]!=1 or d["settings"]!=self.cfg:
                return
            session=d["session"]
            if type(session) not in (int,float) or not math.isfinite(session) or session<=0:
                raise ValueError("Invalid cycle session")
            if not isinstance(d["cycles"],list) or len(d["cycles"])>18:
                raise ValueError("Invalid cycles")
            result={}
            for row in d["cycles"]:
                keys={"start","stop","mode","duration_seconds","covered_seconds","paired_seconds","kwh","heat_kwh","paired_kwh","cop_estimate"}
                if not isinstance(row,dict) or set(row)!=keys or row["mode"] not in tuple(m+f for m in ("eco","quiet","turbo") for f in (" + FLimit"," / FLimit OFF")):
                    raise ValueError("Invalid cycle")
                for k,v in row.items():
                    if k=="mode":
                        continue
                    if v is None and k in ("kwh","heat_kwh","paired_kwh","cop_estimate"):
                        continue
                    if type(v) not in (int,float) or not math.isfinite(v) or v<0:
                        raise ValueError("Invalid cycle value")
                if not session<=row["start"]<row["stop"] or not 0<=row["paired_seconds"]<=row["covered_seconds"]<=row["duration_seconds"]+5:
                    raise ValueError("Invalid cycle coverage")
                result[row["start"]]=row
            self.cycle_session=session
            self.cycles=result
        except FileNotFoundError:
            pass
        except (OSError,ValueError,TypeError,KeyError):
            self.cycle_error="Nie można odczytać bilansu cykli"

    def save_cycles(self):
        if self.cycle_path is None:
            return
        temp=None
        try:
            if self.cycle_path.is_symlink():
                raise ValueError("Invalid cycle path")
            fd,temp=tempfile.mkstemp(prefix=".energy-cycles-",dir=self.cycle_path.parent)
            with os.fdopen(fd,"w",encoding="utf-8") as f:
                json.dump({"schema":1,"settings":self.cfg,"session":self.cycle_session,
                           "cycles":list(self.cycles.values())},f,allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp,self.cycle_path)
            temp=None
            self.cycle_error=None
        except (OSError,ValueError):
            self.cycle_error="Nie można zapisać bilansu cykli"
        finally:
            if temp is not None:
                try: os.unlink(temp)
                except OSError: pass

    def record_cycles(self,session,cycles):
        # Only intervals wholly inside a completed cycle, in the same
        # observed configuration and CO-running state. Never extrapolate.
        if session is None or self.last is None or self.last[3] is None:
            return
        if session!=self.cycle_session:
            self.cycle_session=session
            self.cycles={}
        changed=False
        for start,stop,mode in cycles:
            if start in self.cycles or start<session or not start<stop<=self.last[3] or len(self.cycles)>=18:
                continue
            rows=[r for r in self.rows if r[6] is not None and r[1]=="co_run" and r[2]==mode
                  and start<=r[6]-r[3] and r[6]<=stop]
            bucket={}
            for r in rows:
                self.add(bucket,mode,r)
            b=bucket.get(mode,{"seconds":0,"kwh":0,"paired_seconds":0,"heat_kwh":0,"paired_kwh":0})
            self.cycles[start]={"start":start,"stop":stop,"mode":mode,"duration_seconds":stop-start,
                "covered_seconds":b["seconds"],"paired_seconds":b["paired_seconds"],
                "kwh":b["kwh"] if rows else None,"heat_kwh":b["heat_kwh"] if b["paired_seconds"] else None,
                "paired_kwh":b["paired_kwh"] if b["paired_seconds"] else None,
                "cop_estimate":b["heat_kwh"]/b["paired_kwh"] if b["paired_seconds"]>=300 and b["paired_kwh"]>=.05 else None}
            changed=True
        if changed:
            self.save_cycles()

    def meter_average_power(self,now):
        # Average over contiguous, measured counter increments only.
        # Do not bridge gaps, resets or stale readings.
        if not self.cfg["enabled"] or not self.cfg["energy"] or not self.rows or self.last is None:
            return None
        end=self.rows[-1][0]
        if self.last[0]!=end or not 0<=now-end<=self.cfg["interval"]+35:
            return None
        seconds=0.0
        kwh=0.0
        cursor=end
        for row in reversed(self.rows):
            if abs(row[0]-cursor)>0.001 or seconds+row[3]>300:
                break
            seconds+=row[3]
            kwh+=row[4]
            cursor=row[0]-row[3]
        if seconds<60:
            return None
        return {"kw":kwh*3600/seconds,"seconds":seconds}

    def summary(self,now=None):
        now=time.monotonic() if now is None else now
        with self.lock:
            totals={}
            modes={}
            for row in self.rows:
                if now-86400<=row[0]<=now:
                    self.add(totals,row[1],row)
                    if row[1] in ("co_run","co_idle"):
                        self.add(modes,row[2],row)
            def expose(rows):
                return {k:dict(v,cop_estimate=(v["heat_kwh"]/v["paired_kwh"]
                     if v["paired_seconds"]>=300 and v["paired_kwh"]>=.05 else None)) for k,v in rows.items()}
            return {"settings":dict(self.cfg),"error":self.error,
                    "current":dict(self.current) if self.current_at is not None and 0<=now-self.current_at<=MAX_READ_AGE else {},
                    "meter_average_power":self.meter_average_power(now),
                    "busy":self.busy,"groups_24h":expose(totals),"modes_24h":expose(modes),
                    "experiment":expose(self.experiment),"session":self.session,
                    "cycles":list(self.cycles.values()),"cycle_session":self.cycle_session,"cycle_error":self.cycle_error,
                    "electricity_estimated":not bool(self.cfg["energy"]),"flow_estimated":self.cfg["flow_source"]=="manual",
                    "coverage_seconds":sum(v["seconds"] for v in totals.values()),
                    "scope":"RAM only; sampling estimates, not calibrated heat measurement"}
