import ast
import json
import runpy
import tempfile
import time
import unittest
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from adaptive.energy import EnergyMonitor, DEFAULT, validate, convert

PATCH=runpy.run_path(str(Path(__file__).resolve().parents[1]/"tools/patch-energy.py"))
class EnergyTests(unittest.TestCase):
    def configured(self,**kw):
        m=EnergyMonitor({})
        m.save(dict(DEFAULT,enabled=True,energy="sensor.energy",flow_source="manual",manual_flow=1.15,**kw))
        return m

    def test_validation(self):
        for data in (dict(DEFAULT,enabled=True),dict(DEFAULT,manual_flow=float("nan")),dict(DEFAULT,energy="sensor.x/../../abc"),dict(DEFAULT,energy_unit="J")):
            with self.assertRaises(ValueError):
                validate(data)
        self.assertAlmostEqual(convert("flow",20,"l/min"),1.2)
        self.assertEqual(convert("energy",1200,"Wh"),1.2)
        m=EnergyMonitor({"mqtt_topic":"haier","ha_mqtt_discovery_prefix":"homeassistant"})
        with self.assertRaises(ValueError):
            m.save(dict(DEFAULT,enabled=True,source="mqtt",energy="haier/power/set"))

    def test_counter_and_paired_cop(self):
        m=self.configured()
        state=("co_run","eco / FLimit OFF",5,1000)
        for i in range(11):
            m.accept(i*30,state,{"energy":10+i*.025,"flow":1.15})
        d=m.summary(300)
        b=d["groups_24h"]["co_run"]
        self.assertAlmostEqual(b["kwh"],.25)
        self.assertAlmostEqual(b["heat_kwh"],1.163*1.15*5/12)
        self.assertAlmostEqual(b["cop_estimate"],1.163*1.15*5/3)
        self.assertAlmostEqual(d["experiment"][state[1]]["kwh"],.25)
        m.accept(330,("co_idle",state[1],0,1000),{"energy":10.3})
        self.assertIn("unassigned",m.summary(330)["groups_24h"])
        m.accept(360,None,{"energy":0})
        m.accept(600,state,{"energy":1})
        self.assertAlmostEqual(sum(v["kwh"] for v in m.summary(600)["groups_24h"].values()),.3)

    def test_power_estimate_and_no_flow(self):
        m=EnergyMonitor({})
        m.save(dict(DEFAULT,enabled=True,power="sensor.power"))
        m.accept(0,None,{"power":2})
        m.accept(60,None,{"power":4})
        d=m.summary(60)
        self.assertTrue(d["electricity_estimated"])
        self.assertAlmostEqual(d["groups_24h"]["unassigned"]["kwh"],.05)
        self.assertIsNone(d["groups_24h"]["unassigned"]["cop_estimate"])

    def test_ha_freshness_and_units(self):
        state={"state":"2500","attributes":{"unit_of_measurement":"Wh"},
               "last_updated":datetime.now(timezone.utc).isoformat()}
        class Response:
            status_code=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def iter_content(self,n):yield json.dumps(state).encode()
        def get(url,**kwargs):
            self.assertEqual(url,"http://ha.local:8123/api/states/sensor.energy")
            self.assertFalse(kwargs["allow_redirects"])
            return Response()
        m=EnergyMonitor({"haaddr":"http://ha.local","haport":"8123","hakey":"fixture","requests":SimpleNamespace(get=get)})
        self.assertEqual(m.read_ha("sensor.energy","energy","Wh"),2.5)
        with self.assertRaises(ValueError):
            m.read_ha("sensor.energy","energy","kWh")
        state["last_updated"]="2000-01-01T00:00:00Z"
        with self.assertRaises(ValueError):
            m.read_ha("sensor.energy","energy","Wh")

    def test_mqtt_exact_topic_and_retained(self):
        m=EnergyMonitor({"mqtt_topic":"haier"})
        m.save(dict(DEFAULT,enabled=True,source="mqtt",energy="meter/total"))
        class Client:
            def is_connected(self):return True
            def subscribe(self,topic,qos=0):return (0,1)
            def unsubscribe(self,topic):return (0,1)
        c=Client()
        m.mqtt_connect(c)
        msg=SimpleNamespace(topic="meter/total",payload=b"12",retain=True)
        self.assertTrue(m.mqtt_message(c,msg))
        self.assertEqual(m.read_values(m.cfg)[1],["energy"])
        msg.retain=False
        self.assertTrue(m.mqtt_message(c,msg))
        self.assertEqual(m.read_values(m.cfg)[0]["energy"],12)
        msg.topic="haier/power/set"
        self.assertFalse(m.mqtt_message(c,msg))
        m.mqtt_disconnect(c)
        self.assertEqual(m.read_values(m.cfg)[1],["energy"])

    def test_config_persist_and_bounded_history(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"energy.json"
            m=EnergyMonitor({},path)
            m.save(dict(DEFAULT,enabled=True,energy="sensor.energy"))
            self.assertEqual(EnergyMonitor({},path).cfg,m.cfg)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            before=path.stat().st_ino
            m.save(m.cfg)
            self.assertEqual(before,path.stat().st_ino)
            for i in range(4000):
                m.accept(i*30,None,{"energy":i*.001})
            self.assertLessEqual(len(m.rows),2881)
            self.assertLessEqual(m.summary(3999*30)["coverage_seconds"],86430)

    def test_cycle_checkpoint_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"energy.json"
            m=EnergyMonitor({},path)
            m.save(dict(DEFAULT,enabled=True,energy="sensor.energy",flow_source="manual",manual_flow=1.15))
            mode="eco / FLimit OFF"
            state=("co_run",mode,5,1000)
            for i in range(13):
                m.accept(i*30,state,{"energy":10+i*.025,"flow":1.15},1000+i*30)
            m.record_cycles(1000,[(1000,1360,mode),(1360,1370,mode)])
            row=m.summary(360)["cycles"][0]
            self.assertEqual(row["covered_seconds"],360)
            self.assertAlmostEqual(row["kwh"],.3)
            self.assertIsNotNone(row["cop_estimate"])
            restarted=EnergyMonitor({},path)
            self.assertEqual(restarted.summary()["cycles"],[row])
            before=restarted.cycle_path.stat().st_ino
            restarted.accept(390,None,{},1390)
            restarted.record_cycles(1000,[(1000,1360,mode)])
            self.assertEqual(before,restarted.cycle_path.stat().st_ino)
            restarted.record_cycles(1000,[(1360,1390,mode)])
            self.assertIsNone(restarted.summary()["cycles"][1]["kwh"])

    def test_meter_average_power_uses_only_contiguous_increments(self):
        m=self.configured()
        self.assertIsNone(m.meter_average_power(0))
        for i in range(11):
            m.accept(i*30,None,{"energy":10+i*.025})
        v=m.meter_average_power(300)
        self.assertAlmostEqual(v["kw"],3)
        self.assertEqual(v["seconds"],300)
        self.assertIsNone(m.meter_average_power(400))
        m.accept(330,None,{"energy":0})
        self.assertIsNone(m.meter_average_power(330))
        m.accept(360,None,{"energy":.025})
        self.assertIsNone(m.meter_average_power(360))
        m.accept(390,None,{"energy":.05})
        self.assertAlmostEqual(m.meter_average_power(390)["kw"],3)
        m.accept(420,None,{})
        self.assertIsNone(m.meter_average_power(420))

    def test_signed_defrost_and_climate_bins(self):
        m=self.configured()
        mode="eco / FLimit OFF"
        m.accept(0,("co_run",mode,5,1000,1.0,35,True),{"energy":10,"flow":1.15},1000)
        m.accept(30,("co_run",mode,5,1000,1.2,35,True),{"energy":10.01,"flow":1.15},1030)
        m.accept(60,("defrost",mode,-5,1000,1.0,35,True),{"energy":10.02,"flow":1.15},1060)
        m.accept(90,("defrost",mode,-5,1000,1.0,35,True),{"energy":10.03,"flow":1.15},1090)
        d=m.summary(90)
        self.assertAlmostEqual(d["net_groups_24h"]["defrost"]["net_heat_kwh"],-1.163*1.15*5/120)
        self.assertAlmostEqual(d["climate_24h"][0]["net_heat_kwh"],0)
        self.assertAlmostEqual(d["climate_24h"][0]["kwh"],.02)
        self.assertEqual(d["climate_24h"][0]["outdoor_band"],0)
        self.assertEqual(d["climate_24h"][0]["target_band"],34)
        m.accept(120,("defrost",mode,-5,1000,1.0,35,None),{"energy":10.04,"flow":1.15},1120)
        d=m.summary(120)
        self.assertIsNone(d["climate_24h"][0]["cop_net"])
        self.assertLess(d["climate_24h"][0]["paired_fraction"],1)

    def test_window_summary_requires_matching_session_and_coverage(self):
        m=self.configured()
        mode="eco / FLimit OFF"
        for t in range(0,601,30):
            m.accept(t,("co_run",mode,5,1000,1,35,True),{"energy":10+t/3600,"flow":1.15},1000+t)
        result=m.window_summary(1000,1600,mode,1000)
        self.assertAlmostEqual(result["time_fraction"],1)
        self.assertAlmostEqual(result["cop_net"],1.163*1.15*5)
        self.assertIsNone(m.window_summary(1000,1600,mode,999))
        self.assertIsNone(m.window_summary(1000,2200,mode,1000)["cop_net"])

    def test_climate_history_persists_estimated_flow_and_excludes_gaps(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"energy.json"
            m=EnergyMonitor({},path)
            m.save(dict(DEFAULT,enabled=True,energy="sensor.energy",flow_source="manual",manual_flow=1.15))
            state=("co_run","eco / FLimit OFF",5,1000,1,35,True)
            for t in range(0,601,30):
                m.accept(t,state,{"energy":10+t/3600,"flow":1.15},1000+t)
            m.accept(900,state,{"energy":10.25,"flow":1.15},1900)
            m.save_climate(900)
            h=m.climate_history()
            self.assertTrue(h["flow_estimated"])
            self.assertEqual(h["rows"][0]["seconds"],600)
            self.assertAlmostEqual(h["rows"][0]["cop_net"],1.163*1.15*5)
            self.assertFalse(h["unsaved"])
            restarted=EnergyMonitor({},path)
            self.assertEqual(restarted.climate_history(),h)
            restarted.save(dict(m.cfg,manual_flow=1.2))
            self.assertEqual(EnergyMonitor({},path).climate_history()["contexts"],0)

    def test_ui_patch(self):
        fixture=("""
_WV_HTML = '<nav></nav>'
_WV_ADAPTIVE_REPORT_HTML = '<header></header>'
def on_connect(client, userdata, flags, rc):
    pass
def on_disconnect(client, userdata, rc):  # The callback for when
    pass
def on_message(client,userdata,msg):
    if msg.topic == str(mqtt_topic) + "/haierpi/watchdog_heartbeat":
        return
# HOME-IOT WEB UI V2 END
""")
        out=PATCH["patch"](fixture)
        self.assertEqual(out,PATCH["patch"](out))
        self.assertIn("/v2/energy",out)
        self.assertIn("@login_required",out)
        self.assertIn("X-HaierPi-CSRF",out)
        ast.parse(out)

if __name__=="__main__":
    unittest.main()
