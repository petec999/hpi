"""Experimental anti-cycling supervisory policy. Pure proposals, no I/O."""
from dataclasses import dataclass
from collections import deque
from statistics import median
import math

# Indices are identifiers, NOT a measured total ordering of capacity.
LEVELS=(("quiet",True),("quiet",False),("eco",False),("turbo",False),
        ("eco",True),("turbo",True))
PRESETS=("quiet","eco","turbo")

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
    probe_after: float=900
    failed_retry: float=1800
    trial_window: float=900
    forecast_min: float=3
    deficit_band: float=0.5
    surplus_band: float=0.6
    urgent_deficit: float=2
    integral_limit: float=4  # K*min, not thermal energy
    trend_band: float=0.08
    probe_hz: float=30  # experimental opt-out threshold, not factory minimum

@dataclass(frozen=True)
class Decision:
    current: int
    proposed: int
    reason: str
    delta: float=None  # legacy return deficit, diagnostic only
    trend: float=None  # return deficit K/min
    supply_error: float=None
    supply_trend: float=None
    predicted_surplus: float=None
    deficit_integral: float=0
    risk: str="paused"
    blocked_seconds: float=0

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
               and not s.override and s.error==0 and s.hz>0 and s.requested_hz>=0
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
        # Leaky deficit integral; normal water-side delta T is not a deficit.
        self.integral=max(0,min(30,self.integral+(max(0,es-0.2) if es>0.2 else -0.8)*dt))
        if len(rows)<3 or now-rows[0][0]<90:
            return Decision(level,level,"collecting samples",er,supply_error=es,deficit_integral=self.integral)
        ts=trend(rows,1)
        tr=trend(rows,2)
        forecast=-es-max(-0.5,min(0.5,ts))*c.forecast_min
        def decision(proposed,reason,risk,blocked=0):
            return Decision(level,proposed,reason,er,tr,es,ts,forecast,self.integral,risk,blocked)
        urgent=es>=c.urgent_deficit and ts>=-c.trend_band
        shortfall=(es>c.deficit_band and ts>=-c.trend_band) or (es>0.3 and self.integral>=c.integral_limit)
        # Rising supply above/near target, supported by the return trend.
        # This is an overshoot proxy, not a known factory shutoff threshold.
        excess=(es<=-c.surplus_band and ts<=c.trend_band) or (
            es<=0.2 and forecast>=c.surplus_band and ts<-c.trend_band and tr<=c.trend_band)
        settled=now-self.ready_since>=c.startup_hold and now-self.changed_at>=c.settle_hold
        stable_probe=(now-self.ready_since>=c.probe_after and abs(es)<=0.3 and
                      abs(ts)<=c.trend_band and abs(tr)<=c.trend_band and
                      median(x[3] for x in rows)>=c.probe_hz and
                      abs(median(x[3]-x[4] for x in rows))<=2)
        if self.trial and now-self.trial[2]>c.trial_window:
            self.trial=None
        direction=None
        risk="balanced"
        if urgent or shortfall:
            direction="up"
            risk="shortfall"
            # Urgent deficits may bypass the normal settling hold but still need confirmation.
            if not urgent and now-self.changed_at<c.settle_hold:
                direction=None
        elif settled and (excess or stable_probe):
            direction="down"
            risk="surplus" if excess else "efficiency_probe"
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
        required=c.urgent_confirm if direction=="up" and urgent else c.up_confirm if direction=="up" else c.down_confirm
        if now-self.candidate_since<required:
            self.last_offer=None
            return decision(level,"confirming "+risk,risk)
        if direction=="up" and self.trial and self.trial[1]==level:
            self.blocked[(self.trial[0],level)]=now+c.failed_retry
            self.trial=None
            reason="restore previous capacity; reduction failed"
        else:
            reason="increase available capacity" if direction=="up" else "reduce before overshoot" if excess else "probe lower capacity"
        self.last_offer=(level,proposed,direction,now)
        return decision(proposed,reason,risk)
