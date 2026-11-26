"""Conservative opt-in integration with Stable. No changes to heat demand or setpoints."""
import threading
import time
import math
import os
import tempfile
from pathlib import Path
from adaptive.regulator import Regulator, Sample, LEVELS, Learning, STOP_HYSTERESIS, HysteresisObserver

class SelectionBlocked(ValueError):
    """Safe, fixed activation reason exposed to authenticated UI."""

class Runtime:
    MAX_AGE=60
    PERIOD=30
    EXPERIMENT_LEVELS=(("eco",False),("quiet",False),("quiet",True),("eco",True),("turbo",True),("turbo",False))
    EXPERIMENT_CYCLES=3
    EXPERIMENT_TIMEOUT=7*86400
    SIZES={"R101":6,"R141":16,"R201":1,"R241":22}
    def __init__(self,g,learning_path=None):
        self.g=g
        self.lock=threading.RLock()
        self.serial_lock=threading.RLock()
        self.frames_lock=threading.Lock()
        self.frames={}
        self.control="legacy"
        self.reg=Regulator()
        self.learning=Learning(learning_path,g.get("logging"))
        self.learning_before=None
        observer_path=Path(learning_path).with_name(".adaptive-hysteresis-v1.json") if learning_path else None
        self.observer=HysteresisObserver(observer_path,g.get("logging"))
        self.observer_frames=None
        self.experiment_since=None
        self.experiment_started=None
        self.experiment_idle=None
        self.experiment_initial=None
        self.last_tick=0
        self.pending=None
        self.status={"reason":"Legacy; no adaptive writes","risk":"paused"}
        self.fault=None
        self.invalid_since=None
        self.ready_log_frames=None
        self.ready_log_count=0
        self.idle_frame=None

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

    def gpio(self,pin):
        value=self.g["GPIO"].input(self.g[pin])
        if type(value) is not str or value not in ("0","1"):
            raise ValueError("GPIO readback unavailable: "+pin)
        return value=="1"

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
        relay=self.gpio("freqlimitpin")
        power=int(a[0])&255
        heating=bool(power&1 and power&4 and not power&2) and self.gpio("heatdemandpin")
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
        zone=self.g["get_temp_zone"](self.number(self.raw("outtemp")))
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
                if zone in ("frost","warm") and self.control=="experiment":
                    self.fail("experiment interrupted by priority zone")
                if zone in ("frost","warm") and self.control=="auto":
                    self.idle_frame=None
                    self.pending=None
                    self.learning.cancel()
                    self.learning_before=None
                    self.reg.reset()
                return self.g["new_presetchange" if kind=="preset" else "flimitchange"](value)
            return ("Adaptive owns output",False if kind=="preset" else "error")

    def priority_write(self,kind,value):
        with self.lock:
            if self.control=="experiment":
                self.fail("experiment interrupted by priority write")
            if self.control=="auto":
                self.idle_frame=None
                self.pending=None
                self.learning.cancel()
                self.learning_before=None
                self.reg.reset()
            return self.g["new_presetchange" if kind=="preset" else "flimitchange"](value)

    def legacy_tick(self,name,*args):
        with self.lock:
            if self.control in ("legacy","shadow"):
                return self.g[name](*args)

    def manual(self,kind,value):
        with self.lock:
            if self.control in ("manual","auto","experiment"):
                if self.priority() or self.pending is not None:
                    return ("Priority operation or pending readback",False if kind=="preset" else "error")
                self.control="manual"
                self.idle_frame=None
                self.learning.cancel()
                self.learning_before=None
                self.reg=Regulator()
            return self.g["new_presetchange" if kind=="preset" else "flimitchange"](value)

    @staticmethod
    def activation_reason(s,zone,curve):
        if s.error:
            return "Aktywny błąd pompy"
        if s.dhw:
            return "Trwa grzanie CWU"
        if s.defrost:
            return "Trwa odszranianie"
        if s.override:
            return "Aktywna funkcja ochronna lub serwisowa"
        if zone!="normal":
            return "Wymuszona strefa temperatury zewnętrznej"
        if abs(curve-s.target)>1:
            return "Nastawa pompy różni się od krzywej o ponad 1 K"
        if not (10<=s.target<=65 and -10<=s.supply_temp<=85 and -10<=s.return_temp<=85):
            return "Temperatury poza zakresem regulatora"
        return None

    def choose(self,mode,expected):
        with self.lock:
            if mode not in ("legacy","manual","shadow","auto","experiment") or expected!=self.control:
                raise SelectionBlocked("Stan sterowania zmienił się; odśwież panel")
            if self.pending is not None:
                # Disarm immediately, but do not send competing commands.
                if mode in ("manual","shadow"):
                    self.control="manual"
                    return
                raise SelectionBlocked("Oczekiwanie na potwierdzenie poprzedniego polecenia")
            if mode in ("auto","experiment"):
                try:
                    s,zone,curve,_=self.snapshot()
                except Exception:
                    raise SelectionBlocked("Brak pełnego, świeżego odczytu pompy lub GPIO") from None
                reason=self.activation_reason(s,zone,curve)
                if reason:
                    raise SelectionBlocked(reason)
                # The Adaptive owner gates legacy CO writers. Stored legacy
                # preset/FLimit policies remain untouched for a return to Legacy.
            self.control=mode
            self.observer.interrupt()
            self.experiment_idle=None
            if mode=="experiment":
                self.experiment_since=time.time()
                self.experiment_started=time.monotonic()
                self.experiment_initial=(s.mode,s.relay)
            self.learning.cancel()
            self.learning_before=None
            self.fault=None
            self.invalid_since=None
            self.reg=Regulator()
            self.idle_frame=None
            self.status={"reason":"control selected: "+mode,"risk":"paused"}

    def fail(self,reason):
        self.learning.cancel()
        self.learning_before=None
        self.control="manual"
        self.reg=Regulator()
        self.fault=reason
        self.status={"reason":reason,"risk":"paused"}
        self.g["logging"].warning("Adaptive modulation disarmed: %s",reason)

    @staticmethod
    def display_reason(s,reason):
        # Presentation only: never change the decision, thresholds or timing.
        if reason=="collecting samples":
            return "Zbieranie pomiarów – oczekiwanie na stabilny odczyt"
        if reason!="paused: operating state or data invalid":
            return reason
        values=(s.now,s.target,s.return_temp,s.supply_temp,s.hz,s.requested_hz)
        if not s.fresh or not all(type(v) in (int,float) and math.isfinite(v) for v in values):
            return "Brak aktualnych lub poprawnych pomiarów"
        if not (10<=s.target<=65 and -10<=s.return_temp<=85 and -10<=s.supply_temp<=85) or min(s.hz,s.requested_hz)<0:
            return "Pomiary poza zakresem regulatora"
        if s.error:
            return "Aktywny błąd pompy"
        if s.defrost:
            return "Odszranianie – regulacja wstrzymana"
        if s.dhw:
            return "Grzanie CWU – regulacja CO wstrzymana"
        if s.override:
            return "Aktywna funkcja ochronna lub serwisowa"
        if s.hz==0:
            return "Postój sprężarki – oczekiwanie na wznowienie ogrzewania"
        if s.requested_hz==0:
            return "Pompa kończy pracę – oczekiwanie na wznowienie ogrzewania"
        if not s.heating:
            return "Brak aktywnego ogrzewania CO"
        return "Oczekiwanie na poprawny stan pracy pompy"

    def idle_snapshot_valid(self,s,zone,curve):
        # A stopped compressor is not necessarily a stopped heating system.
        # Require CH enabled (R101 + pch), not ch_heating (active operation)
        # or heat demand GPIO. Real idle telemetry reports ch_heating=off.
        # Never change mode in cooling, off, DHW, protection or priority zones.
        with self.frames_lock:
            stamp,frame=self.frames["R101"]
            idle_stamp=self.frames["R241"][0]
        power=int(frame[0])&255
        return (self.activation_reason(s,zone,curve) is None and s.fresh
                and s.hz==0 and s.requested_hz==0
                and bool(power&1 and power&4 and not power&2)
                and self.flag(self.raw("pch"))
                and 0<=time.monotonic()-stamp<=self.MAX_AGE
                and 0<=time.monotonic()-idle_stamp<=self.MAX_AGE)

    def prepare_idle(self,s,zone,curve):
        # Only called in Auto/Shadow, before the normal running policy.
        # Two distinct consecutive stopped samples; one output per command.
        # Native compressor start/stop, setpoint and demand remain untouched.
        if not self.idle_snapshot_valid(s,zone,curve):
            self.idle_frame=None
            return False
        with self.frames_lock:
            frame=self.frames["R241"][0]
        previous=self.idle_frame
        self.idle_frame=frame
        self.learning.cancel()
        self.learning_before=None
        self.reg.reset()
        mode,relay=("quiet",True)
        actual=s.mode+("+FLimit" if s.relay else "")
        proposed="quiet+FLimit"
        reason="Postój sprężarki – przygotowanie Quiet + FLimit"
        if (s.mode,s.relay)==(mode,relay):
            reason="Postój sprężarki – Quiet + FLimit gotowe do startu"
        elif previous is None or not 0<frame-previous<=self.MAX_AGE:
            reason="Postój sprężarki – potwierdzanie postoju przed przygotowaniem"
        self.status={"reason":"idle startup preparation","reason_pl":reason,
                     "risk":"paused","actual":actual,"proposed":proposed,
                     "target":s.target,"return_temp":s.return_temp,"stop_target":s.target+STOP_HYSTERESIS,
                     "stop_margin":s.target+STOP_HYSTERESIS-s.return_temp,"down_confirm":self.reg.cfg.down_confirm,
                     "surplus_band":self.reg.cfg.surplus_band}
        if self.control!="auto" or (s.mode,s.relay)==(mode,relay) or previous is None or not 0<frame-previous<=self.MAX_AGE:
            return True
        with self.serial_lock:
            current,z,actual_target,_=self.snapshot()
            if (not self.idle_snapshot_valid(current,z,actual_target)
                    or (current.mode,current.relay)!=(s.mode,s.relay)
                    or abs(current.target-s.target)>0.25 or self.g.get("newframe")):
                return True
            # Enable frequency limit first; only then set Quiet.
            # Do not train the running policy on changes made at zero Hz.
            mode,relay=(current.mode,True) if not current.relay else ("quiet",True)
            issued=time.monotonic()
            self.pending=(mode,relay,issued+90,issued)
            if not current.relay:
                _,ok=self.g["flimitchange"]("1")
                if ok!="success" or self.gpio("freqlimitpin")!=relay:
                    self.fail("idle FLimit GPIO readback mismatch")
            else:
                _,ok=self.g["new_presetchange"](mode)
                if ok is not True:
                    self.fail("idle preset write not acknowledged")
            self.g["logging"].info("Adaptive idle preparation issued: %s / FLimit %s",mode,relay)
        return True

    def observe_hysteresis(self):
        # Separate from regulation; failures must never influence commands.
        try:
            s,zone,curve,_=self.snapshot()
            with self.frames_lock:
                stamps=tuple(self.frames[k][0] for k in ("R101","R141","R201","R241"))
                power=int(self.frames["R101"][1][0])&255
            if self.observer_frames is not None and not all(a>b for a,b in zip(stamps,self.observer_frames)):
                if max(stamps)-min(stamps)>self.MAX_AGE:
                    self.observer.interrupt()
                return
            self.observer_frames=stamps
            eligible=(self.activation_reason(s,zone,curve) is None
                      and bool(power&1 and power&4 and not power&2)
                      and self.flag(self.raw("pch")) and self.gpio("heatdemandpin")
                      and self.pending is None)
            try:
                outdoor=self.number(self.raw("outtemp"))
            except (TypeError,ValueError):
                outdoor=None
            self.observer.observe(s,self.control,eligible,time.time(),outdoor=outdoor)
        except Exception:
            self.observer.interrupt()
        finally:
            self.observer.save_if_due(time.monotonic())

    def experiment_counts(self):
        counts=[0]*len(self.EXPERIMENT_LEVELS)
        if self.experiment_since is not None:
            for row in self.observer.rows:
                c=row["context"]
                if c[0]=="experiment" and row["start"]["at"]>=self.experiment_since:
                    pair=tuple(c[1:3])
                    if pair in self.EXPERIMENT_LEVELS:
                        counts[self.EXPERIMENT_LEVELS.index(pair)]+=1
        return counts

    def experiment_tick(self,s,zone,curve):
        # Opt-in, native idle only. Never change demand, water target or Fset.
        counts=self.experiment_counts()
        idx=next((i for i,n in enumerate(counts) if n<self.EXPERIMENT_CYCLES),None)
        expired=self.experiment_started is None or s.now-self.experiment_started>=self.EXPERIMENT_TIMEOUT
        done=idx is None or expired
        goal=self.experiment_initial if done else self.EXPERIMENT_LEVELS[idx]
        actual=(s.mode,s.relay)
        label=lambda x:x[0]+("+FLimit" if x[1] else " / FLimit OFF")
        self.status={"reason":"experiment: passive during active cycle","reason_pl":"Eksperyment – obserwacja cyklu, bez zmian podczas pracy",
                     "risk":"paused","actual":label(actual),"proposed":label(goal),"target":s.target,
                     "return_temp":s.return_temp}
        if self.activation_reason(s,zone,curve) is not None or not self.gpio("heatdemandpin"):
            self.experiment_idle=None
            self.status["reason_pl"]="Eksperyment wstrzymany – warunek priorytetowy lub brak zapotrzebowania"
            return
        if not self.idle_snapshot_valid(s,zone,curve):
            self.experiment_idle=None
            return
        with self.frames_lock:
            stamp=self.frames["R241"][0]
        if self.experiment_idle is None:
            self.experiment_idle=(stamp,stamp)
            return
        first,previous=self.experiment_idle
        if stamp<=previous or stamp-previous>self.MAX_AGE:
            if stamp-previous>self.MAX_AGE:
                self.experiment_idle=(stamp,stamp)
            return
        self.experiment_idle=(first,stamp)
        if stamp-first<60 or self.observer.stop is not None:
            return
        if actual==goal:
            if done:
                self.control="manual"
                self.status["reason_pl"]="Eksperyment zakończony – przywrócono konfigurację początkową"
            else:
                self.status["reason_pl"]="Eksperyment – konfiguracja gotowa, oczekiwanie na naturalny START"
            return
        with self.serial_lock:
            current,z,target,_=self.snapshot()
            if (not self.idle_snapshot_valid(current,z,target) or not self.gpio("heatdemandpin")
                    or (current.mode,current.relay)!=actual or abs(current.target-s.target)>0.25
                    or self.g.get("newframe")):
                return
            # One output at a time; enable limit first if needed, then preset,
            # then remove limit if needed. No writes in Shadow.
            mode,relay=actual
            if goal[1] and not relay:
                relay=True
            elif mode!=goal[0]:
                mode=goal[0]
            else:
                relay=goal[1]
            issued=time.monotonic()
            self.pending=(mode,relay,issued+90,issued)
            self.observer.interrupt()
            self.experiment_idle=None
            if mode!=actual[0]:
                _,ok=self.g["new_presetchange"](mode)
                if ok is not True:
                    self.fail("experiment preset write not acknowledged")
            else:
                _,ok=self.g["flimitchange"]("1" if relay else "0")
                if ok!="success" or self.gpio("freqlimitpin")!=relay:
                    self.fail("experiment FLimit readback mismatch")
            self.g["logging"].info("Hysteresis experiment issued: %s / FLimit %s",mode,relay)

    def tick(self):
        now=time.monotonic()
        if now-self.last_tick<self.PERIOD:
            return
        if not self.lock.acquire(blocking=False):
            return
        try:
            self.last_tick=now
            self.learning.save_if_due(now)
            if self.control not in ("auto","shadow"):
                self.idle_frame=None
            if self.control!="auto":
                self.learning.cancel()
                self.learning_before=None
            if self.ready_log_count<3:
                with self.frames_lock:
                    stamps={k:t for k,(t,_) in self.frames.items()}
                good=set(stamps)==set(self.SIZES) and all(0<=now-t<=self.MAX_AGE for t in stamps.values())
                if good and (self.ready_log_frames is None or
                             all(t>self.ready_log_frames[k] for k,t in stamps.items())):
                    self.g["logging"].info("Adaptive integration: four complete recent frames")
                    self.ready_log_frames=stamps
                    self.ready_log_count+=1
            self.observe_hysteresis()
            if self.control=="legacy" and self.pending is None:
                return
            try:
                s,zone,curve,stamp=self.snapshot()
            except Exception as e:
                self.idle_frame=None
                self.learning.cancel()
                self.learning_before=None
                self.reg.reset()
                if self.invalid_since is None:
                    self.invalid_since=now
                if self.pending and now>self.pending[2]:
                    self.pending=None
                    self.fail("command readback unavailable")
                elif self.control in ("auto","experiment") and now-self.invalid_since>=180:
                    self.fail("telemetry lost; manual hold")
                else:
                    self.status={"reason":str(e),"risk":"paused"}
                return
            self.invalid_since=None
            if self.pending:
                mode,relay,deadline,issued=self.pending
                if (s.mode,s.relay)==(mode,relay) and stamp>issued:
                    self.pending=None
                    before=self.learning_before
                    self.learning_before=None
                    if before is not None and self.control=="auto":
                        original,outdoor=before
                        current_outdoor=self.number(self.raw("outtemp"))
                        if abs(current_outdoor-outdoor)<=1.5:
                            self.learning.start(original,s,outdoor)
                elif now>deadline:
                    self.pending=None
                    self.fail("command readback did not match")
                    return
                else:
                    self.status={"reason":"waiting for confirmed preset and relay","risk":"paused"}
                    return
            if self.control=="experiment":
                self.experiment_tick(s,zone,curve)
                return
            if self.control=="manual":
                if self.fault is None:
                    self.status={"reason":"manual control; no adaptive writes","risk":"paused"}
                return
            if zone!="normal" or s.dhw or s.defrost or s.override or s.error or abs(curve-s.target)>1:
                self.idle_frame=None
                self.learning.cancel()
                self.learning_before=None
                self.reg.reset()
                self.status={"reason":"priority zone, protection, DHW or setpoint mismatch","risk":"paused"}
                return
            if self.prepare_idle(s,zone,curve):
                return
            if self.control=="auto":
                outdoor=self.number(self.raw("outtemp"))
                self.learning.observe(s,outdoor)
                self.reg.cfg=self.learning.settings(s,outdoor)
            d=self.reg.step(s,control=self.control)
            label=lambda i: None if i is None else LEVELS[i][0]+("+FLimit" if LEVELS[i][1] else "")
            self.status={"reason":d.reason,"reason_pl":self.display_reason(s,d.reason),"risk":d.risk,"actual":label(d.current),
                         "proposed":label(d.proposed),"target":s.target,
                         "supply_error":d.supply_error,"forecast":d.predicted_surplus,
                         "return_temp":s.return_temp,"return_trend":None if d.trend is None else -d.trend,
                         "stop_target":s.target+STOP_HYSTERESIS,"stop_margin":s.target+STOP_HYSTERESIS-s.return_temp,
                         "deficit_integral":d.deficit_integral,
                         "down_confirm":self.reg.cfg.down_confirm,
                         "surplus_band":self.reg.cfg.surplus_band}
            if self.control!="auto" or d.proposed==d.current or d.proposed is None:
                return
            # Re-read immediately, and serialize against legacy set_newframe callers.
            with self.serial_lock:
                current,z,actual_target,_=self.snapshot()
                if z!="normal" or current.override or current.defrost or current.dhw or current.error or not current.heating or current.hz<=0 or current.requested_hz<=0 or (current.mode,current.relay)!=(s.mode,s.relay) or abs(current.target-s.target)>0.25 or abs(actual_target-current.target)>1 or self.g.get("newframe"):
                    return
                mode,relay=LEVELS[d.proposed]
                issued=time.monotonic()
                self.learning.cancel()
                self.learning_before=(s,outdoor)
                self.pending=(mode,relay,issued+90,issued)
                if mode!=s.mode:
                    _,ok=self.g["new_presetchange"](mode)
                    if ok is not True:
                        self.fail("preset write not acknowledged; waiting for readback")
                elif relay!=s.relay:
                    _,ok=self.g["flimitchange"]("1" if relay else "0")
                    if ok!="success" or self.gpio("freqlimitpin")!=relay:
                        self.fail("FLimit GPIO readback mismatch")
                else:
                    self.pending=None
            self.g["logging"].info("Adaptive proposal issued: %s",self.status)
        except Exception:
            self.g["logging"].exception("Adaptive modulation tick failed")
            self.fail("controller exception")
        finally:
            self.lock.release()

    @staticmethod
    def validate_curve(value):
        if not isinstance(value,dict) or set(value)!={"mode","slope","shift","gain","points"}:
            raise ValueError("invalid curve fields")
        if value["mode"] not in ("manual","static","auto","directly"):
            raise ValueError("invalid curve mode")
        def number(v,lo,hi):
            if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:
                raise ValueError("invalid curve number")
            return float(v)
        points=value["points"]
        if not isinstance(points,list) or len(points)!=14:
            raise ValueError("14 curve points required")
        return {"mode":value["mode"],"slope":number(value["slope"],0,5),
                "shift":number(value["shift"],-30,30),"gain":number(value["gain"],0,20),
                "points":[number(v,0,65) for v in points]}

    def curve_settings(self):
        try:
            c=self.g["config"]["SETTINGS"]
            return self.validate_curve({"mode":c["heatingcurve"].strip().lower(),
                "slope":float(c["hcslope"]),"shift":float(c["hcpshift"]),"gain":float(c["hcamp"]),
                "points":[float(v) for v in c["hcman"].split(",")]})
        except (KeyError,ValueError,TypeError,AttributeError,OverflowError):
            return None

    def save_curve(self,value,expected,path="/opt/config.ini"):
        # Same config keys and reload path as Stable. Atomic replacement, not a
        # series of partially applied writes. No change to unrelated settings.
        import configparser
        with self.lock:
            value=self.validate_curve(value)
            expected=self.validate_curve(expected)
            if value["mode"]=="directly" or expected["mode"]=="directly":
                raise SelectionBlocked("Edycja krzywej wymaga trybu ogrzewania krzywą")
            if self.pending is not None or self.curve_settings()!=expected:
                raise SelectionBlocked("Ustawienia zmieniły się lub trwa polecenie; odśwież")
            if value==expected:
                return
            target=Path(path).resolve(strict=True)
            original=target.read_bytes()
            stat=target.stat()
            disk=configparser.ConfigParser(interpolation=None)
            disk.read_string(original.decode("utf-8"))
            live=self.g["config"]["SETTINGS"]
            keys=("heatingcurve","heatingcurve_last","hcslope","hcpshift","hcamp","hcman")
            if any(disk["SETTINGS"].get(k)!=live.get(k) for k in keys):
                raise SelectionBlocked("Konfiguracja na dysku zmieniła się; odśwież")
            changes={"heatingcurve":value["mode"],"heatingcurve_last":value["mode"],
                     "hcslope":str(value["slope"]),"hcpshift":str(value["shift"]),
                     "hcamp":str(value["gain"]),"hcman":",".join(str(v) for v in value["points"])}
            before={k:live.get(k) for k in keys}
            def replace_config(data,previous):
                fd,tmp=tempfile.mkstemp(prefix=".curve-",dir=target.parent)
                try:
                    with os.fdopen(fd,"wb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.chmod(tmp,stat.st_mode & 0o777)
                    os.chown(tmp,stat.st_uid,stat.st_gid)
                    if target.read_bytes()!=previous:
                        raise SelectionBlocked("Plik konfiguracji zmienił się; odśwież")
                    os.replace(tmp,target)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            import io
            disk["SETTINGS"].update(changes)
            buffer=io.StringIO()
            disk.write(buffer)
            updated=buffer.getvalue().encode("utf-8")
            replace_config(updated,original)
            try:
                live.update(changes)
                self.g["loadconfig"]()
                if self.curve_settings()!=value:
                    raise RuntimeError("curve configuration readback mismatch")
            except Exception:
                for k,v in before.items():
                    if v is None:
                        live.pop(k,None)
                    else:
                        live[k]=v
                replace_config(original,updated)
                self.g["loadconfig"]()
                raise
            self.learning.cancel()
            self.learning_before=None
            self.reg.reset()
            # Core scheduled calculation applies new settings with native guards.
            # Do not force a write during defrost/DHW or an unconfirmed transition.
            self.g["logging"].info("Heating curve settings saved from WWW v2")

    def view(self):
        with self.lock:
            try:
                s,zone,curve,_=self.snapshot()
                actual=s.mode
                relay="1" if s.relay else "0"
                blocker=self.activation_reason(s,zone,curve)
            except Exception:
                actual=relay=zone=curve=None
                blocker="Brak pełnego, świeżego odczytu pompy lub GPIO"
            if self.pending is not None:
                blocker="Oczekiwanie na potwierdzenie poprzedniego polecenia"
            return dict(self.status,control=self.control,mode=actual,relay=relay,
                        ready=blocker is None,activation_blocker=blocker,curve=curve,zone=zone,pending=self.pending is not None,fault=self.fault,
                        curve_settings=self.curve_settings(),learning=self.learning.summary(),hysteresis=self.observer.summary(),
                        experiment={"counts":self.experiment_counts(),"levels":[m+("+FLimit" if l else " / OFF") for m,l in self.EXPERIMENT_LEVELS],
                                    "per_level":self.EXPERIMENT_CYCLES,"since":self.experiment_since})
