#!/usr/bin/env python3
"""Build versioned HaierPi 1.4.5_2 distribution without modifying stable core."""
from __future__ import annotations

import ast
import gzip
import hashlib
from io import BytesIO
from pathlib import Path
import sys
import tarfile

UPSTREAM_SHA256 = "ca803a3f8777efa75a40739d2efeb0362365ffa4291d3eb76d9a231c6cb53976"
ROOT = Path(__file__).resolve().parents[1]
NAME = "HaierPi-1.4.5_2"
ADDON_FILES = [
    "install-diagnostics-light.sh",
    "install-1452.sh",
    "tools/install-mqtt-watchdog.py",
    "docs/MQTT_END_TO_END_WATCHDOG.md",
    "diagnostics/circuit_telemetry.py",
    "diagnostics/cycle_counter.py",
    "diagnostics/derive_mqtt_env.py",
    "diagnostics/install_verify.py",
    "diagnostics/mqtt_circuit_bridge.py",
    "diagnostics/mqtt_cycle_bridge.py",
    "diagnostics/source_topics.py",
    "deployment/haierpi-circuit.service",
    "deployment/haierpi-cycles.service",
    "deployment/haierpi-diagnostics.env.example",
    "deployment/haierpi-startup/start.sh",
    "docs/OVERLAYFS_AUTOSTART.md",
    "docs/CYCLE_COUNTERS.md",
    "docs/CIRCUIT_TELEMETRY.md",
    "docs/UNIFIED_SAFE_INSTALL.md",
]
CORE_ROOTS = ("main.py", "static/", "templates/", "env/")

def sha(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def check_upstream(source:Path)->bytes:
    data=source.read_bytes()
    if sha(data)!=UPSTREAM_SHA256:
        raise ValueError("Official stable checksum mismatch; refusing to build")
    with tarfile.open(fileobj=BytesIO(data),mode="r:gz") as tf:
        contents={}
        for m in tf.getmembers():
            p=m.name.removeprefix("./")
            if p.startswith("/") or ".." in Path(p).parts or m.issym() or m.islnk() or m.isdev():
                raise ValueError("Unsafe stable archive member: "+m.name)
            if m.isfile():
                if p in contents: raise ValueError("Duplicate stable member: "+p)
                if p!="main.py" and not any(p.startswith(prefix) for prefix in CORE_ROOTS[1:]):
                    raise ValueError("Unexpected stable member: "+p)
                contents[p]=tf.extractfile(m).read()
        mandatory=["main.py","env/lib/python3.9/site-packages/PyHaier/GetTao.py"]
        for path in mandatory:
            if path not in contents: raise ValueError("Missing upstream member "+path)
        main=contents["main.py"].decode("utf-8")
        ast.parse(main,filename="stable/main.py")
        import importlib.util
        spec = importlib.util.spec_from_file_location("watchdog_installer", ROOT/"tools/install-mqtt-watchdog.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        patched = installer.patch(main)
        compile(patched, "stable/main.py + watchdog", "exec")
        if patched == main or installer.patch(patched) != patched:
            raise ValueError("Watchdog patch must apply once and be idempotent")
        print("Verified watchdog patch against official stable source")
        required={
            "upstream version": 'version="1.4.5"',
            "freshness monitor": "def mqtt_pump_freshness_tick():",
            "R141 availability": "HaierPi_R141Fresh",
            "R241 availability": "HaierPi_R241Fresh",
            "legacy MQTT cleanup": "for _legacy_sensor in (",
            "correct compressor fact mapping": '''"HaierPi_Compfact", "Hz", "frequency", "measurement", "{{ value_json[1] | float }}"''',
            "correct compressor target mapping": '''"HaierPi_Compfset", "Hz", "frequency", "measurement", "{{ value_json[0] | float }}"''',
            "signed superheat": 'superheat = f"{Ts - TsatPs_act:.1f}"',
            "signed subcool": 'subcooling = f"{TsatPd_act - Thi:.1f}"',
        }
        for feature,marker in required.items():
            if marker not in main:
                raise ValueError("Official Stable no longer matches verified feature: "+feature)
        conversion={"GetTao.py":1,"GetTdef.py":1,"GetTdTs.py":2,
                    "GetTSatPd.py":2,"GetTSatPs.py":2,"GetThiTho.py":2}
        for module,n in conversion.items():
            src=contents["env/lib/python3.9/site-packages/PyHaier/"+module]
            if src.count(b"-= 4096")!=n or b"-= 4095" in src:
                raise ValueError("Stable U2 conversion is missing: "+module)
    return data

def check_addons():
    cycle=(ROOT/"diagnostics/mqtt_cycle_bridge.py").read_text()
    if "counters = CycleCounter()" not in cycle or "HPI_COUNTER_FILE" in cycle:
        raise ValueError("Cycle service must be RAM-only")
    if "haierpi-cycles haierpi-circuit" not in (ROOT/"install-diagnostics-light.sh").read_text():
        raise ValueError("Diagnostic installer must deploy named two-service layout")
    for name in ADDON_FILES:
        if not (ROOT/name).is_file(): raise FileNotFoundError(ROOT/name)
        if name.endswith(".py"):
            ast.parse((ROOT/name).read_text(),filename=name)
    if (ROOT/"diagnostics/mqtt_history.py").exists():
        raise ValueError("SQLite historian unexpectedly still present")

def add_file(tf,name:str,data:bytes,executable=False):
    info=tarfile.TarInfo(NAME+"/"+name)
    info.size=len(data)
    info.uid=0
    info.gid=0
    info.uname="root"
    info.gname="root"
    info.mtime=0
    info.mode=0o755 if executable else 0o644
    tf.addfile(info,BytesIO(data))

def main():
    if len(sys.argv)!=3:
        raise SystemExit("Usage: build_145_2.py ORIGINAL_STABLE.tar.gz OUT_DIR")
    stable=check_upstream(Path(sys.argv[1]))
    check_addons()
    dest=Path(sys.argv[2])
    dest.mkdir(parents=True,exist_ok=True)
    target=dest/"1.4.5_2.tar.gz"
    if target.exists():
        raise FileExistsError("Refuse to overwrite: "+str(target))
    entries={
        "upstream/1.4.5_stable.tar.gz": stable,
        "upstream/1.4.5_stable.sha256":
            (UPSTREAM_SHA256+"  1.4.5_stable.tar.gz\n").encode(),
        "README.md": (ROOT/"RELEASE_1.4.5_2.md").read_bytes(),
    }
    for name in ADDON_FILES:
        entries[name]=(ROOT/name).read_bytes()
    with target.open("xb") as stream:
        with gzip.GzipFile(fileobj=stream,mode="wb",filename="",mtime=0,compresslevel=6) as gz:
            with tarfile.open(fileobj=gz,mode="w",format=tarfile.PAX_FORMAT) as tf:
                for name,data in sorted(entries.items()):
                    add_file(tf,name,data,executable=name.endswith(".sh"))
    with tarfile.open(target,"r:gz") as t:
        packaged=t.extractfile(NAME+"/upstream/1.4.5_stable.tar.gz").read()
        if sha(packaged)!=UPSTREAM_SHA256:
            raise ValueError("Packaged upstream stable was modified")
        files={m.name for m in t.getmembers() if m.isfile()}
        if len(files)!=len(entries): raise ValueError("Unexpected file count")
        assert NAME+"/diagnostics/mqtt_history.py" not in files
    checksum=dest/"1.4.5_2.sha256"
    checksum.write_text(sha(target.read_bytes())+"  1.4.5_2.tar.gz\n")
    print("SUCCESS VERSION 1.4.5_2")
    print("Original Stable SHA256: "+UPSTREAM_SHA256)
    print("New package SHA256: "+sha(target.read_bytes()))
    print("Release content: original Stable unchanged + "+str(len(ADDON_FILES))+" add-on files")
    print("Source does not contain SQLite logger or recurring SD counter writes")

if __name__=="__main__":
    main()
