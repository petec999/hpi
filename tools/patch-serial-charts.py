#!/usr/bin/env python3
"""Fail-closed patch for the alpha13 serial reader, mailbox and charts."""
import ast
import re
import textwrap

MARK = "# HPI SERIAL AND CHART GUARDS v1"
HELPER = '''# HPI SERIAL AND CHART GUARDS v1
_hpi_mailbox_lock = threading.Lock()
_hpi_command = None
_hpi_chart_lock = threading.RLock()
_hpi_serial_stats = {"valid":0,"crc_errors":0,"short_frames":0,"reconnects":0,
                     "write_timeouts":0,"write_failures":0}

def _hpi_crc(data):
    crc = 0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    return crc

def _hpi_read_packet(port):
    if port.read(1) != b"\\x11":
        return None
    header = port.read(2)
    if len(header) != 2:
        _hpi_serial_stats["short_frames"] += 1
        return None
    if header[0] != 3 or header[1] not in (2,12,32,44):
        return None
    size = header[1]
    body = port.read(size+2)
    if len(body) != size+2:
        _hpi_serial_stats["short_frames"] += 1
        return None
    if _hpi_crc(b"\\x11"+header+body[:-2]) != int.from_bytes(body[-2:],"little"):
        _hpi_serial_stats["crc_errors"] += 1
        return None
    _hpi_serial_stats["valid"] += 1
    return [int.from_bytes(body[i:i+2],"big") for i in range(0,size,2)]

def _hpi_send(register, frame, timeout_s=12.0):
    global _hpi_command, newframe, writed
    if event.is_set():
        return False
    if (not isinstance(register,(list,tuple)) or not isinstance(frame,(list,tuple))
            or len(register)!=len(frame) or len(frame) not in (1,6)
            or any(type(v) is not int or not 0<=v<=65535 for v in frame)):
        return False
    # The reader must never acquire this controller-side lock.
    with _am.serial_lock:
        with _hpi_mailbox_lock:
            if _hpi_command is not None or event.is_set():
                return False
            cmd={"data":[list(register),list(frame)],"done":threading.Event(),
                 "deadline":time.monotonic()+timeout_s,"started":False,"ok":False}
            _hpi_command=cmd
            newframe=cmd["data"]
            writed="0"
        cmd["done"].wait(timeout_s)
        with _hpi_mailbox_lock:
            if cmd["done"].is_set():
                return cmd["ok"]
            _hpi_serial_stats["write_timeouts"] += 1
            if _hpi_command is cmd and not cmd["started"]:
                _hpi_command=None
                newframe=[]
            # If already executing, keep the slot occupied until the reader
            # finishes. A late acknowledgement cannot satisfy a new request.
            return False

def _hpi_take():
    global _hpi_command, newframe
    with _hpi_mailbox_lock:
        cmd=_hpi_command
        if cmd is None:
            return None
        if event.is_set() or time.monotonic() >= cmd["deadline"]:
            _hpi_command=None
            newframe=[]
            cmd["done"].set()
            return None
        cmd["started"]=True
        return cmd

def _hpi_finish(cmd, ok):
    global _hpi_command, newframe, writed
    with _hpi_mailbox_lock:
        if _hpi_command is cmd:
            cmd["ok"]=bool(ok)
            if not ok:
                _hpi_serial_stats["write_failures"] += 1
            _hpi_command=None
            newframe=[]
            writed="0"
            cmd["done"].set()

def _hpi_save_charts():
    names = (''' + '"datechart","tankchart","twichart","twochart","tdchart","tschart","thichart","thochart","taochart","pdsetchart","pdactchart","pssetchart","psactchart","eevlevelchart","fan1chart","fan2chart","tsatpdsetchart","tsatpdactchart","tsatpssetchart","tsatpsactchart","intempchart","outtempchart","humidchart","hcurvechart","fsetchart","factchart","flimitonchart","modechart_quiet","modechart_eco","modechart_turbo","threewaychart","superheatchart","subcoolingchart","tdefchart","defrostchart","antifreezechart","heaterchart"' + ''')
    with _hpi_chart_lock:
        rows=[collections.deque(globals()[name],maxlen=8640) for name in names]
    path=os.path.realpath("charts.pkl")
    try:
        st=os.stat(path)
    except FileNotFoundError:
        st=None
    fd,tmp=tempfile.mkstemp(prefix=".charts-",dir=os.path.dirname(path))
    try:
        with os.fdopen(fd,"wb") as stream:
            if st is not None:
                os.fchmod(stream.fileno(),st.st_mode & 0o777)
                if os.geteuid()==0:
                    os.fchown(stream.fileno(),st.st_uid,st.st_gid)
            pickle.dump(rows,stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp,path)
        dirfd=os.open(os.path.dirname(path),os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

'''

READER = '''def ReadPump():
    global R101, R141, R201, R241
    global last_pump_rx_ts, last_pump_rx_block, last_pump_rx_len, last_pump_error
    banks={6:"R101",16:"R141",1:"R201",22:"R241"}
    delay=2
    event.wait(.2)
    while not event.is_set():
        try:
            if not ser.isOpen():
                ser.open()
                gpiocontrol("modbus","0")
                _hpi_serial_stats["reconnects"] += 1
                logging.info("RS485 port reopened")
            cmd=_hpi_take()
            if cmd is not None:
                ok=False
                try:
                    ok=WritePump(cmd["data"],cmd["deadline"])
                finally:
                    _hpi_finish(cmd,ok)
            if event.is_set():
                break
            regs=_hpi_read_packet(ser)
            if regs is None:
                continue
            delay=2
            size=len(regs)
            key=banks[size]
            globals()[key]=regs
            _am.note(key,regs)
            if key in _pump_frame_last_at:
                _pump_frame_last_at[key]=time.monotonic()
            last_pump_rx_ts=time.time()
            last_pump_rx_block=key
            last_pump_rx_len=size
            last_pump_error=""
            now_ts=time.time()
            if now_ts-_last_block_ts[size]>=UPDATE_INTERVAL_SEC:
                if _hpi_start_once(key,GetParametersNEW,(regs,)):
                    _last_block_ts[size]=now_ts
        except Exception:
            last_pump_error=traceback.format_exc()
            logging.error("RS485 reader error; retry in %ss",delay)
            logging.debug(last_pump_error)
            with _am.frames_lock:
                _am.frames.clear()
            for key in _pump_frame_last_at:
                _pump_frame_last_at[key]=0.0
            try:
                ser.close()
            except Exception:
                pass
            try:
                gpiocontrol("modbus","0")
            except Exception:
                logging.exception("Cannot restore RS485 receive direction")
            event.wait(delay)
            delay=min(delay*2,30)
    try:
        ser.close()
    except Exception:
        logging.exception("RS485 close failed")
'''

# Preserve the exact old reader to support upgrades of already patched systems.
READER_V1 = READER
READER = READER.replace(
    "    event.wait(.2)\n    while",
    "    # HPI RS485 SILENCE RECOVERY v2\n    last_valid=time.monotonic()\n    event.wait(.2)\n    while"
).replace(
    '                ser.open()\n                gpiocontrol("modbus","0")',
    '                gpiocontrol("modbus","0")\n                ser.open()\n                last_valid=time.monotonic()'
).replace(
    "            if regs is None:\n                continue\n            delay=2",
    "            if regs is None:\n                if time.monotonic()-last_valid>=90:\n                    raise TimeoutError('RS485: no valid frame for 90 s')\n                continue\n            last_valid=time.monotonic()\n            delay=2"
)
SER_OPEN = 'ser = serial.Serial(port=modbusdev, baudrate = 9600, parity=serial.PARITY_EVEN,stopbits=serial.STOPBITS_ONE,bytesize=serial.EIGHTBITS,timeout=1)'
SER_DEFER = SER_OPEN.replace("port=modbusdev","port=None") + "\nser.port = modbusdev"

def upgrade_reader(source):
    if "# HPI RS485 SILENCE RECOVERY v2" not in source:
        if READER_V1.rstrip() not in source:
            raise ValueError("Unexpected installed serial reader")
        source=replace_func(source,"ReadPump",READER)
    if SER_DEFER not in source:
        if source.count(SER_OPEN)!=1:
            raise ValueError("Unexpected serial initialization")
        source=source.replace(SER_OPEN,SER_DEFER,1)
    return source

def replace_func(source,name,replacement,parent=None):
    tree=ast.parse(source)
    if parent:
        tree=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==parent)
    matches=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name]
    if len(matches)!=1:
        raise ValueError("Unexpected function: "+name)
    n=matches[0]
    lines=source.splitlines(keepends=True)
    lines[n.lineno-1:n.end_lineno]=[textwrap.indent(replacement.rstrip()+"\n"," "*n.col_offset)]
    return "".join(lines)

def patch(source):
    if MARK in source:
        if HELPER not in source:
            raise ValueError("Modified serial guard")
        return upgrade_reader(source)
    def once(old,new):
        nonlocal source
        if source.count(old)!=1:
            raise ValueError("Unexpected serial/chart anchor: "+old[:100])
        source=source.replace(old,new,1)
    if "_hpi_start_once" not in source:
        raise ValueError("Install core resource guards first")
    # Keep the existing write protocol and retry conditions, but make the
    # result request-local, check the deadline and always restore RX direction.
    source,n=re.subn(r'(?m)^def WritePump\(newframe\):[ \t]*(?:#[^\n]*)?$',
                     lambda _: HELPER+"def WritePump(newframe, deadline):",source)
    if n!=1:
        raise ValueError("Unexpected WritePump signature")
    once("        global writed\n        if count == 6:","        if count == 6:")
    once("        time.sleep(1)\n        modbus.connect()\n        for x in range(5):\n            time.sleep(1)",
         "        if event.wait(1) or time.monotonic() >= deadline:\n            return False\n        if not modbus.connect():\n            return False\n        for x in range(5):\n            if event.wait(1) or time.monotonic() >= deadline:\n                return False")
    once('                logging.info(f"Modbus write result: {result}")\n                time.sleep(0.1)',
         '                logging.info(f"Modbus write result: {result}")\n                if result.isError():\n                    continue\n                time.sleep(0.1)')
    once('                result=modbus.read_holding_registers(register, count, unit=17)\n                logging.info(f"Newframe[0]: {newframe[0]}")',
         '                result=modbus.read_holding_registers(register, count, unit=17)\n                if result.isError() or len(result.registers)!=count:\n                    return False\n                logging.info(f"Newframe[0]: {newframe[0]}")')
    once('                    writed = "1"\n                    break','                    return True')
    once('        modbus.close()\n        gpiocontrol("modbus","0")\n        return True','        return False')
    once('            WriteRegisters(len(newframe[1]))\n        except:\n            gpiocontrol("modbus", "0")',
         '            return WriteRegisters(len(newframe[1]))\n        finally:\n            try:\n                modbus.close()\n            finally:\n                gpiocontrol("modbus", "0")')
    # Preserve the original bus-direction switch timing; don't start a write
    # after its caller timed out or shutdown began.
    once('        gpiocontrol("modbus", "1")\n        break;',
         '        if event.is_set() or time.monotonic() >= deadline:\n            return False\n        gpiocontrol("modbus", "1")\n        break;')
    source=replace_func(source,"ReadPump",READER)
    source=upgrade_reader(source)
    source=replace_func(source,"set_newframe","def set_newframe(register, frame):\n    return _hpi_send(register,frame)")
    source=replace_func(source,"_send_and_wait","def _send_and_wait(frame, timeout_s=12.0):\n    return _hpi_send(R101,frame,timeout_s)",parent="statechange")
    # Do not let another caller interleave the wake-up and target mode writes.
    once('            ok = True\n            if (not _is_on) and str(newstate).strip().lower() != \'off\':',
         '            with _am.serial_lock:\n                ok = True\n                if (not _is_on) and str(newstate).strip().lower() != \'off\':')
    wake_comment=re.search(r'(?m)^                ok = _send_and_wait\(PyHaier\.SetState\(R101, "on"\), timeout_s=12\.0\)\n(                #[^\n]*\n)                time\.sleep\(0\.3\)$',source)
    if wake_comment is None:
        raise ValueError("Unexpected state wake-up sequence")
    once('                ok = _send_and_wait(PyHaier.SetState(R101, "on"), timeout_s=12.0)\n'+wake_comment[1]+'                time.sleep(0.3)\n\n            if ok:\n                ok = _send_and_wait(PyHaier.SetState(R101, newstate), timeout_s=12.0)',
         '                    ok = _send_and_wait(PyHaier.SetState(R101, "on"), timeout_s=12.0)\n                    # Wait for the next observed state as in the original code.\n                    time.sleep(0.3)\n\n                if ok:\n                    ok = _send_and_wait(PyHaier.SetState(R101, newstate), timeout_s=12.0)')
    # Collect a complete chart row before publishing it; readers see all or none.
    once('    if _do_chart: datechart.append(str(now))','    _chart_row={}\n    if _do_chart: _chart_row["datechart"]=str(now)')
    pattern=r'(?m)^    if _do_chart: (\w+)\.append\((.*)\)$'
    source,n=re.subn(pattern,lambda m:'    if _do_chart: _chart_row["'+m[1]+'"]='+m[2],source)
    if n!=36:
        raise ValueError("Unexpected chart series count: "+str(n))
    once('    socketlocal.emit("chart_update", {','    if _do_chart:\n        with _hpi_chart_lock:\n            if not event.is_set():\n                for name,value in _chart_row.items():\n                    globals()[name].append(value)\n    socketlocal.emit("chart_update", {')
    # Snapshot all series under the same lock while preparing chart responses.
    tree=ast.parse(source)
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="gen_charts")
    lines=source.splitlines(keepends=True)
    start=node.body[0].lineno-1
    lines[start:node.end_lineno]=["    with _hpi_chart_lock:\n"]+["    "+l if l.strip() else l for l in lines[start:node.end_lineno]]
    source="".join(lines)
    pattern=r"(?m)^    with open\('charts\.pkl', 'wb'\) as f:\n        pickle\.dump\([^\n]+\n"
    source,n=re.subn(pattern,'    event.set()\n    try:\n        _hpi_save_charts()\n    except Exception:\n        logging.exception("Cannot save chart snapshot")\n',source)
    if n!=1:
        raise ValueError("Unexpected chart save")
    compile(source,"main.py","exec")
    return source
