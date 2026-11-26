import importlib.util
import unittest
from pathlib import Path
from flask_login import LoginManager, UserMixin

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("webpatch",ROOT/"tools/install-web-ui-v2.py")
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)
SOURCE = '''
from flask import Flask
from flask_login import login_required
app = Flask(__name__)
# HOME-IOT MQTT WATCHDOG v2
statusdict={}
_pump_frame_last_at={}
PUMP_FRAME_STALE_AFTER_S=180
_wd_last_ok=None

@app.route("/")
@login_required
def original():
    return "Original"
'''

class User(UserMixin):
    id="test"

class Tests(unittest.TestCase):
    def setUp(self):
        self.g={"__name__":"web_test"}
        exec(patcher.patch(SOURCE),self.g)
        app=self.g["app"]
        app.secret_key="test-only"
        manager=LoginManager(app)
        manager.user_loader(lambda uid: User() if uid=="test" else None)
        self.client=app.test_client()
    def login(self):
        with self.client.session_transaction() as s:
            s["_user_id"]="test"
            s["_fresh"]=True
    def test_idempotent_and_original(self):
        modified=patcher.patch(SOURCE)
        self.assertEqual(patcher.patch(modified),modified)
        self.assertIn("def original():",modified)
        self.assertRaises(ValueError,patcher.patch,SOURCE.replace("WATCHDOG v2","WATCHDOG v1"))
    def test_auth_and_read_only(self):
        self.assertEqual(self.client.get("/v2/").status_code,401)
        self.assertEqual(self.client.get("/v2/api/state").status_code,401)
        self.login()
        page=self.client.get("/v2/")
        self.assertEqual(page.status_code,200)
        self.assertIn(b"HaierPi",page.data)
        self.assertEqual(page.headers["Cache-Control"],"no-store")
        self.assertEqual(self.client.get("/").data,b"Original")
        self.assertEqual(self.client.post("/v2/api/state").status_code,405)
        api=self.client.get("/v2/api/state")
        self.assertEqual(api.status_code,200)
        self.assertEqual(api.json["schema"],1)
    def test_frame_gating_and_values(self):
        g=self.g
        g.update(_pump_frame_last_at={"R141":990,"R241":995},
                 _wd_last_ok=990,_wd_status="ok",mqtt_snapshot_interval_s=30,
                 use_mqtt="1",_wd_failures=2,_wd_recoveries=1,
                 statusdict={
                     "water":{"mqtt":"/haierunit/temperatures/twitwo/state","value":"[29.7,34.2]"},
                     "compressor":{"mqtt":"/haierunit/compressor/info/state","value":[42,38,4.5,310,45]},
                     "defrost":{"mqtt":"/haierunit/statuses/defrost/state","value":"off"},
                     "ts":{"mqtt":"/haierunit/temperatures/tdts/state","value":[57,-2]},
                     "sat":{"mqtt":"/haierunit/temperatures/tsatps/state","value":[0,-1]},
                     "secret":{"mqtt":"/private/secret/state","value":"test-secret"},
                 })
        state=g["_wv_state"](g,1000)
        v=state["values"]
        self.assertEqual((v["two"],v["twi"],v["delta"]),(34.2,29.7,4.5))
        self.assertEqual((v["fact"],v["fset"]),(38,42))
        self.assertEqual(v["superheat"],-1)
        self.assertIs(v["defrost"],False)
        self.assertNotIn("test-secret",str(state))
        self.assertEqual(state["watchdog"]["status"],"ok")
        g["_pump_frame_last_at"]["R241"]=800
        state=g["_wv_state"](g,1000)
        self.assertIsNone(state["values"]["fact"])
        self.assertIsNone(state["values"]["superheat"])
        self.assertEqual(state["values"]["two"],34.2)
        self.assertEqual(g["_wv_state"](g,1200)["watchdog"]["status"],"alarm")
    def test_invalid_values(self):
        g=self.g
        g.update(_pump_frame_last_at={"R141":990,"R241":990},
                 statusdict={"twitwo":{"value":"[null,NaN]"},"compinfo":{"value":"invalid"}})
        v=g["_wv_state"](g,1000)["values"]
        self.assertIsNone(v["two"])
        self.assertIsNone(v["twi"])
        self.assertIsNone(v["fact"])

if __name__=="__main__":
    unittest.main()
