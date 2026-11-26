import importlib.util
import unittest
import re
import time
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
    def test_upgrade_previous_preview(self):
        old=SOURCE.replace('@app.route("/")',patcher.PREVIOUS_BLOCK+'@app.route("/")')
        updated=patcher.patch(old)
        self.assertEqual(updated,patcher.patch(SOURCE))
        self.assertEqual(patcher.patch(updated),updated)
        self.assertRaises(ValueError,patcher.patch,old.replace("Panel techniczny","Unknown panel"))

    def test_commands(self):
        calls=[]
        g=self.g
        g.update(_pump_frame_last_at={"R141":time.monotonic(),"R241":time.monotonic()},
                 statusdict={"settemp":{"value":"30.0"},"dhw":{"value":"50.0"},
                             "pch":{"value":"on"},"pdhw":{"value":"off"},
                             "mode":{"value":"eco"}},
                 new_tempchange=lambda *a:(calls.append(a) or "ok",True),
                 statechange=lambda *a:calls.append(a),
                 new_presetchange=lambda *a:(calls.append(a) or "ok",True))
        url="/v2/api/control"
        payload={"key":"settemp","value":30.5,"expected":30}
        self.assertEqual(self.client.post(url,json=payload).status_code,401)
        self.login()
        page=self.client.get("/v2/").data.decode()
        token=re.search(r'name="wv-csrf" content="([a-f0-9]{64})"',page).group(1)
        h={"Origin":"http://localhost","X-HaierPi-CSRF":token}
        def post(p,headers=h):
            return self.client.post(url,json=p,headers=headers)
        self.assertEqual(post(payload,{}).status_code,403)
        self.assertEqual(post(payload,{**h,"Origin":"http://other"}).status_code,403)
        self.assertEqual(post({**payload,"value":70}).status_code,400)
        self.assertEqual(post({**payload,"value":True}).status_code,400)
        self.assertEqual(post({**payload,"value":30.2}).status_code,400)
        self.assertEqual(post({**payload,"key":"heater"}).status_code,400)
        self.assertEqual(post({**payload,"expected":29}).status_code,409)
        self.assertEqual(calls,[])
        self.assertEqual(post(payload).status_code,202)
        self.assertEqual(calls,[("heat","30.5","0")])
        self.assertEqual(post({"key":"pdhw","value":"on","expected":"off"}).status_code,429)
        g["_wv_last_command"]=float("-inf")
        self.assertEqual(post({"key":"pdhw","value":"on","expected":"off"}).status_code,202)
        self.assertEqual(calls[-1],("pdhw","on","0"))
        g["_wv_last_command"]=float("-inf")
        self.assertEqual(post({"key":"dhw","value":51,"expected":50}).status_code,202)
        self.assertEqual(calls[-1],("dhw","51.0","1"))
        g["_wv_last_command"]=float("-inf")
        self.assertEqual(post({"key":"mode","value":"quiet","expected":"eco"}).status_code,202)
        self.assertEqual(calls[-1],("quiet",))
        g["_pump_frame_last_at"]["R141"]=0
        self.assertEqual(post(payload).status_code,409)
        self.assertEqual(len(calls),4)

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
