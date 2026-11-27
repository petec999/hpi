import ast
import collections
import io
import logging
import os
import pickle
import runpy
import tempfile
import threading
import time
import traceback
import unittest
from pathlib import Path
from types import SimpleNamespace

PATCH=runpy.run_path(str(Path(__file__).resolve().parents[1]/"tools/patch-serial-charts.py"))

class SerialCharts(unittest.TestCase):
    def env(self):
        env={"threading":threading,"time":time,"event":threading.Event(),
             "_am":SimpleNamespace(serial_lock=threading.RLock()),"newframe":[],
             "writed":"0","os":os,"pickle":pickle,"tempfile":tempfile,
             "collections":collections,"logging":logging,"traceback":traceback}
        exec(PATCH["HELPER"],env)
        return env

    def packet(self,env,regs):
        body=b"\x11\x03"+bytes([2*len(regs)])+b"".join(v.to_bytes(2,"big") for v in regs)
        return body+env["_hpi_crc"](body).to_bytes(2,"little")

    def test_crc_and_all_supported_lengths(self):
        env=self.env()
        self.assertEqual(env["_hpi_crc"](b"123456789"),0x4b37)
        for size in (1,6,16,22):
            regs=list(range(size))
            self.assertEqual(env["_hpi_read_packet"](io.BytesIO(self.packet(env,regs))),regs)
        packet=self.packet(env,[12,34,56,78,90,123])
        self.assertIsNone(env["_hpi_read_packet"](io.BytesIO(packet[:-1]+bytes([packet[-1]^1]))))
        self.assertIsNone(env["_hpi_read_packet"](io.BytesIO(packet[:-2])))
        self.assertEqual(env["_hpi_serial_stats"]["valid"],4)
        self.assertEqual(env["_hpi_serial_stats"]["crc_errors"],1)
        self.assertEqual(env["_hpi_serial_stats"]["short_frames"],1)

    def pending(self,env,timeout=1):
        end=time.monotonic()+timeout
        while env["_hpi_command"] is None and time.monotonic()<end:
            time.sleep(.001)
        self.assertIsNotNone(env["_hpi_command"])
        return env["_hpi_take"]()

    def test_timed_out_inflight_command_cannot_ack_next(self):
        env=self.env()
        results=[]
        worker=threading.Thread(target=lambda:results.append(env["_hpi_send"]([0],[1],.2)))
        worker.start()
        first=self.pending(env)
        worker.join(2)
        self.assertEqual(results,[False])
        self.assertFalse(env["_hpi_send"]([0],[2],.01))
        env["_hpi_finish"](first,True)
        worker=threading.Thread(target=lambda:results.append(env["_hpi_send"]([0],[2],1)))
        worker.start()
        second=self.pending(env)
        env["_hpi_finish"](first,True)
        self.assertFalse(second["done"].is_set())
        env["_hpi_finish"](second,True)
        worker.join(2)
        self.assertEqual(results,[False,True])
        self.assertEqual(env["newframe"],[])

    def test_unstarted_timeout_and_bad_input(self):
        env=self.env()
        self.assertFalse(env["_hpi_send"]([0],[1],.01))
        self.assertIsNone(env["_hpi_take"]())
        self.assertFalse(env["_hpi_send"]([0],"ERROR"))
        self.assertFalse(env["_hpi_send"]([0],[65536]))
        self.assertEqual(env["newframe"],[])

    def test_reader_reopens_after_error(self):
        env=self.env()
        class FastEvent:
            stopped=False
            def is_set(self): return self.stopped
            def set(self): self.stopped=True
            def wait(self,delay): return self.stopped
        class Port:
            opened=True
            reads=0
            def isOpen(self): return self.opened
            def close(self): self.opened=False
            def open(self): self.opened=True
            def read(self,n):
                self.reads+=1
                if self.reads==1: raise OSError("test cable")
                return buf.read(n)
        buf=io.BytesIO(self.packet(env,[0]*6))
        env["event"]=FastEvent()
        frames={"old":1}
        seen=[]
        env["_am"]=SimpleNamespace(frames_lock=threading.Lock(),frames=frames,
                                   note=lambda key,regs:seen.append((key,regs)))
        env.update(ser=Port(),_pump_frame_last_at={"R141":1.0,"R241":1.0},
                   _last_block_ts={6:0},UPDATE_INTERVAL_SEC=1,
                   gpiocontrol=lambda *a:None,GetParametersNEW=lambda *a:None)
        def start(*args):
            env["event"].set()
            return True
        env["_hpi_start_once"]=start
        exec(PATCH["READER"],env)
        with self.assertLogs(level="ERROR"):
            env["ReadPump"]()
        self.assertEqual(seen,[("R101",[0]*6)])
        self.assertFalse(frames)
        self.assertEqual(env["_pump_frame_last_at"]["R141"],0)
        self.assertEqual(env["_hpi_serial_stats"]["reconnects"],1)
        self.assertFalse(env["ser"].isOpen())

    def test_chart_atomic_save_and_failed_write(self):
        with tempfile.TemporaryDirectory() as d:
            env=self.env()
            path=Path(d)/"charts.pkl"
            helper=PATCH["HELPER"].replace('os.path.realpath("charts.pkl")',repr(str(path)))
            exec(helper,env)
            fn=next(n for n in ast.parse(helper).body if isinstance(n,ast.FunctionDef) and n.name=="_hpi_save_charts")
            names=ast.literal_eval(fn.body[0].value)
            self.assertEqual(len(names),37)
            for i,name in enumerate(names):
                env[name]=collections.deque([i],maxlen=8640)
            env["_hpi_save_charts"]()
            path.chmod(0o640)
            env["_hpi_save_charts"]()
            self.assertEqual(path.stat().st_mode & 0o777,0o640)
            original=path.read_bytes()
            self.assertEqual([x[0] for x in pickle.loads(original)],list(range(37)))
            def fail(*args):
                raise OSError("disk write failure")
            env["pickle"]=SimpleNamespace(dump=fail)
            with self.assertRaises(OSError):
                env["_hpi_save_charts"]()
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(list(Path(d).iterdir()),[path])

if __name__=="__main__":
    unittest.main()
