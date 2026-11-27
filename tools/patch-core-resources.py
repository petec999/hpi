#!/usr/bin/env python3
"""Bound workers, network queues and retained chart history on HaierPi alpha13."""
import re

MARK = '# HPI CORE RESOURCE GUARDS v1'
HELPER = '''# HPI CORE RESOURCE GUARDS v1
_hpi_worker_lock = threading.Lock()
_hpi_active_workers = set()

def _hpi_start_once(key, target, args=()):
    # No backlog: a later periodic reading will provide current data.
    if event.is_set():
        return False
    with _hpi_worker_lock:
        if key in _hpi_active_workers:
            return False
        _hpi_active_workers.add(key)
    def run():
        try:
            target(*args)
        except Exception:
            logging.exception("HaierPi worker failed: %s", key)
        finally:
            with _hpi_worker_lock:
                _hpi_active_workers.discard(key)
    try:
        threading.Thread(target=run, daemon=True, name="hpi-"+key).start()
    except BaseException:
        with _hpi_worker_lock:
            _hpi_active_workers.discard(key)
        raise
    return True

'''

CONFIG_HELPER = '''# HPI ATOMIC CONFIG WRITE v1
_hpi_config_write_lock = threading.Lock()

def _hpi_save_config():
    # Only serialize writes, not hardware calls. Keep the existing symlink target.
    with _hpi_config_write_lock:
        path = os.path.realpath('/opt/config.ini')
        buf = io.StringIO()
        config.write(buf)
        data = buf.getvalue().encode('utf-8')
        try:
            with open(path, 'rb') as old:
                if old.read() == data:
                    return
            st = os.stat(path)
        except FileNotFoundError:
            st = None
        fd, tmp = tempfile.mkstemp(prefix='.config-', dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, 'wb') as stream:
                if st is not None:
                    os.fchmod(stream.fileno(), st.st_mode & 0o777)
                    if os.geteuid() == 0:
                        os.fchown(stream.fileno(), st.st_uid, st.st_gid)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
            dirfd = os.open(os.path.dirname(path), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

'''

def config_patch(source):
    if CONFIG_HELPER in source:
        return source
    if source.count('def loadconfig():') != 1:
        raise ValueError('Unexpected config loader')
    source=source.replace('def loadconfig():',CONFIG_HELPER+'def loadconfig():',1)
    pattern = r"(?m)^( +)with open\('/opt/config\.ini', 'w'\) as configfile:\n\1    config\.write\(configfile\)\n"
    def replacement(match):
        indent=match.group(1)
        # The local and remote bulk-settings loops save once, after all fields.
        tail=source[match.end():]
        if indent == ' '*16 and tail.startswith(("            emit('return',", "            sio_remote.emit('return_from_device',")):
            indent=' '*12
        return indent+'_hpi_save_config()\n'
    source,n=re.subn(pattern,replacement,source)
    if n!=8:
        raise ValueError('Unexpected config writer count')
    compile(source,'main.py','exec')
    return source


def patch(source):
    if MARK in source:
        if HELPER not in source:
            raise ValueError('Modified resource guard')
        return config_patch(source)
    def once(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError('Unexpected source anchor: '+old[:100])
        source = source.replace(old,new,1)
    once('def GetParameters():', HELPER+'def GetParameters():')
    for name in ('GetDHT22','GetInsideTemp','GetOutsideTemp','GetHumidity','GetDHWTemp','hpiapp'):
        pattern = r'threading\.Thread\(target='+name+r'(?:, args=(\([^\n]*?\)))?, daemon=True\)\.start\(\)'
        source,n = re.subn(pattern,lambda m: '_hpi_start_once("'+name+'", '+name+((', '+m.group(1)) if m.group(1) else '')+')',source)
        if n!=1:
            raise ValueError('Unexpected sensor worker: '+name)
    for bank,count in ((101,6),(141,16),(201,1),(241,22)):
        old='threading.Thread(target=GetParametersNEW, args=(R%d,), daemon=True).start()'%bank
        once(old,'_hpi_start_once("R%d", GetParametersNEW, (R%d,))'%(bank,bank))
        old='                    R%d=T%d\n'%(bank,bank)
        once(old,'                    if len(T%d) != %d:\n                        continue\n'%(bank,count)+old)
    old='                        if rs:\n                            T'
    if source.count(old)!=4:
        raise ValueError('Unexpected register read layout')
    source=source.replace(old,'                        if len(rs) == 4:\n                            T')
    source,n = re.subn(r'(?m)^            resp\s*=\s*requests\.get\(url, headers=headers\)$', '            resp = requests.get(url, headers=headers, timeout=(3, 5))', source)
    if n!=2:
        raise ValueError('Unexpected HTTP call layout')
    once('        # Configure callbacks\n','        # Bound QoS 1 messages during disconnects (Paho default is unlimited).\n        cl.max_queued_messages_set(512)\n        # Configure callbacks\n')
    once('            globals()[_name] = _value\n','            _default = globals()[_name]\n            if not isinstance(_value, (list, tuple, collections.deque)):\n                continue\n            _seq = list(_value)[-8640:]\n            globals()[_name] = collections.deque(list(_default)[:8640-len(_seq)]+_seq, maxlen=8640)\n')
    once('    logging.info("Cannot load charts pickle")\n','    logging.info("Cannot load charts pickle")\nfinally:\n    # Do not keep a second copy of the deserialized chart data.\n    for _chart_tmp in ("_charts_data", "_value", "_val", "_seq", "_pad", "_default"):\n        globals().pop(_chart_tmp, None)\n')
    once("            proc = subprocess.Popen(['journalctl', '-t', 'HaierPi', '-p','debug'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)\n            f=open(\"/opt/haier/crashlog-\"+crash_date+\".log\", \"w\")\n            for line in iter(proc.stdout.readline, ''):\n                f.write(line)\n            f.close()\n            with open(\"/opt/haier/crashlog-\"+crash_date+\".log\", \"r\") as f:\n                files = {\"file\": f}\n                headers = {'Authorization': f\"Bearer {hpikey}\"}\n                r=requests.post(\"https://app.haierpi.pl/upload\", files=files, headers=headers)\n", '''            try:
                # Keep only recent diagnostics; never wait forever for journal or upload.
                path = "/opt/haier/crashlog-"+crash_date+".log"
                proc = subprocess.run(['journalctl', '-t', 'HaierPi', '-n', '1000', '--no-pager'],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
                with open(path, "wb") as f:
                    f.write(proc.stdout[-1024*1024:])
                # Preserve local diagnostics; remote upload only when portal is enabled.
                if hpiatstart == '1':
                    with open(path, "rb") as f:
                        with requests.post("https://app.haierpi.pl/upload", files={"file": f},
                                           headers={'Authorization': f"Bearer {hpikey}"}, timeout=(3, 10)) as response:
                            response.raise_for_status()
            except Exception:
                logging.exception("Crash diagnostic failed")
''')
    compile(source,'main.py','exec')
    return config_patch(source)
