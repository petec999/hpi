import ast
import os
import runpy
import tempfile
import unittest
from pathlib import Path

PATCH=runpy.run_path(str(Path(__file__).resolve().parents[1]/"tools/patch-local-auth.py"))
FIXTURE="""
app.config['SECRET_KEY'] = 'fixture-only'
@app.route('/theme', methods=['POST'])
def theme_route():
    return 'theme'
@app.route('/backup')
def backup_route():
    return 'backup'
@app.route('/restore', methods=['GET', 'POST'])
def upload_file():
    return 'restore'
@socketlocal.on('connect')
def handle_connect():
    global grestarted
    return 'connected'
@socketlocal.on('client')
def handle_client_message(data):
    global grestarted
    logging.debug(data)
    return 'action'
"""

class LocalAuthTests(unittest.TestCase):
    def test_patch_and_idempotence(self):
        patched=PATCH["patch"](FIXTURE)
        self.assertEqual(patched,PATCH["patch"](patched))
        self.assertNotIn("fixture-only",patched)
        self.assertNotIn("logging.debug(data)",patched)
        tree=ast.parse(patched)
        for n in tree.body:
            if isinstance(n,ast.FunctionDef) and n.name in ("theme_route","backup_route","upload_file"):
                self.assertIn("login_required",[ast.unparse(d) for d in n.decorator_list])
        with self.assertRaises(ValueError):
            PATCH["patch"]("pass")

    def test_socket_guards(self):
        tree=ast.parse(PATCH["patch"](FIXTURE))
        nodes=[]
        for n in tree.body:
            if isinstance(n,ast.FunctionDef) and n.name in ("handle_connect","handle_client_message"):
                n.decorator_list=[]
                nodes.append(n)
        import logging
        env={"is_logged_in":lambda:False,"logging":logging}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),"fixture","exec"),env)
        self.assertFalse(env["handle_connect"]())
        self.assertIsNone(env["handle_client_message"]({}))
        env["is_logged_in"]=lambda:True
        self.assertEqual(env["handle_connect"](),"connected")
        self.assertIsNone(env["handle_client_message"]("invalid"))
        self.assertEqual(env["handle_client_message"]({}),"action")

    def test_private_secret_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/".key"
            env={"os":os,"tempfile":tempfile}
            exec(PATCH["HELPER"].replace("/opt/haier/.hpi-web-secret-v1",str(path)),env)
            key=env["_hpi_web_secret"]()
            self.assertEqual(len(key),64)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(env["_hpi_web_secret"](),key)
            self.assertEqual(list(Path(d).iterdir()),[path])
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                env["_hpi_web_secret"]()

if __name__=="__main__":
    unittest.main()
