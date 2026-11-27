"""Conservative opt-in integration with Stable. No changes to heat demand or setpoints."""
import threading
import time
import math
import json
import os
import tempfile
from pathlib import Path
from adaptive.regulator import Regulator, Sample, LEVELS, Learning, STOP_HYSTERESIS, HysteresisObserver, AdaptiveReport, NativeThresholds, RegisterWatch, HeaterCounter, OperationMonitor

class SelectionBlocked(ValueError):
    """Safe, fixed activation reason exposed to authenticated UI."""

class Runtime:
    MAX_AGE=60
    PERIOD=30
    EXPERIMENT_LEVELS=(("eco",False),("quiet",False),("quiet",True),("eco",True),("turbo",True),("turbo",False))
    EXPERIMENT_CYCLES=3
    SIZES={"R101":6,"R141":16,"R201":1,"R241":22}
    def __init__(self,g,learning_path=None):
        self.g=g
        self.lock=threading.RLock()
        self.serial_lock=threading.RLock()
        self.frames_lock=threading.Lock()
        self.frames={}
        self.control="legacy"
        self.resume_path=Path(learning_path).with_name(".adaptive-owner-v1") if learning_path else None
        self.resume_requested=False
        self.resume_error=None
        self.load_owner()
        self.reg=Regulator()
        self.learning=Learning(learning_path,g.get("logging"))
        self.learning_before=None
        observer_path=Path(learning_path).with_name(".adaptive-hysteresis-v1.json") if learning_path else None
        self.observer=HysteresisObserver(observer_path,g.get("logging"))
        self.report=AdaptiveReport(Path(learning_path).with_name(".adaptive-report-v1.json") if learning_path else None)
        self.operation=OperationMonitor(Path(learning_path).with_name(".adaptive-operation-v1.json") if learning_path else None)
        self.learning.on_record=self.report.learned
        self.thresholds=NativeThresholds(Path(learning_path).with_name(".adaptive-thresholds-v1.json") if learning_path else None)
        self.register_watch=RegisterWatch(Path(learning_path).with_name(".adaptive-register-watch-v1.json") if learning_path else None)
        self.heater_counter=HeaterCounter(Path(learning_path).with_name(".adaptive-heater-counter-v1.json") if learning_path else None)
        # Prior experimental ON marker is diagnostic only after retirement.
        self.heater_marker=Path(learning_path).with_name(".adaptive-heater-owned-v1") if learning_path else None
        self.observer_frames=None
        self.experiment_counts_saved=[0]*len(self.EXPERIMENT_LEVELS)
        self.experiment_watermark=0
        self.experiment_since=None
        self.experiment_idle=None
        self.experiment_initial=None
        self.experiment_path=Path(learning_path).with_name(".adaptive-experiment-v1.json") if learning_path else None
        self.experiment_saved=False
        self.experiment_error=None
        self.load_experiment()
        self.last_tick=0
        self.pending=None
        self.status={"reason":"Waiting for valid boot telemetry" if self.resume_requested else "Legacy/Manual; no adaptive writes","risk":"paused"}
        self.fault=None
        self.invalid_since=None
        self.ready_log_frames=None
        self.ready_log_count=0
        self.idle_frame=None

    def load_experiment(self):
        # Checkpoint is not an actuator owner. Boot always follows load_owner.
        if self.experiment_path is None:
            return
        try:
            if self.experiment_path.is_symlink() or self.experiment_path.stat().st_size>4096:
                raise ValueError("invalid experiment checkpoint")
            data=json.loads(self.experiment_path.read_text(encoding="utf-8"))
            if not isinstance(data,dict) or data.get("schema")!=1 or "session" not in data:
                raise ValueError("invalid experiment schema")
            session=data["session"]
            if session is None:
                return
            since,initial=session["since"],session["initial"]
            if (type(since) not in (int,float) or not math.isfinite(since) or not 0<since<=time.time()+60
                    or not isinstance(initial,list) or len(initial)!=2 or initial[0] not in ("eco","quiet","turbo")
                    or type(initial[1]) is not bool):
                raise ValueError("invalid experiment session")
            counts=session.get("counts",[0]*len(self.EXPERIMENT_LEVELS))
            watermark=session.get("watermark",0)
            if (not isinstance(counts,list) or len(counts)!=len(self.EXPERIMENT_LEVELS)
                    or any(type(n) is not int or not 0<=n<=self.EXPERIMENT_CYCLES for n in counts)
                    or type(watermark) not in (int,float) or not math.isfinite(watermark) or watermark<0):
                raise ValueError("invalid experiment progress")
            self.experiment_counts_saved=counts
            self.experiment_watermark=watermark
            self.experiment_since=since
            self.experiment_initial=tuple(initial)
            self.experiment_saved=True
        except FileNotFoundError:
            pass
        except (OSError,ValueError,TypeError,KeyError,AttributeError,OverflowError):
            self.experiment_error="Nie można odczytać zapisu eksperymentu"

    def persist_experiment(self,session):
        temp=None
        try:
            if self.experiment_path is not None:
                if self.experiment_path.is_symlink():
                    raise ValueError("invalid experiment path")
                fd,temp=tempfile.mkstemp(prefix=".experiment-",dir=self.experiment_path.parent)
                with os.fdopen(fd,"w",encoding="utf-8") as stream:
                    json.dump({"schema":1,"session":session},stream,allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp,self.experiment_path)
                temp=None
                fd=os.open(str(self.experiment_path.parent),os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            self.experiment_saved=session is not None
            self.experiment_error=None
        except (OSError,ValueError,TypeError):
            self.experiment_error="Nie można zapisać stanu eksperymentu"
            raise SelectionBlocked(self.experiment_error) from None
        finally:
            if temp is not None:
                try:
                    os.unlink(temp)
                except OSError:
                    pass

    def load_owner(self):
        if self.resume_path is None:
            return
        try:
            if self.resume_path.is_symlink() or self.resume_path.stat().st_size>16:
                raise ValueError("invalid owner file")
            saved=self.resume_path.read_text(encoding="ascii").strip()
            if saved not in ("auto","manual","legacy"):
                raise ValueError("invalid owner")
            self.resume_requested=saved=="auto"
            self.control="manual" if saved in ("auto","manual") else "legacy"
        except FileNotFoundError:
            pass
        except (OSError,ValueError):
            self.control="manual"
            self.resume_error="Nie można odczytać zapamiętanego trybu; sterowanie ręczne"

    def persist_owner(self,mode):
        if self.resume_path is None:
            self.resume_requested=False
            return
        value="auto" if mode=="auto" else "manual" if mode in ("manual","experiment") else "legacy"
        temp=None
        try:
            if self.resume_path.is_symlink():
                raise ValueError("invalid owner path")
            fd,temp=tempfile.mkstemp(prefix=".adaptive-owner-",dir=self.resume_path.parent)
            with os.fdopen(fd,"w",encoding="ascii") as stream:
                stream.write(value+"\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp,self.resume_path)
            temp=None
            fd=os.open(str(self.resume_path.parent),os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            self.resume_requested=False
            self.resume_error=None
        except (OSError,ValueError) as e:
            self.resume_requested=False
            self.resume_error="Nie można zapisać trybu na dysku; sprawdź pamięć przed restartem"
            self.g["logging"].error("Adaptive owner persistence failed: %s",type(e).__name__)
            raise SelectionBlocked(self.resume_error) from None
        finally:
            if temp is not None:
                try:
                    os.unlink(temp)
                except OSError:
                    pass

    def resume_auto(self):
        if not self.resume_requested:
            return
        self.status={"reason":"Auto resume pending","reason_pl":"Auto po restarcie – oczekiwanie na świeże pomiary i normalne CO","risk":"paused"}
        if self.ready_log_count<2:
            return
        try:
            s,zone,curve,_=self.snapshot()
            if self.activation_reason(s,zone,curve) or not self.flag(self.raw("pch")) or not self.gpio("heatdemandpin"):
                return
            with self.frames_lock:
                power=int(self.frames["R101"][1][0])&255
            if not (power&1 and power&4 and not power&2):
                return
        except Exception:
            return
        self.choose("auto","manual")
        self.g["logging"].info("Adaptive Auto restored after restart; fresh telemetry verified")

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

    def snapshot(self,frames=None):
        if frames is None:
            with self.frames_lock:
                f=dict(self.frames)
        else:
            f=frames
        now=time.monotonic()
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
                try:
                    self.persist_owner("manual")
                except SelectionBlocked:
                    self.control="manual"
                    return ("Cannot persist Manual hold",False if kind=="preset" else "error")
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
            restart_experiment=mode=="experiment_new"
            if restart_experiment:
                mode="experiment"
            if mode not in ("legacy","manual","shadow","auto","experiment") or expected!=self.control:
                raise SelectionBlocked("Stan sterowania zmienił się; odśwież panel")
            if self.pending is not None:
                # Disarm immediately, but do not send competing commands.
                if mode in ("manual","shadow"):
                    self.control="manual"
                    self.resume_requested=False
                    self.persist_owner("manual")
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
            # Manual hold must take effect in RAM even if disk is read-only.
            # Do not keep actuating just because the user cannot persist a stop.
            if mode!="auto":
                self.control="manual"
                self.resume_requested=False
                self.learning.cancel()
                self.learning_before=None
                self.reg.reset()
            self.persist_owner(mode)
            if mode=="experiment" and (restart_experiment or not self.experiment_saved):
                since=time.time()
                initial=(s.mode,s.relay)
                # Persist before allowing any experiment writes.
                self.persist_experiment({"since":since,"initial":list(initial)})
                self.experiment_counts_saved=[0]*len(self.EXPERIMENT_LEVELS)
                self.experiment_watermark=0
                self.experiment_since=since
                self.experiment_initial=initial
            self.control=mode
            self.report_event("owner","selected "+mode)
            self.report.interrupt()
            self.thresholds.interrupt()
            self.observer.interrupt("context_changed",time.time())
            self.experiment_idle=None
            self.learning.cancel()
            self.learning_before=None
            self.fault=None
            self.invalid_since=None
            self.reg=Regulator()
            self.idle_frame=None
            self.status={"reason":"control selected: "+mode,"risk":"paused"}

    def fail(self,reason):
        self.report_event("fault",reason)
        self.report.interrupt()
        self.thresholds.interrupt()
        self.learning.cancel()
        self.learning_before=None
        self.control="manual"
        try:
            self.persist_owner("manual")
        except SelectionBlocked:
            reason+="; "+str(self.resume_error)
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
        model=self.thresholds.model(s)
        if model["start_margin"] is not None and (model["start_margin"]<=0.5 or model["start_eta_min"] is not None and model["start_eta_min"]<=5):
            reason+=" · zbliża się prognozowany START"
        self.status={"reason":"idle startup preparation","reason_pl":reason,
                     "risk":"paused","actual":actual,"proposed":proposed,
                     "target":s.target,"return_temp":s.return_temp,"stop_target":model["stop_target"],
                     "supply_temp":s.supply_temp,"stop_sensor":"two","stop_margin":model["stop_target"]-s.supply_temp,"down_confirm":self.reg.cfg.down_confirm,
                     "surplus_band":self.reg.cfg.surplus_band}
        if self.control!="auto" or (s.mode,s.relay)==(mode,relay) or previous is None or not 0<frame-previous<=self.MAX_AGE:
            return True
        # Preserve a near-complete STOP observation for at most one tick
        # if both water sensors are still well above the predicted START.
        # Native restart remains independent; skip this hold near START.
        edge=self.thresholds.pending
        if edge is not None and not edge[5] and edge[6] and 30<=s.now-edge[1]<60 and min(s.return_temp,s.supply_temp)>=model["start_target"]+2 and (model["start_eta_min"] is None or model["start_eta_min"]>5):
            self.status["reason_pl"]="Postój – potwierdzanie progu STOP przed przygotowaniem"
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
            self.report_event("issued","idle: "+mode+" / FLimit "+str(relay))
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

    def report_event(self,kind,detail):
        try:
            self.report.event(kind,self.control,detail)
        except Exception:
            pass

    def report_view(self):
        with self.lock:
            data=self.report.snapshot()
            # Do not present an old sampled run as a currently running compressor.
            if self.report.last is None or not 0<=time.monotonic()-self.report.last[0]<=65:
                data["current_streak"]=None
            rows=[]
            for key,value in self.learning.rows.items():
                a,b,c,d=map(int,key.split(":"))
                score=value["score"]
                learned=value["n"]>=3
                rows.append(dict(value,context=key,outdoor_band=a*5,target_band=b*3,
                    transition=data["levels"][c]+" → "+data["levels"][d],tuned=learned,
                    down_confirm=90-30*score if learned else 90,
                    surplus_band=1.5-.5*score if learned else 1.5,
                    early_surplus=2.5-.5*score if learned else 2.5,
                    forecast_min=3+.5*score if learned else 3))
            data["learning"]={"contexts":len(rows),"capacity":self.learning.MAX_CONTEXTS,
                "observations":sum(v["n"] for v in rows),"unsaved":self.learning.dirty,
                "storage_error":self.learning.storage_error,"rows":sorted(rows,key=lambda x:x["last"],reverse=True)}
            try:
                data["learning"]["saved_at"]=self.learning.path.stat().st_mtime if self.learning.path and self.learning.path.exists() else None
            except OSError:
                data["learning"]["saved_at"]=None
            data["experiment_comparison"]=self.experiment_comparison()
            data["operation_24h"]=self.operation.summary(time.time())
            data["thresholds"]=self.thresholds.summary()
            data["register_watch"]=self.register_watch.summary(time.monotonic())
            data["heater_counter"]=self.heater_counter.summary(time.monotonic())
            return data

    def heater_view(self):
        data=self.heater_counter.summary(time.monotonic())
        # Do not silently write OFF or delete a prior ownership marker.
        # It is evidence of a possible historical manual request, not proof.
        data["previous_request_marker"]=bool(self.heater_marker and
            (self.heater_marker.exists() or self.heater_marker.is_symlink()))
        return data

    def observe_heater(self,now):
        # Count only fresh, distinct R141 samples; no additional RS485 traffic.
        try:
            with self.frames_lock:
                stamp,frame=self.frames.get("R141",(None,None))
            self.heater_counter.observe(frame,stamp,time.monotonic(),time.time())
            self.heater_counter.save_if_due(now)
            d=self.heater_counter.summary(time.monotonic())
            if d["state"] is None or d["storage_error"]:
                return
            base=str(self.g.get("mqtt_topic","")).rstrip("/")
            if not base:
                return
            for client in list(self.g.get("services",[])):
                try:
                    if client.is_connected():
                        for key,value in (("starts",d["starts"]),("seconds",d["seconds"])):
                            client.publish(base+"/diagnostics/heater/"+key,str(value),qos=0,retain=False)
                except Exception:
                    pass
        except Exception:
            pass

    def observe_registers(self,now):
        # Independent from CO eligibility and owner. No extra bus transactions.
        try:
            with self.frames_lock:
                f=dict(self.frames)
            if set(f)!=set(self.SIZES):
                self.register_watch.interrupt()
                return
            stamps=tuple(f[k][0] for k in self.SIZES)
            frames={k:f[k][1] for k in self.SIZES}
            context={k:self.raw(k) for k in RegisterWatch.CONTEXT}
            self.register_watch.observe(frames,stamps,context,time.monotonic(),time.time())
        except Exception:
            self.register_watch.interrupt()
        finally:
            try:
                self.register_watch.save_if_due(now)
            except Exception:
                pass

    def observe_hysteresis(self):
        # Separate from regulation; failures must never influence commands.
        try:
            with self.frames_lock:
                frames=dict(self.frames)
            s,zone,curve,_=self.snapshot(frames)
            stamps=tuple(frames[k][0] for k in ("R101","R141","R201","R241"))
            power=int(frames["R101"][1][0])&255
            if self.observer_frames is not None and not all(a>b for a,b in zip(stamps,self.observer_frames)):
                if max(stamps)-min(stamps)>self.MAX_AGE:
                    self.operation.interrupt()
                    self.observer.interrupt("frame_gap",time.time())
                    self.thresholds.interrupt()
                    self.report.interrupt()
                return
            self.observer_frames=stamps
            co_enabled=bool(power&1 and power&4 and not power&2) and self.flag(self.raw("pch"))
            demand=self.gpio("heatdemandpin")
            eligible=self.activation_reason(s,zone,curve) is None and co_enabled and demand
            reason=("fault" if s.error else "dhw" if s.dhw else "defrost" if s.defrost else
                    "protection" if s.override else "priority_zone" if zone!="normal" else
                    "target_mismatch" if abs(curve-s.target)>1 else "co_disabled" if not co_enabled else
                    "no_demand" if not demand else "pending_write" if self.pending is not None else "invalid_sample")
            try:
                outdoor=self.number(self.raw("outtemp"))
            except (TypeError,ValueError):
                outdoor=None
            wall=time.time()
            try:
                self.operation.observe(s,wall,co_enabled)
            except Exception:
                self.operation.interrupt()
            # Do not discard ordinary Auto modulation or pending writes from
            # performance cycles. Strict hysteresis keeps its old rules.
            try:
                self.report.observe(s,self.control,eligible,wall,outdoor)
            except Exception:
                self.report.interrupt()
            self.observer.observe(s,self.control,eligible and self.pending is None,wall,outdoor=outdoor,reason=reason)
            try:
                self.thresholds.observe(s,eligible and self.pending is None,wall,self.control)
            except Exception:
                self.thresholds.interrupt()
        except Exception:
            self.operation.interrupt()
            self.observer.interrupt("telemetry_unavailable",time.time())
            self.report.interrupt()
            self.thresholds.interrupt()
        finally:
            try:
                self.checkpoint_experiment_progress()
            except SelectionBlocked:
                pass
            self.observer.save_if_due(time.monotonic())
            try:
                self.report.save_if_due(time.monotonic())
                self.thresholds.save_if_due(time.monotonic())
                self.operation.save_if_due(time.monotonic())
            except Exception:
                pass

    def experiment_progress(self):
        counts=list(self.experiment_counts_saved)
        watermark=self.experiment_watermark
        if self.experiment_since is not None:
            for row in self.observer.rows:
                c=row["context"]
                at=row["start"]["at"]
                if c[0]=="experiment" and at>=self.experiment_since and at>self.experiment_watermark:
                    pair=tuple(c[1:3])
                    if pair in self.EXPERIMENT_LEVELS:
                        i=self.EXPERIMENT_LEVELS.index(pair)
                        counts[i]=min(self.EXPERIMENT_CYCLES,counts[i]+1)
                        watermark=max(watermark,at)
        return counts,watermark

    def experiment_comparison(self):
        # Read-only comparison of retained, accepted cycles in the current session.
        # Persistent counts may exceed retained samples after history eviction.
        from statistics import median
        counts=self.experiment_counts()
        result=[]
        for i,pair in enumerate(self.EXPERIMENT_LEVELS):
            rows=[r for r in self.observer.rows if self.experiment_since is not None
                  and r["context"][0]=="experiment" and tuple(r["context"][1:3])==pair
                  and r["start"]["at"]>=self.experiment_since]
            def med(values):
                values=list(values)
                return median(values) if values else None
            result.append({"mode":pair[0],"flimit":pair[1],"completed":counts[i],
                "retained":len(rows),
                "run_seconds":med(r["run_seconds"] for r in rows if "run_seconds" in r),
                "stop_fact":med(r["stop"]["fact"][0] for r in rows if "fact" in r["stop"]),
                "stop_delta":med(r["stop"]["two"][0]-r["stop"]["twi"][0] for r in rows)})
        return {"since":self.experiment_since,"per_level":self.EXPERIMENT_CYCLES,"rows":result}

    def experiment_counts(self):
        return self.experiment_progress()[0]

    def checkpoint_experiment_progress(self):
        if not self.experiment_saved or self.experiment_since is None:
            return
        counts,watermark=self.experiment_progress()
        if watermark==self.experiment_watermark:
            return
        self.persist_experiment({"since":self.experiment_since,"initial":list(self.experiment_initial),
                                 "counts":counts,"watermark":watermark})
        self.experiment_counts_saved=counts
        self.experiment_watermark=watermark

    def experiment_tick(self,s,zone,curve):
        # Opt-in, native idle only. Never change demand, water target or Fset.
        counts=self.experiment_counts()
        idx=next((i for i,n in enumerate(counts) if n<self.EXPERIMENT_CYCLES),None)
        done=idx is None
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
                try:
                    self.persist_experiment(None)
                    self.status["reason_pl"]="Eksperyment zakończony – przywrócono konfigurację początkową"
                except SelectionBlocked:
                    self.status["reason_pl"]="Eksperyment zakończony – konfiguracja przywrócona, błąd zapisu stanu"
                    self.fault=self.experiment_error
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
            self.observe_heater(now)
            self.observe_registers(now)
            self.observe_hysteresis()
            if self.resume_requested:
                self.resume_auto()
                return
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
                    self.report_event("confirmed",mode+" / FLimit "+str(relay))
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
            model=self.thresholds.model(s)
            stop_offset=model["stop"]["offset"]
            if self.control=="auto":
                outdoor=self.number(self.raw("outtemp"))
                self.learning.observe(s,outdoor,stop_offset)
                self.reg.cfg=self.learning.settings(s,outdoor)
            d=self.reg.step(s,control=self.control,stop_offset=stop_offset)
            label=lambda i: None if i is None else LEVELS[i][0]+("+FLimit" if LEVELS[i][1] else "")
            self.status={"reason":d.reason,"reason_pl":self.display_reason(s,d.reason),"risk":d.risk,"actual":label(d.current),
                         "proposed":label(d.proposed),"target":s.target,
                         "supply_error":d.supply_error,"forecast":d.predicted_surplus,
                         "return_temp":s.return_temp,"return_trend":None if d.trend is None else -d.trend,
                         "supply_temp":s.supply_temp,"supply_forecast":d.supply_forecast,
                         "supply_trend":None if d.supply_trend is None else -d.supply_trend,
                         "stop_sensor":"two","stop_target":model["stop_target"],"stop_margin":model["stop_target"]-s.supply_temp,
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
                if d.reason in ("increase available capacity","restore previous capacity; reduction failed") and current.supply_temp-current.target>=self.thresholds.model(current)["stop"]["offset"]-self.reg.cfg.stop_margin:
                    return
                issued=time.monotonic()
                self.learning.cancel()
                self.learning_before=(s,outdoor)
                self.pending=(mode,relay,issued+90,issued)
                self.report_event("issued",str(self.status["actual"])+" → "+str(self.status["proposed"])+" | "+d.reason+" | Two "+str(s.supply_temp)+" / target "+str(s.target))
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

    def storage_diagnostics(self):
        """Read-only process and filesystem diagnostics; no history writes."""
        result = {}
        try:
            import shutil
            root = self.experiment_path.parent if self.experiment_path else Path(".")
            usage = shutil.disk_usage(root)
            result.update(disk_total_bytes=usage.total, disk_free_bytes=usage.free)
            result["state_files"] = {p.name: p.stat().st_size for p in root.glob(".adaptive-*") if p.is_file() and not p.is_symlink()}
        except OSError:
            result["disk_error"] = True
        for path, keys, multiplier in (("/proc/self/status", ("VmRSS", "VmHWM"), 1024),
                                        ("/proc/self/io", ("write_bytes", "wchar"), 1)):
            try:
                for line in Path(path).read_text().splitlines():
                    key, _, value = line.partition(":")
                    if key in keys:
                        result[key + "_bytes"] = int(value.split()[0]) * multiplier
            except (OSError, ValueError, IndexError):
                pass
        return result

    def view(self):
        with self.lock:
            try:
                s,zone,curve,_=self.snapshot()
                actual=s.mode
                relay="1" if s.relay else "0"
                blocker=self.activation_reason(s,zone,curve)
                model=self.thresholds.model(s)
                if blocker is not None or self.pending is not None or not self.flag(self.raw("pch")) or not self.gpio("heatdemandpin"):
                    model["start_eta_min"]=model["stop_eta_min"]=None
            except Exception:
                actual=relay=zone=curve=model=None
                blocker="Brak pełnego, świeżego odczytu pompy lub GPIO"
            if self.pending is not None:
                blocker="Oczekiwanie na potwierdzenie poprzedniego polecenia"
            return dict(self.status,storage_diagnostics=self.storage_diagnostics(),control=self.control,mode=actual,relay=relay,
                        ready=blocker is None,activation_blocker=blocker,curve=curve,zone=zone,pending=self.pending is not None,fault=self.fault,
                        auto_resume_pending=self.resume_requested,owner_storage_error=self.resume_error,threshold_model=model,
                        heater=self.heater_view(),curve_settings=self.curve_settings(),learning=self.learning.summary(),hysteresis=self.observer.summary(),
                        experiment={"counts":self.experiment_counts(),"levels":[m+("+FLimit" if l else " / OFF") for m,l in self.EXPERIMENT_LEVELS],
                                    "per_level":self.EXPERIMENT_CYCLES,"since":self.experiment_since,
                                    "resume_available":self.experiment_saved and self.control!="experiment",
                                    "initial":self.experiment_initial,"storage_error":self.experiment_error})
