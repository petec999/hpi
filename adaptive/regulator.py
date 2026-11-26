"""Experimental read-only supervisory modulation policy; never writes hardware."""
from dataclasses import dataclass
from collections import deque
from statistics import median
import math

# These are candidate capacity envelopes, not guaranteed compressor frequencies.
LEVELS=(("quiet",True),("quiet",False),("eco",False),("turbo",False))

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
    thresholds: tuple=(1.5,2.8,4.0)
    hysteresis: float=0.4
    startup_hold: float=300
    settle_hold: float=300
    up_confirm: float=120
    down_confirm: float=300
    window: float=120
    max_gap: float=65
    trend_deadband: float=0.12  # K/min; candidate value
    emergency_delta: float=6.0  # accelerated release of a capacity constraint

@dataclass(frozen=True)
class Decision:
    current: int
    proposed: int
    reason: str
    delta: float=None
    trend: float=None
    # This module cannot authorize actual actuation.

class Regulator:
    def __init__(self,settings=Settings()):
        self.cfg=settings
        t=settings.thresholds
        if len(t)!=3 or not all(math.isfinite(x) for x in t) or not 0<t[0]<t[1]<t[2]:
            raise ValueError("Thresholds must increase")
        if not 0<settings.hysteresis<min(t[1]-t[0],t[2]-t[1])/2:
            raise ValueError("Invalid hysteresis")
        if not all(math.isfinite(x) and x>0 for x in (settings.startup_hold,settings.settle_hold,settings.up_confirm,settings.down_confirm,settings.window,settings.max_gap,settings.trend_deadband,settings.emergency_delta)):
            raise ValueError("Invalid timing or trend settings")
        self.history=deque()
        self.last=None
        self.ready_since=None
        self.level=None
        self.changed_at=None
        self.candidate=None
        self.candidate_since=None
        self.target=None

    def reset(self):
        self.history.clear()
        self.ready_since=None
        self.candidate=None
        self.candidate_since=None

    def step(self,s,control="shadow",floor=0,ceiling=3):
        if control not in ("manual","legacy","shadow","auto"):
            raise ValueError("Unknown control")
        if not 0<=floor<=ceiling<=3:
            raise ValueError("Invalid bounds")
        try:
            level=LEVELS.index((s.mode,s.relay))
        except ValueError:
            self.reset()
            return Decision(None,None,"unrecognized capacity combination")
        if control in ("manual","legacy"):
            self.reset()
            self.last=None
            self.level=None
            return Decision(level,level,"external control owns outputs")
        finite=all(isinstance(x,(int,float)) and math.isfinite(x) for x in
                   (s.now,s.target,s.return_temp,s.supply_temp,s.hz,s.requested_hz))
        valid=(finite and s.fresh and s.heating and not s.defrost and not s.dhw
               and not s.override and s.error==0 and s.hz>0 and s.requested_hz>=0
               and 10<=s.target<=65 and -10<=s.return_temp<=85 and -10<=s.supply_temp<=85)
        if not valid:
            self.reset()
            self.last=None
            return Decision(level,level,"paused: operating state or data invalid")
        now=s.now
        if self.last is not None and (now<=self.last or now-self.last>self.cfg.max_gap):
            self.reset()
        self.last=now
        if self.target is None or abs(self.target-s.target)>=0.25:
            self.reset()
            self.target=s.target
        if level!=self.level:
            self.reset()
            self.level=level
            self.changed_at=now
        if self.ready_since is None:
            self.ready_since=now
        self.history.append((now,s.target-s.return_temp))
        while self.history and now-self.history[0][0]>self.cfg.window:
            self.history.popleft()
        d=median(v for _,v in self.history)
        span=now-self.history[0][0]
        if span<self.cfg.window*0.75 or len(self.history)<3:
            return Decision(level,level,"collecting samples",d)
        mid=len(self.history)//2
        first=list(self.history)[:mid]
        last=list(self.history)[mid:]
        dt=median(t for t,_ in last)-median(t for t,_ in first)
        trend=(median(v for _,v in last)-median(v for _,v in first))*60/dt if dt>0 else 0
        cfg=self.cfg
        # Never step down during startup, after defrost or a recent mode change.
        # Urgent shortfall can release one constraint after fresh samples.
        urgent=d>=cfg.emergency_delta and trend>=-cfg.trend_deadband
        if now-self.ready_since<cfg.startup_hold and not urgent:
            return Decision(level,level,"startup or recovery settling",d,trend)
        if self.changed_at is not None and now-self.changed_at<cfg.settle_hold and not urgent:
            return Decision(level,level,"waiting for actual mode response",d,trend)
        proposed=level
        if level<floor:
            proposed=level+1
        elif level>ceiling:
            proposed=level-1
        elif level<ceiling and (urgent or (d>cfg.thresholds[level]+cfg.hysteresis and trend>=-cfg.trend_deadband)):
            proposed=level+1
        elif level>floor and d<cfg.thresholds[level-1]-cfg.hysteresis and trend<=cfg.trend_deadband:
            proposed=level-1
        if proposed==level:
            self.candidate=None
            self.candidate_since=None
            return Decision(level,level,"hold: sufficient or recovering",d,trend)
        if self.candidate!=proposed:
            self.candidate=proposed
            self.candidate_since=now
        required=(cfg.up_confirm if proposed>level else cfg.down_confirm)
        if urgent and proposed>level:
            required=0
        if now-self.candidate_since<required:
            return Decision(level,level,"confirming sustained demand",d,trend)
        return Decision(level,proposed,"increase available capacity" if proposed>level else "reduce available capacity",d,trend)
