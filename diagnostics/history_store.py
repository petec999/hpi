"""Read-only SQLite telemetry history and event journal for HaierPi.

Storage is independent of HaierPi release directories. No Modbus writes.
"""
import csv
import json
import math
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS samples (
  id INTEGER PRIMARY KEY,
  timestamp TEXT NOT NULL,
  unique_id TEXT NOT NULL,
  value REAL NOT NULL,
  unit TEXT,
  UNIQUE(timestamp, unique_id)
);
CREATE INDEX IF NOT EXISTS samples_time ON samples(timestamp);
CREATE INDEX IF NOT EXISTS samples_uid_time ON samples(unique_id,timestamp);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  timestamp TEXT NOT NULL,
  event_type TEXT NOT NULL,
  source TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT
);
CREATE INDEX IF NOT EXISTS events_time ON events(timestamp);
"""


def utc_now():
    return datetime.now(timezone.utc)


def iso_utc(timestamp):
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
        raise ValueError("Expected timezone-aware datetime")
    return timestamp.astimezone(timezone.utc).isoformat(timespec="seconds")


class HistoryStore:
    def __init__(self, filename):
        self.path = Path(filename)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        with self._lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    def close(self):
        with self._lock:
            self.db.close()

    def sample(self, unique_id, value, unit=None, timestamp=None):
        timestamp = utc_now() if timestamp is None else timestamp
        if not isinstance(unique_id, str) or not unique_id.startswith("HaierPi_"):
            raise ValueError("Only HaierPi sensor IDs accepted")
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Nonfinite or nonnumeric measurement")
        with self._lock, self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO samples(timestamp, unique_id, value, unit) VALUES (?,?,?,?)",
                (iso_utc(timestamp), unique_id, float(value), unit))

    def event(self, kind, source, previous, current, timestamp=None):
        timestamp = utc_now() if timestamp is None else timestamp
        if not kind or not source:
            raise ValueError("Event kind and source required")
        with self.db:
            self.db.execute(
                "INSERT INTO events(timestamp, event_type, source, old_value, new_value) VALUES (?,?,?,?,?)",
                (iso_utc(timestamp), str(kind), str(source),
                 None if previous is None else str(previous),
                 None if current is None else str(current)))

    def prune(self, days=90, now=None):
        if not 1 <= days <= 3650:
            raise ValueError("Retention must be between 1 and 3650 days")
        now = utc_now() if now is None else now
        cutoff = iso_utc(now - timedelta(days=days))
        with self.db:
            n_samples = self.db.execute("DELETE FROM samples WHERE timestamp < ?", (cutoff,)).rowcount
            n_events = self.db.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,)).rowcount
        return n_samples, n_events

    def export_csv(self, destination, table, since=None, until=None):
        if table not in ("samples", "events"):
            raise ValueError("Unsupported export")
        names = ("timestamp", "unique_id", "value", "unit") if table == "samples" else (
            "timestamp", "event_type", "source", "old_value", "new_value")
        clauses = []
        params = []
        for operation, instant in ((">=", since), ("<=", until)):
            if instant is not None:
                clauses.append("timestamp " + operation + " ?")
                params.append(iso_utc(instant))
        sql = "SELECT " + ", ".join(names) + " FROM " + table
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY timestamp, id"
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(names)
            writer.writerows(self.db.execute(sql, params))
        return path

    def summary(self):
        with self._lock:
            return {
            "sample_count": self.db.execute("SELECT count(*) FROM samples").fetchone()[0],
            "event_count": self.db.execute("SELECT count(*) FROM events").fetchone()[0],
            "first_sample": self.db.execute("SELECT min(timestamp) FROM samples").fetchone()[0],
            "last_sample": self.db.execute("SELECT max(timestamp) FROM samples").fetchone()[0],
            }
