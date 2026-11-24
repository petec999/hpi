"""Read-only compressor and defrost event counters for HaierPi.

No heat-pump controls are changed. Feed only decoded, fresh observations.
"""
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import json
import math
import os
import tempfile


@dataclass
class DailyCounters:
    date: str
    compressor_starts: int = 0
    compressor_seconds: float = 0.0
    compressor_completed_cycles: int = 0
    compressor_last_cycle_seconds: float = 0.0
    defrost_starts: int = 0
    defrost_seconds: float = 0.0
    defrost_completed_cycles: int = 0
    defrost_last_cycle_seconds: float = 0.0


class CycleCounter:
    """Conservative, sample-based daily counter with atomic persistence.

    First sample after startup, a telemetry gap or restart is a baseline,
    never a new start. Runtime is credited only between agreeing ON samples.
    """

    def __init__(self, path, *, max_gap_seconds=180.0, compressor_on_hz=1.0):
        self.path = Path(path)
        self.max_gap_seconds = float(max_gap_seconds)
        self.compressor_on_hz = float(compressor_on_hz)
        if not math.isfinite(self.max_gap_seconds) or self.max_gap_seconds <= 0:
            raise ValueError("Invalid sample gap")
        if not math.isfinite(self.compressor_on_hz) or self.compressor_on_hz <= 0:
            raise ValueError("Invalid compressor threshold")
        self.daily = None
        self._interrupt()
        self._load()

    def _interrupt(self):
        self._last_time = None
        self._last_comp = None
        self._last_defrost = None
        self._comp_cycle_seconds = 0.0
        self._defrost_cycle_seconds = 0.0

    def _load(self):
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") != 1:
                raise ValueError("Unsupported counter file version")
            self.daily = DailyCounters(**payload["daily"])
        # Intentionally do not restore last observed ON/OFF states.

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".haier_counter_", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "daily": asdict(self.daily)}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def observe(self, timestamp: datetime, *, compressor_hz, defrost,
                r141_fresh, r241_fresh):
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Timestamp must be timezone-aware")
        today = timestamp.date().isoformat()
        if self.daily is None or self.daily.date != today:
            self.daily = DailyCounters(date=today)
            self._interrupt()

        valid = (r141_fresh is True and r241_fresh is True and
                 isinstance(compressor_hz, (int, float)) and
                 not isinstance(compressor_hz, bool) and
                 math.isfinite(compressor_hz) and 0 <= compressor_hz <= 250 and
                 type(defrost) is bool)
        if not valid:
            self._interrupt()
            self._save()
            return asdict(self.daily)

        comp = compressor_hz >= self.compressor_on_hz
        delta = None
        if self._last_time is not None:
            delta = (timestamp - self._last_time).total_seconds()
            if not 0 < delta <= self.max_gap_seconds:
                self._interrupt()
                delta = None

        if delta is not None:
            if self._last_comp and comp:
                self.daily.compressor_seconds += delta
                self._comp_cycle_seconds += delta
            elif self._last_comp is False and comp:
                self.daily.compressor_starts += 1
            elif self._last_comp and not comp:
                self.daily.compressor_completed_cycles += 1
                self.daily.compressor_last_cycle_seconds = self._comp_cycle_seconds
                self._comp_cycle_seconds = 0.0

            if self._last_defrost and defrost:
                self.daily.defrost_seconds += delta
                self._defrost_cycle_seconds += delta
            elif self._last_defrost is False and defrost:
                self.daily.defrost_starts += 1
            elif self._last_defrost and not defrost:
                self.daily.defrost_completed_cycles += 1
                self.daily.defrost_last_cycle_seconds = self._defrost_cycle_seconds
                self._defrost_cycle_seconds = 0.0

        self._last_time = timestamp
        self._last_comp = comp
        self._last_defrost = defrost
        self._save()
        return asdict(self.daily)
