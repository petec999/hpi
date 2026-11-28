import tempfile
import unittest
from pathlib import Path
from adaptive.regulator import RegisterWatch

def frames():
    return {k:[0]*n for k,n in RegisterWatch.SIZES.items()}

class RegisterWatchTest(unittest.TestCase):
    def test_reference_edges_and_dhw_samples(self):
        w=RegisterWatch()
        a=frames()
        w.observe(a,(0,)*4,{"tank":48},0,1000)
        a["R241"][3]=4
        w.observe(a,(30,)*4,{"tank":47.9},30,1030)
        self.assertEqual(len(w.events),1)
        a["R101"][0]=0x85
        a["R141"][3]=256
        a["R241"][3]=12
        w.observe(a,(60,)*4,{"tank":47.8},60,1060)
        self.assertEqual(len(w.events),2)
        e=w.summary(60)["events"][-1]
        self.assertIn("heater_readback",e["flags"])
        self.assertIn({"register":244,"before":4,"after":12,"xor":8,"set_bits":[3],"cleared_bits":[]},e["changes"])
        for t in (90,120,150,180):
            w.observe(a,(t,)*4,{"tank":47.8},t,1000+t)
        self.assertEqual(w.events[-1]["kind"],"dhw_sample")
        self.assertEqual(len(w.events),3)
        self.assertFalse(w.summary(250)["fresh"])

    def test_tank_bit_and_candidate_edges(self):
        w=RegisterWatch()
        a=frames()
        a["R101"][0]=0x03
        w.observe(a,(0,)*4,{},0,1000)
        self.assertFalse(w.summary(0)["flags"]["dhw_enabled"])
        for t in (30,60,90,120):
            w.observe(a,(t,)*4,{},t,1000+t)
        self.assertEqual(len(w.events),1)
        a["R101"][0]=0x85
        w.observe(a,(150,)*4,{},150,1150)
        self.assertTrue(w.summary(150)["flags"]["dhw_enabled"])
        self.assertIn("dhw_enabled",w.events[-1]["flags"])
        a["R141"][9]=0x0100
        a["R141"][10]=0x0100
        w.observe(a,(180,)*4,{},180,1180)
        self.assertEqual(w.events[-1]["kind"],"candidate")
        self.assertEqual([x["register"] for x in w.summary(180)["events"][-1]["changes"]],[150,151])

    def test_persistence_and_gap(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"watch.json"
            w=RegisterWatch(p)
            a=frames()
            w.observe(a,(0,)*4,{},0,1000)
            w.save_if_due(0)
            a["R141"][3]=256
            w.observe(a,(200,)*4,{},200,1200)
            self.assertEqual(len(w.events),1)
            w.observe(a,(230,)*4,{},230,1230)
            a["R141"][3]=0
            w.observe(a,(260,)*4,{},260,1260)
            self.assertEqual(len(w.events),2)
            w.save_if_due(1799)
            self.assertEqual(len(RegisterWatch(p).events),1)
            w.save_if_due(1800)
            self.assertEqual(RegisterWatch(p).events,w.events)

    def test_register_decode_and_co_candidate(self):
        a=frames()
        a["R141"][3]=0x1b00
        a["R141"][9]=0x0200
        a["R141"][10]=0x0200
        a["R141"][15]=16
        d=RegisterWatch.decode_registers(a)
        self.assertEqual(len(d["rows"]),45)
        self.assertEqual(len({r["register"] for r in d["rows"]}),45)
        self.assertEqual(d["signals"][0]["value"],26)
        self.assertEqual(d["signals"][1]["value"],2)
        self.assertEqual(d["signals"][0]["quality"],"unknown")
        signals={x["address"]:x for x in d["signals"]}
        self.assertFalse(signals["R156 bit4 / R141 bit13"]["value"])
        self.assertFalse(signals["R156 bit11 / R144 bit8"]["value"])
        a["R141"][0]=0x2000
        a["R141"][15]=0x0810
        signals={x["address"]:x for x in RegisterWatch.decode_registers(a)["signals"]}
        self.assertTrue(signals["R156 bit4 / R141 bit13"]["value"])
        self.assertTrue(signals["R156 bit11 / R144 bit8"]["value"])
        self.assertEqual(signals["R156 bit11"]["quality"],"candidate")
        a["R141"][0]=0
        a["R141"][15]=16
        self.assertEqual(RegisterWatch.decode_registers({})["rows"],[])
        w=RegisterWatch()
        w.observe(a,(0,)*4,{},0,1000)
        a["R141"][15]=0
        w.observe(a,(30,)*4,{},30,1030)
        self.assertEqual(w.events[-1]["kind"],"candidate")

    def test_register_page_patch(self):
        import ast, runpy, shutil, subprocess
        p=runpy.run_path(str(Path(__file__).resolve().parents[1]/"tools/patch-adaptive-preview.py"))
        source="_WV_HTML = "+repr('<a href="/v2/adaptive-report">Raport Adaptive →</a>')+"\n# HOME-IOT WEB UI V2 END\n"
        s=p["registers_page_api"](source)
        self.assertEqual(p["registers_page_api"](s),s)
        compile(s,"test","exec")
        self.assertIn('@login_required\ndef _wv_registers_json',s)
        html=ast.literal_eval(next(l for l in s.splitlines() if l.startswith("_WV_REGISTERS_HTML = ")).split("=",1)[1].strip())
        self.assertIn("/v2/api/registers",html)
        node=shutil.which("node")
        if node:
            subprocess.run([node,"--check","-"],input=html.split("<script>")[1].split("</script>")[0],text=True,check=True)

    def test_cap(self):
        w=RegisterWatch()
        a=frames()
        for i in range(300):
            a["R141"][3]=256*(i%2)
            w.observe(a,(i*30,)*4,{},i*30,1000+i*30)
        self.assertEqual(len(w.events),256)
