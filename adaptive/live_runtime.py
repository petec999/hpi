"""Conservative opt-in integration with Stable. No changes to heat demand or setpoints."""
import threading
import time
import math
from adaptive.regulator import Regulator, Sample, LEVELS

class Runtime:
    MAX_AGE=60
    PERIOD=30
    SIZES={"R101":6,"R141":16,"R201":1,"R241":22}
    def __init__(self,g):
        self.g=g
        self.lock=threading.RLock()
        self.serial_lock=threading.RLock()
        self.frames_lock=threading.Lock()
        self.frames={}
        self.control="legacy"
        self.reg=Regulator()
        self.last_tick=0
        self.pending=None
        self.status={"reason":"Legacy; no adaptive writes","risk":"paused"}
        self.fault=None
        self.invalid_since=None
        self.reported_ready=False

    def note(self,key,regs):
        # Separate lock: never hold controller lock in the serial reader.
        with self.frames_lock:
            if len(regs)==self.SIZES[key]:
                self.frames[key]=(time.monotonic(),tuple(regs))
            else:
                self.frames.pop(key,None)

    def raw(self,key):
        return self.g.get("statusdict",{}).get(key,{}).get("value")

    @staticmethod
    def flag(v):
        if v in (True,1,"1","on","ON"):
            return True
        if v in (False,0,"0","off","OFF"):
            return False
        raise ValueError("unknown boolean state")

    @staticmethod
    def number(v):
        if isinstance(v,bool):
            raise ValueError("invalid numeric data")
        n=float(v)
        if not math.isfinite(n):
            raise ValueError("nonfinite data")
        return n

    def snapshot(self):
        now=time.monotonic()
        with self.frames_lock:
            f=dict(self.frames)
        if set(f)!=set(self.SIZES) or any(not 0<=now-t<=self.MAX_AGE for t,_ in f.values()):
            raise ValueError("waiting for four recent complete frames")
        a,b,c,d=(list(f[k][1]) for k in ("R101","R141","R201","R241"))
        p=self.g["PyHaier"]
        target=self.number(p.GetCHTemp(a))
        water=p.GetTwiTwo(b)
        ci=p.GetCompInfo(d)
        mode=str(p.GetMode(c)).lower()
        if mode not in ("quiet","eco","turbo"):
            raise ValueError("unknown preset readback")
        relay=self.flag(self.g["GPIO"].input(self.g["freqlimitpin"]))
        power=int(a[0])&255
        heating=bool(power&1 and power&4 and not power&2) and self.flag(self.g["GPIO"].input(self.g["heatdemandpin"]))
        valve=str(p.Get3way(b)).upper()
        if valve not in ("CH","DHW"):
            raise ValueError("unknown valve")
        defrost=str(p.GetDefrost(b)).upper()
        frost=str(p.GetAntifreeze(b)).upper()
        # Existing decoders return textual flags; unknown values fail closed.
        if defrost not in ("DEFROST","NORMAL","OFF","ON","0","1","NO DEFROST","NODEFROST","NOT DEFROST"):
            # Cross-check decoded status rather than accepting an unknown token.
            defrost_on=self.flag(self.raw("defrost"))
            if defrost_on!=(defrost=="DEFROST"):
                raise ValueError("defrost disagreement")
        else:
            defrost_on=defrost in ("DEFROST","ON","1")
        frost_on=frost=="ANTIFREEZE" or self.flag(self.raw("antifreeze"))
        override=any(self.flag(self.raw(k)) for k in
                     ("service_set_pump","service_set_heater","antifreeze_custom",
                      "anti_legionella_active","ch_cooling"))
        override=override or frost_on or bool(self.g.get("_dhwwl_active")) or bool(self.g.get("_tz_forcing_flimit"))
        # Guard native CH enable and operating state independently.
        heating=heating and self.flag(self.raw("ch_heating"))
        error=self.number(p.GetError(b))
        if error!=int(error):
            raise ValueError("invalid error")
        s=Sample(now,target,self.number(water[0]),self.number(water[1]),
                 self.number(ci[1]),self.number(ci[0]),mode,relay,heating,
                 defrost_on,True,int(error),valve=="DHW",override)
        zone=self.g["get_temp_zone"](self.raw("outtemp"))
        if zone not in ("normal","frost","warm"):
            raise ValueError("invalid zone")
        curve=self.number(self.raw("hcurve"))
        return s,zone,curve,f["R201"][0]

    def priority(self):
        try:
            s,zone,_,_=self.snapshot()
            return s.dhw or s.defrost or s.override or s.error!=0 or zone!="normal"
        except Exception:
            return True

    def legacy(self,kind,value,zone=None):
        with self.lock:
            # Explicit outdoor-zone presets remain authoritative.
            if self.control in ("legacy","shadow") or zone in ("frost","warm"):
                if zone in ("frost","warm") and self.control=="auto":
                    self.pending=None
                    self.reg.reset()
                return self.g["new_presetchange" if kind=="preset" else "flimitchange"](value)
            return ("Adaptive owns output",False if kind=="preset" else "error")

    def priority_write(self,kind,value):
        with self.lock:
            if self.control=="auto":
                self.pending=None
                self.reg.reset()
            return self.g["new_presetchange" if kind=="preset" else "flimitchange"](value)

    def legacy_tick(self,name,*args):
        with self.lock:
            if self.control in ("legacy","shadow"):
                return self.g[name](*args)

    def manual(self,kind,value):
        with self.lock:
            if self.control in ("manual","auto"):
                if self.priority() or self.pending is not None:
                    return ("Priority operation or pending readback",False if kind=="preset" else "error")
                self.control="manual"
                self.reg=Regulator()
            return self.g["new_presetchange" if kind=="preset" else "flimitchange"](value)

    def choose(self,mode,expected):
        with self.lock:
            if mode not in ("legacy","manual","shadow","auto") or expected!=self.control:
                raise ValueError("control selection changed")
            if self.pending is not None:
                # Disarm immediately, but do not send competing commands.
                if mode in ("manual","shadow"):
                    self.control="manual"
                    return
                raise ValueError("waiting for pending command")
            if mode=="auto":
                s,zone,curve,_=self.snapshot()
                if zone!="normal" or s.dhw or s.defrost or s.override or s.error or abs(curve-s.target)>1:
                    raise ValueError("automatic control not ready")
                if str(self.g.get("flimit")).lower()!="auto" or str(self.g.get("presetautochange")).lower()!="auto":
                    raise ValueError("set original FLimit and preset policy to auto first")
            self.control=mode
            self.fault=None
            self.invalid_since=None
            self.reg=Regulator()
            self.status={"reason":"control selected: "+mode,"risk":"paused"}

    def fail(self,reason):
        self.control="manual"
        self.reg=Regulator()
        self.fault=reason
        self.status={"reason":reason,"risk":"paused"}
        self.g["logging"].warning("Adaptive modulation disarmed: %s",reason)

    def tick(self):
        now=time.monotonic()
        if now-self.last_tick<self.PERIOD:
            return
        if not self.lock.acquire(blocking=False):
            return
        try:
            self.last_tick=now
            if not self.reported_ready:
                with self.frames_lock:
                    good=set(self.frames)==set(self.SIZES) and all(0<=now-t<=self.MAX_AGE for t,_ in self.frames.values())
                if good:
                    self.g["logging"].info("Adaptive integration: four complete recent frames")
                    self.reported_ready=True
            if self.control=="legacy" and self.pending is None:
                return
            try:
                s,zone,curve,stamp=self.snapshot()
            except Exception as e:
                self.reg.reset()
                if self.invalid_since is None:
                    self.invalid_since=now
                if self.pending and now>self.pending[2]:
                    self.pending=None
                    self.fail("command readback unavailable")
                elif self.control=="auto" and now-self.invalid_since>=180:
                    self.fail("telemetry lost; manual hold")
                else:
                    self.status={"reason":str(e),"risk":"paused"}
                return
            self.invalid_since=None
            if self.pending:
                mode,relay,deadline,issued=self.pending
                if (s.mode,s.relay)==(mode,relay) and stamp>issued:
                    self.pending=None
                elif now>deadline:
                    self.pending=None
                    self.fail("command readback did not match")
                    return
                else:
                    self.status={"reason":"waiting for confirmed preset and relay","risk":"paused"}
                    return
            if self.control=="manual":
                if self.fault is None:
                    self.status={"reason":"manual control; no adaptive writes","risk":"paused"}
                return
            if zone!="normal" or s.dhw or s.defrost or s.override or s.error or abs(curve-s.target)>1:
                self.reg.reset()
                self.status={"reason":"priority zone, protection, DHW or setpoint mismatch","risk":"paused"}
                return
            if self.control=="auto" and (str(self.g.get("flimit")).lower()!="auto" or
                                       str(self.g.get("presetautochange")).lower()!="auto"):
                self.fail("original automatic policy setting changed")
                return
            d=self.reg.step(s,control=self.control)
            label=lambda i: None if i is None else LEVELS[i][0]+("+FLimit" if LEVELS[i][1] else "")
            self.status={"reason":d.reason,"risk":d.risk,"actual":label(d.current),
                         "proposed":label(d.proposed),"target":s.target,
                         "supply_error":d.supply_error,"forecast":d.predicted_surplus,
                         "deficit_integral":d.deficit_integral}
            if self.control!="auto" or d.proposed==d.current or d.proposed is None:
                return
            # Re-read immediately, and serialize against legacy set_newframe callers.
            with self.serial_lock:
                current,z,actual_target,_=self.snapshot()
                if z!="normal" or current.override or current.defrost or current.dhw or current.error or not current.heating or current.hz<=0 or current.requested_hz<=0 or (current.mode,current.relay)!=(s.mode,s.relay) or abs(current.target-s.target)>0.25 or abs(actual_target-current.target)>1 or self.g.get("newframe"):
                    return
                mode,relay=LEVELS[d.proposed]
                issued=time.monotonic()
                self.pending=(mode,relay,issued+90,issued)
                if mode!=s.mode:
                    _,ok=self.g["new_presetchange"](mode)
                    if ok is not True:
                        self.fail("preset write not acknowledged; waiting for readback")
                elif relay!=s.relay:
                    _,ok=self.g["flimitchange"]("1" if relay else "0")
                    if ok!="success" or self.flag(self.g["GPIO"].input(self.g["freqlimitpin"]))!=relay:
                        self.fail("FLimit GPIO readback mismatch")
                else:
                    self.pending=None
            self.g["logging"].info("Adaptive proposal issued: %s",self.status)
        except Exception:
            self.g["logging"].exception("Adaptive modulation tick failed")
            self.fail("controller exception")
        finally:
            self.lock.release()

    def view(self):
        with self.lock:
            try:
                s,zone,curve,_=self.snapshot()
                actual=s.mode
                relay="1" if s.relay else "0"
                ready=(zone=="normal" and not (s.dhw or s.defrost or s.override or s.error) and abs(curve-s.target)<=1)
            except Exception:
                actual=relay=zone=None
                ready=False
            return dict(self.status,control=self.control,mode=actual,relay=relay,
                        ready=ready,zone=zone,pending=self.pending is not None,fault=self.fault)
