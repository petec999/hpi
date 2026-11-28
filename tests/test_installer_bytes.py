import ast
import runpy
import sys
import tempfile
import unittest
from pathlib import Path

INSTALL=runpy.run_path(str(Path(__file__).resolve().parents[1]/"tools/install-adaptive-preview.py"))

class InstallerBytes(unittest.TestCase):
    def test_unicode_literals_preserve_values(self):
        module="message = 'Włącz ogrzewanie – próba'\n"
        source="_WV_HTML = "+repr("Zażółć gęślą jaźń – ąćę")+"\n"
        source+="exec(compile("+repr(module)+", 'fixture', 'exec'), _am_module.__dict__)\n"
        safe=INSTALL["safe_literals"](source)
        self.assertTrue(safe.isascii())
        self.assertEqual(ast.dump(ast.parse(source)),ast.dump(ast.parse(safe)))
        self.assertEqual(safe,INSTALL["safe_literals"](safe))
        INSTALL["validate_bytes"](safe.encode(), "main.py", sys.executable)

    def test_invalid_bytes_and_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"main.py"
            valid="x='Włącz'\n".encode()
            path.write_bytes(valid)
            INSTALL["verify_installed"](path,valid,sys.executable)
            path.write_bytes(b"x='\xc4'\n")
            with self.assertRaises(RuntimeError):
                INSTALL["verify_installed"](path,valid,sys.executable)
            with self.assertRaises(UnicodeDecodeError):
                INSTALL["validate_bytes"](path.read_bytes(),path,sys.executable)

if __name__=="__main__":
    unittest.main()
