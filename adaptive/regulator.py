"""Experimental anti-cycling supervisory policy. Pure proposals, no I/O."""
from dataclasses import dataclass, replace
from pathlib import Path
import json
import os
import tempfile
import time
from collections import deque
from statistics import median
import math

# Indices are identifiers, NOT a measured total ordering of capacity.
LEVELS=(("quiet",True),("quiet",False),("eco",False),("turbo",False),
        ("eco",True),("turbo",True))
PRESETS=("quiet","eco","turbo")
# Empirical supply-temperature STOP model, not a factory-confirmed safety limit.
STOP_HYSTERESIS=5.0

@dataclass(frozen=True)
class Sample:
    now: float
    target: float
    return_temp: float
    supply_temp: float
    hz: float
    requested_hz: float
    mode: str
    relay: bool
    heating: bool
    defrost: bool
    fresh: bool
    error: int=0
    dhw: bool=False
    override: bool=False

@dataclass(frozen=True)
class Settings:
    window: float=150
    max_gap: float=65
    startup_hold: float=300
    settle_hold: float=180
    up_confirm: float=120
    urgent_confirm: float=60
    down_confirm: float=90
    early_down_confirm: float=60
    early_surplus: float=2.5
    probe_after: float=900
    failed_retry: float=1800
    trial_window: float=900
    forecast_min: float=3
    deficit_band: float=0.5
    surplus_band: float=1.5
    urgent_deficit: float=2
    integral_limit: float=4  # K*min, not thermal energy
    trend_band: float=0.08
    stop_margin: float=1.0  # provisional warning margin below assumed STOP
    probe_hz: float=30  # experimental opt-out threshold, not factory minimum

@dataclass(frozen=True)
class Decision:
    current: int
    proposed: int
    reason: str
    delta: float=None  # median target minus Twi
    trend: float=None  # return deficit K/min
    supply_error: float=None
    supply_trend: float=None
    predicted_surplus: float=None  # predicted Twi minus target
    deficit_integral: float=0
    risk: str="paused"
    blocked_seconds: float=0
    supply_forecast: float=None  # predicted Two minus target

def adjacent(level,direction):
    """One output per transition. Direction is a policy hypothesis.
    Up: remove limit first, then raise preset. Down: limit first, then
    lower preset with limit retained. No assumed ranking across mixed pairs.
    """
    mode,relay=LEVELS[level]
    i=PRESETS.index(mode)
    if direction=="up":
        if relay:
            return LEVELS.index((mode,False))
        if i<2:
            return LEVELS.index((PRESETS[i+1],False))
    elif direction=="down":
        if not relay:
            return LEVELS.index((mode,True))
        if i>0:
            return LEVELS.index((PRESETS[i-1],True))
    return level

def trend(rows,index):
    n=len(rows)//2
    a,b=rows[:n],rows[n:]
    dt=median(x[0] for x in b)-median(x[0] for x in a)
    return (median(x[index] for x in b)-median(x[index] for x in a))*60/dt if dt>0 else 0

class Regulator:
    def __init__(self,settings=Settings()):
        self.cfg=settings
        if not all(isinstance(v,(int,float)) and math.isfinite(v) and v>0
                   for v in vars(settings).values()):
            raise ValueError("Invalid settings")
        if settings.window<90 or settings.urgent_deficit<=settings.deficit_band:
            raise ValueError("Invalid policy bands")
        self.history=deque()
        self.last=None
        self.level=None
        self.target=None
        self.ready_since=None
        self.changed_at=None
        self.integral=0
        self.candidate=None
        self.candidate_since=None
        self.last_offer=None
        self.trial=None
        self.blocked={}
        self.last_control=None

    def reset(self,clear_memory=False):
        self.history.clear()
        self.last=None
        self.ready_since=None
        self.candidate=None
        self.candidate_since=None
        self.integral=0
        self.last_offer=None
        self.trial=None
        if clear_memory:
            self.blocked.clear()
            self.level=None
            self.target=None
            self.changed_at=None

    def step(self,s,control="shadow",allowed=None):
        if control not in ("manual","legacy","shadow","auto"):
            raise ValueError("Unknown control")
        allowed=set(range(len(LEVELS))) if allowed is None else set(allowed)
        if not allowed or not allowed<=set(range(len(LEVELS))):
            raise ValueError("Invalid allowed combinations")
        try:
            level=LEVELS.index((s.mode,s.relay))
        except ValueError:
            self.reset()
            return Decision(None,None,"unknown preset or relay")
        if control!=self.last_control:
            self.reset(clear_memory=True)
            self.last_control=control
        if control in ("manual","legacy"):
            return Decision(level,level,"external control owns outputs")
        finite=all(type(x) in (int,float) and math.isfinite(x) for x in
                   (s.now,s.target,s.return_temp,s.supply_temp,s.hz,s.requested_hz))
        valid=(finite and s.fresh and s.heating and not s.defrost and not s.dhw
               and not s.override and s.error==0 and s.hz>0 and s.requested_hz>0
               and 10<=s.target<=65 and -10<=s.return_temp<=85 and -10<=s.supply_temp<=85)
        if not valid:
            self.reset()
            return Decision(level,level,"paused: operating state or data invalid")
        c=self.cfg
        now=s.now
        if self.last is not None and not 0<now-self.last<=c.max_gap:
            self.reset(clear_memory=now<=self.last)
        if self.target is None or abs(s.target-self.target)>=0.25:
            self.reset(clear_memory=True)
            self.target=s.target
        self.blocked={k:v for k,v in self.blocked.items() if now<v}
        if level!=self.level:
            offer=self.last_offer
            previous=self.level
            self.reset()
            self.level=level
            self.changed_at=now
            # A matching observed transition is NOT proof of causation.
            # Only evaluate a reduction that was actually observed after a proposal.
            if offer and offer[0]==previous and offer[1]==level and offer[2]=="down" and 0<=now-offer[3]<=c.max_gap:
                self.trial=(previous,level,now)
        if self.ready_since is None:
            self.ready_since=now
        dt=0 if self.last is None else (now-self.last)/60
        self.last=now
        e=s.target-s.supply_temp
        self.history.append((now,e,s.target-s.return_temp,s.hz,s.requested_hz))
        while self.history and now-self.history[0][0]>c.window:
            self.history.popleft()
        rows=list(self.history)
        es=median(x[1] for x in rows)
        er=median(x[2] for x in rows)
        # Twi indicates thermal demand; supply corroborates a shortage.
        # A cold return with adequately warm supply is normal.
        self.integral=max(0,min(30,self.integral+(max(0,er-0.2) if er>0.2 and es>0.2 else -0.8)*dt))
        if len(rows)<3 or now-rows[0][0]<90:
            return Decision(level,level,"collecting samples",er,supply_error=es,deficit_integral=self.integral)
        ts=trend(rows,1)
        tr=trend(rows,2)
        # A long median lags rising return temperature; start forecast at
        # the latest three-sample median, using the robust full-window trend.
        forecast=-median(x[2] for x in rows[-3:])-max(-0.5,min(0.5,tr))*c.forecast_min
        supply_forecast=max(s.supply_temp-s.target,-median(x[1] for x in rows[-3:]))-max(-0.5,min(0.5,ts))*c.forecast_min
        def decision(proposed,reason,risk,blocked=0):
            return Decision(level,proposed,reason,er,tr,es,ts,forecast,self.integral,risk,blocked,supply_forecast)
        urgent=er>=c.urgent_deficit and es>=c.urgent_deficit and tr>=-c.trend_band and ts>=-c.trend_band
        shortfall=er>c.deficit_band and tr>=-c.trend_band and (
            (es>c.deficit_band and ts>=-c.trend_band) or (es>0.2 and self.integral>=c.integral_limit))
        # Return indicates surplus; supply approaching the empirical STOP
        # band independently calls for a reduction, even with a cold return.
        excess=(er<=-c.surplus_band and tr<=c.trend_band) or (
            er<=0 and forecast>=c.early_surplus and tr<-c.trend_band)
        stop_risk=max(s.supply_temp-s.target,supply_forecast)>=STOP_HYSTERESIS-c.stop_margin
        # Close to STOP, never increase capacity even if the median lags.
        if stop_risk:
            urgent=shortfall=False
        settled=now-self.ready_since>=c.startup_hold and now-self.changed_at>=c.settle_hold
        stable_probe=(now-self.ready_since>=c.probe_after and abs(er)<=0.3 and es<=0.3 and
                      abs(ts)<=c.trend_band and abs(tr)<=c.trend_band and
                      median(x[3] for x in rows)>=c.probe_hz and
                      abs(median(x[3]-x[4] for x in rows))<=2)
        if self.trial and now-self.trial[2]>c.trial_window:
            self.trial=None
        direction=None
        risk=("cycling_risk_at_minimum" if level==0 else "cycling_risk") if stop_risk else "balanced"
        if urgent or shortfall:
            direction="up"
            risk="shortfall"
            # Urgent deficits may bypass the normal settling hold but still need confirmation.
            if not urgent and now-self.changed_at<c.settle_hold:
                direction=None
        elif (settled and (excess or stable_probe or stop_risk)) or ((stop_risk or (excess and forecast>=c.early_surplus and tr<-c.trend_band)) and now-self.ready_since>=c.settle_hold and now-self.changed_at>=c.settle_hold):
            direction="down"
            risk="cycling_risk" if stop_risk else "surplus" if excess else "efficiency_probe"
        # A reduction while the inverter is already ramping down can overshoot
        # in the opposite direction; let its own regulation settle first.
        if direction=="down" and trend(rows,3)<-2 and trend(rows,4)<-2:
            direction=None
        if direction is None:
            self.candidate=self.candidate_since=None
            self.last_offer=None
            return decision(level,"hold: settling, balanced or recovering",risk)
        proposed=adjacent(level,direction)
        if direction=="up" and self.trial and self.trial[1]==level:
            proposed=self.trial[0]  # undo one observed reduction
        if proposed==level or proposed not in allowed:
            self.candidate=self.candidate_since=None
            self.last_offer=None
            if direction=="down" and proposed==level:
                return decision(level,"minimum available envelope; native modulation or stop", "cycling_risk_at_minimum" if stop_risk else "surplus_at_minimum")
            return decision(level,"capacity boundary or restriction",risk)
        blocked=self.blocked.get((level,proposed),0)-now
        if direction=="down" and blocked>0:
            self.candidate=self.candidate_since=None
            self.last_offer=None
            return decision(level,"hold: previous reduction failed",risk,blocked)
        key=(level,proposed,direction)
        if key!=self.candidate:
            self.candidate=key
            self.candidate_since=now
        required=c.urgent_confirm if direction=="up" and urgent else c.up_confirm if direction=="up" else c.early_down_confirm if stop_risk or (excess and forecast>=c.early_surplus and tr<-c.trend_band) else c.down_confirm
        if now-self.candidate_since<required:
            self.last_offer=None
            return decision(level,"confirming "+risk,risk)
        if direction=="up" and self.trial and self.trial[1]==level:
            self.blocked[(self.trial[0],level)]=now+c.failed_retry
            reason="restore previous capacity; reduction failed"
        else:
            reason="increase available capacity" if direction=="up" else "reduce before overshoot" if excess or stop_risk else "probe lower capacity"
        self.last_offer=(level,proposed,direction,now)
        return decision(proposed,reason,risk)

class Learning:
    """Bounded adaptation from confirmed, uninterrupted Auto reductions."""
    MAX_CONTEXTS = 1024
    MAX_FILE_BYTES = 512 * 1024
    SAVE_INTERVAL = 1800

    def __init__(self, path=None, logger=None):
        self.path = Path(path) if path is not None else None
        self.logger = logger
        self.rows = {}
        self.trial = None
        self.dirty = False
        self.last_save = None
        self.storage_error = None
        self.load()

    @staticmethod
    def key(s, outdoor, old, new):
        if not math.isfinite(outdoor) or not -40 <= outdoor <= 45:
            return None
        return "%d:%d:%d:%d" % (math.floor(outdoor/5), math.floor(s.target/3), old, new)

    def load(self):
        if self.path is None:
            return
        try:
            if self.path.is_symlink() or self.path.stat().st_size > self.MAX_FILE_BYTES:
                raise ValueError("invalid learning file")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data["schema"] != 2 or not isinstance(data["contexts"], dict) or len(data["contexts"]) > self.MAX_CONTEXTS:
                raise ValueError("invalid learning schema")
            rows = {}
            for k, v in data["contexts"].items():
                a,b,c,d = map(int,k.split(":"))
                if not (-8 <= a <= 9 and 3 <= b <= 21 and 0 <= c < 6 and 0 <= d < 6 and adjacent(c,"down")==d and c!=d):
                    raise ValueError("invalid context")
                if set(v) != {"n","score","delta_hz","delta_error","return_trend","last"} or type(v["n"]) is not int or not 1<=v["n"]<=1000000:
                    raise ValueError("invalid observation")
                if not all(type(v[x]) in (int,float) and math.isfinite(v[x]) for x in ("score","delta_hz","delta_error","return_trend","last")):
                    raise ValueError("invalid numeric observation")
                if not (-1<=v["score"]<=1 and abs(v["delta_hz"])<=150 and abs(v["delta_error"])<=30 and abs(v["return_trend"])<=10 and v["last"]>=0):
                    raise ValueError("out of range observation")
                rows[k]=v
            self.rows=rows
            self.last_save=time.monotonic()
        except FileNotFoundError:
            pass
        except (OSError,ValueError,TypeError,KeyError,AttributeError,OverflowError) as e:
            self.storage_error=type(e).__name__
            self.last_save=time.monotonic()
            if self.logger:
                self.logger.warning("Adaptive learning load skipped: %s", self.storage_error)

    def settings(self, s, outdoor):
        base=Settings()
        old=LEVELS.index((s.mode,s.relay))
        new=adjacent(old,"down")
        row=self.rows.get(self.key(s,outdoor,old,new),{})
        if row.get("n",0)<3:
            return base
        score=row["score"]
        return replace(base,
                       down_confirm=max(60,min(120,90-30*score)),
                       surplus_band=max(1.0,min(2.0,1.5-.5*score)),
                       early_surplus=max(2.0,min(3.0,2.5-.5*score)),
                       forecast_min=max(2.5,min(3.5,3+.5*score)))

    def cancel(self):
        self.trial=None

    def start(self, before, after, outdoor):
        self.cancel()
        old=LEVELS.index((before.mode,before.relay))
        new=LEVELS.index((after.mode,after.relay))
        if old==new or adjacent(old,"down")!=new or abs(before.target-after.target)>=.25:
            return
        key=self.key(before,outdoor,old,new)
        if key is not None:
            self.trial={"key":key,"before":before,"new":new,"outdoor":outdoor,
                        "start":after.now,"last":after.now,"samples":[]}

    def observe(self,s,outdoor):
        t=self.trial
        if t is None:
            return
        if (not s.fresh or not s.heating or s.defrost or s.dhw or s.override or s.error
            or s.hz<=0 or s.requested_hz<=0 or abs(s.target-t["before"].target)>=.25
            or abs(outdoor-t["outdoor"])>1.5 or LEVELS.index((s.mode,s.relay))!=t["new"]
            or not 0<=s.now-t["last"]<=65
            or not all(math.isfinite(x) for x in (s.now,s.target,s.supply_temp,s.return_temp,s.hz,outdoor))):
            self.cancel()
            return
        if s.now==t["last"]:
            return
        t["last"]=s.now
        t["samples"].append((s.now,s.target-s.return_temp,s.hz,s.target-s.supply_temp))
        t["samples"]=[x for x in t["samples"] if s.now-x[0]<=120]
        if s.now-t["start"]<90 or len(t["samples"])<3:
            return
        e=median(x[1] for x in t["samples"])
        hz=median(x[2] for x in t["samples"])
        rate=-trend(t["samples"],1)
        shortage=e>.5 and rate<=.08 and all(x[1]>.3 and x[3]>.3 for x in t["samples"])
        urgent=e>=2 and rate<=.08 and all(x[1]>1.5 and x[3]>1.5 for x in t["samples"])
        if s.now-t["start"]<180 and not urgent:
            return
        # A persistent supply risk can justify another reduction after the
        # 180 s settling period. Record that observation before it is lost.
        supply_surplus=-median(x[3] for x in t["samples"])
        supply_rise=max(0,min(.5,-trend(t["samples"],3)))
        supply_risk=supply_surplus+supply_rise*3>=4
        if not shortage and not supply_risk and s.now-t["start"]<300:
            return
        # Positive score means thermal surplus or persistent supply STOP risk.
        # It is not a measurement of savings or a prevented stop.
        score=-1 if shortage else 1 if supply_risk or -e>=1.5 or (-e>=0 and -e+max(0,rate)*3>=2.5) else 0
        self.record(t["key"],score,hz-t["before"].hz,e-(t["before"].target-t["before"].return_temp),rate)
        self.cancel()

    def record(self,key,score,dhz,de,rate=0):
        if not all(math.isfinite(x) for x in (score,dhz,de,rate)) or abs(dhz)>150 or abs(de)>30 or abs(rate)>10:
            return
        if key not in self.rows and len(self.rows)>=self.MAX_CONTEXTS:
            del self.rows[min(self.rows,key=lambda k:self.rows[k]["last"])]
        row=self.rows.get(key)
        alpha=1 if row is None else .25
        row=row or {"n":0,"score":0,"delta_hz":0,"delta_error":0,"return_trend":0}
        updated={"n":min(1000000,row["n"]+1),"last":max(0,time.time())}
        for name,value in (("score",score),("delta_hz",dhz),("delta_error",de),("return_trend",rate)):
            updated[name]=round((1-alpha)*row[name]+alpha*value,4)
        self.rows[key]=updated
        self.dirty=True
        if self.logger:
            self.logger.info("Adaptive learning observation: %s %s",key,updated)

    def save_if_due(self,now):
        if not self.dirty or self.path is None or (self.last_save is not None and now-self.last_save<self.SAVE_INTERVAL):
            return
        self.last_save=now
        temp=None
        try:
            if self.path.is_symlink():
                raise ValueError("symlink learning path")
            fd,temp=tempfile.mkstemp(prefix=".adaptive-learning-",dir=str(self.path.parent))
            with os.fdopen(fd,"w",encoding="utf-8") as f:
                json.dump({"schema":2,"contexts":self.rows},f,allow_nan=False,sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp,self.path)
            temp=None
            self.dirty=False
            self.storage_error=None
        except (OSError,ValueError,TypeError) as e:
            self.storage_error=type(e).__name__
            if self.logger:
                self.logger.warning("Adaptive learning persistence unavailable: %s",self.storage_error)
        finally:
            if temp is not None:
                try:
                    os.unlink(temp)
                except OSError:
                    pass

    def summary(self):
        return {"contexts":len(self.rows),"observations":sum(v["n"] for v in self.rows.values()),
                "trial":self.trial is not None,"unsaved":self.dirty,"storage_error":self.storage_error}


class HysteresisObserver:
    """Passive, bounded evidence of native CO transitions; never controls outputs.

    Thresholds are brackets between consecutive samples, not exact firmware
    thresholds. Discard interrupted cycles and keep contexts separate.
    """
    LIMIT = 128
    MIN_PHASE = 300
    POST_STOP = 120
    MAX_GAP = 65
    SAVE_INTERVAL = 300
    SENSORS = ('twi','two','mean')
    BANDS = (0,1,2)

    def __init__(self, path=None, logger=None):
        self.path = Path(path) if path is not None else None
        self.logger = logger
        self.rows = []
        self.since = None
        self.change = None
        self.last = None
        self.context = None
        self.phase_since = None
        self.start = None
        self.stop = None
        self.ran = False
        self.outdoor = None
        self.above = self.empty_above()
        self.dirty = False
        self.last_save = None
        self.storage_error = None
        self.load()

    def load(self):
        if self.path is None:
            return
        try:
            if self.path.is_symlink() or self.path.stat().st_size > 262144:
                raise ValueError("invalid observer file")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data["schema"] not in (1,2) or not isinstance(data["cycles"], list) or len(data["cycles"]) > self.LIMIT:
                raise ValueError("invalid observer schema")
            def numeric(x, lo, hi):
                return type(x) in (float, int) and math.isfinite(x) and lo <= x <= hi
            for row in data["cycles"]:
                ctx = row["context"]
                if (len(ctx) != 4 or ctx[0] not in ("legacy", "manual", "shadow", "auto", "experiment")
                        or ctx[1] not in PRESETS or type(ctx[2]) is not bool
                        or not numeric(ctx[3], 10, 65)):
                    raise ValueError("invalid context")
                for event in (row["start"], row["stop"]):
                    if not numeric(event["at"], 0, 1e11):
                        raise ValueError("invalid event time")
                    for k in ("twi", "two"):
                        if len(event[k]) != 2 or not all(numeric(v, -100, 100) for v in event[k]):
                            raise ValueError("invalid temperature bracket")
                for event in (row["start"],row["stop"]):
                    if "outdoor" in event and (len(event["outdoor"]) != 2 or not all(v is None or numeric(v,-60,60) for v in event["outdoor"])):
                        raise ValueError("invalid outdoor samples")
                    for k in ("fact","fset"):
                        if k in event and (len(event[k]) != 2 or not all(numeric(v,0,500) for v in event[k])):
                            raise ValueError("invalid frequency samples")
                if "run_seconds" in row and not numeric(row["run_seconds"],0,1e8):
                    raise ValueError("invalid duration")
                if "above_seconds" in row:
                    if set(row["above_seconds"]) != set(self.SENSORS):
                        raise ValueError("invalid duration sensors")
                    for values in row["above_seconds"].values():
                        if set(values) != {str(k) for k in self.BANDS} or not all(numeric(v,0,row["run_seconds"]) for v in values.values()):
                            raise ValueError("invalid duration")
                if row["stop"]["at"] < row["start"]["at"]:
                    raise ValueError("invalid event order")
            if data["since"] is not None and not numeric(data["since"], 0, 1e11):
                raise ValueError("invalid collection start")
            self.rows = data["cycles"]
            self.since = data["since"]
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError) as e:
            self.storage_error = type(e).__name__
            self.last_save = time.monotonic()

    def interrupt(self):
        self.last = None
        self.phase_since = None
        self.start = self.stop = None
        self.ran = False
        self.outdoor = None
        self.above = self.empty_above()

    @classmethod
    def empty_above(cls):
        return {k:{str(b):0.0 for b in cls.BANDS} for k in cls.SENSORS}

    @staticmethod
    def offsets(s):
        a,b=s.return_temp-s.target,s.supply_temp-s.target
        return {"twi":a,"two":b,"mean":(a+b)/2}

    @classmethod
    def edge(cls,before,after,wall,previous_outdoor,outdoor):
        a,b=cls.offsets(before),cls.offsets(after)
        return {"at":wall,"twi":[round(a["twi"],3),round(b["twi"],3)],
                "two":[round(a["two"],3),round(b["two"],3)],
                "outdoor":[previous_outdoor,outdoor],
                "fact":[before.hz,after.hz],"fset":[before.requested_hz,after.requested_hz]}

    def observe(self, s, control, eligible, wall, outdoor=None):
        if type(outdoor) not in (int,float) or not math.isfinite(outdoor) or not -60<=outdoor<=60:
            outdoor=None
        if self.since is None:
            self.since = wall
            self.dirty = True
        if not (eligible and s.fresh and not s.defrost and not s.dhw and not s.override and not s.error
                and all(type(v) in (int,float) and math.isfinite(v) for v in
                        (s.now,s.target,s.return_temp,s.supply_temp,s.hz,s.requested_hz,wall))
                and 10 <= s.target <= 65 and -10 <= s.return_temp <= 85
                and -10 <= s.supply_temp <= 85 and min(s.hz,s.requested_hz) >= 0):
            self.interrupt()
            return
        context = (control, s.mode, s.relay, s.target)
        if context != self.context:
            self.interrupt()
            self.context = context
            self.change = wall
        before = self.last
        if before is not None and not 0 < s.now-before.now <= self.MAX_GAP:
            self.interrupt()
            before = None
        previous_outdoor=self.outdoor
        self.outdoor=outdoor
        self.last = s
        active = s.requested_hz > 0
        if before is None:
            self.phase_since = s.now if not active and s.hz == 0 else None
            return
        if active and not before.requested_hz:
            if self.stop is not None or self.phase_since is None or s.now-self.phase_since < self.MIN_PHASE or before.hz != 0:
                self.start = None
            else:
                self.start = self.edge(before,s,wall,previous_outdoor,outdoor)
            self.above=self.empty_above()
            self.phase_since = s.now
            self.stop = None
            self.ran = s.hz > 0
        if self.start is not None and active and before.requested_hz>0:
            a,b=self.offsets(before),self.offsets(s)
            for k in self.SENSORS:
                for band in self.BANDS:
                    if min(a[k],b[k])>band:
                        self.above[k][str(band)]+=s.now-before.now
        if not active and before.requested_hz > 0:
            self.stop = (self.edge(before,s,wall,previous_outdoor,outdoor),s.now,
                         round(s.now-self.phase_since,2),self.above) if (
                self.start is not None and self.ran and self.phase_since is not None
                and s.now-self.phase_since >= self.MIN_PHASE) else None
            self.phase_since = None
        if active:
            self.ran = self.ran or s.hz > 0
        elif s.hz == 0:
            if self.phase_since is None:
                self.phase_since = s.now
            if self.stop is not None and s.now-self.phase_since >= self.POST_STOP:
                self.rows.append({"context":list(context),"start":self.start,"stop":self.stop[0],
                                  "run_seconds":self.stop[2],"above_seconds":self.stop[3]})
                self.rows = self.rows[-self.LIMIT:]
                self.start = self.stop = None
                self.dirty = True
                if self.logger:
                    self.logger.info("Hysteresis observer: accepted CO cycle (%s stored)",len(self.rows))

    def save_if_due(self, now):
        if not self.dirty or self.path is None or (self.last_save is not None and now-self.last_save < self.SAVE_INTERVAL):
            return
        self.last_save = now
        tmp = None
        try:
            if self.path.is_symlink():
                raise ValueError("symlink observer path")
            fd,tmp = tempfile.mkstemp(prefix=".hysteresis-",dir=str(self.path.parent))
            with os.fdopen(fd,"w",encoding="utf-8") as f:
                json.dump({"schema":2,"since":self.since,"cycles":self.rows},f,allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp,self.path)
            tmp = None
            self.dirty = False
            self.storage_error = None
        except (OSError,ValueError,TypeError) as e:
            self.storage_error = type(e).__name__
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def summary(self):
        # Never combine unlike setpoints, presets, relay states or owners.
        group = [r for r in self.rows if tuple(r["context"]) == self.context]
        result = {"total":len(self.rows),"cycles":len(group),"since":self.since,
                  "changed":self.change,"context":self.context,"storage_error":self.storage_error,
                  "unsaved":self.dirty,"enough_samples":len(group)>=20,"last_cycle":group[-1] if group else None}
        for sensor in self.SENSORS:
            stats={}
            for edge in ("start","stop"):
                pairs=[[(a+b)/2 for a,b in zip(r[edge]["twi"],r[edge]["two"])] if sensor=="mean"
                       else r[edge][sensor] for r in group]
                mids=[sum(p)/2 for p in pairs]
                center=median(mids) if mids else None
                stats[edge]={"offset":round(center,2),"mad":round(median(abs(x-center) for x in mids),2),
                             "sample_span":round(median(abs(p[1]-p[0]) for p in pairs),2)} if mids else None
            stats["width"]=round(stats["stop"]["offset"]-stats["start"]["offset"],2) if group else None
            result[sensor]=stats
        extended=[r for r in group if "above_seconds" in r]
        def med(values):
            values=list(values)
            return round(median(values),2) if values else None
        outdoor=[r["stop"]["outdoor"][0] for r in group if r["stop"].get("outdoor",[None])[0] is not None]
        result["extended"]={"cycles":len(extended),
            "stop_outdoor":med(outdoor),"outdoor_min":min(outdoor) if outdoor else None,
            "outdoor_max":max(outdoor) if outdoor else None,
            "stop_fact":med(r["stop"]["fact"][0] for r in group if "fact" in r["stop"]),
            "stop_fset":med(r["stop"]["fset"][0] for r in group if "fset" in r["stop"]),
            "stop_water_delta":med(r["stop"]["two"][0]-r["stop"]["twi"][0] for r in group),
            "run_seconds":med(r["run_seconds"] for r in extended),
            "above_seconds":{k:{str(b):med(r["above_seconds"][k][str(b)] for r in extended)
                                for b in self.BANDS} for k in self.SENSORS}}
        return result
