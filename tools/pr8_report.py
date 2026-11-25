#!/usr/bin/env python3
"""Read-only PR8 SQLite report and optional CSV export (Python 3.9+).

Does not create or modify the SQLite database, MQTT, service units or HaierPi.
For memory-constrained HaierPi, streamed CSV output is optional. Default is a
short console summary without any extra installation.
"""
import argparse
import csv
import os
from pathlib import Path
import sqlite3
import sys


def report(db_path, samples_csv=None, events_csv=None):
    db = Path(db_path)
    if not db.is_file():
        raise FileNotFoundError("PR8 database not found: " + str(db))
    uri = db.resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        count_samples = con.execute("SELECT count(*) FROM samples").fetchone()[0]
        count_events = con.execute("SELECT count(*) FROM events").fetchone()[0]
        first, last = con.execute(
            "SELECT min(timestamp), max(timestamp) FROM samples").fetchone()
        print("PR8 SQLite (read only):", db)
        print("Samples:", count_samples, "| Events:", count_events)
        print("First sample:", first or "none")
        print("Last sample:", last or "none")
        print("DB size:", db.stat().st_size, "bytes")
        for extra in ("-wal", "-shm"):
            part = Path(str(db) + extra)
            if part.exists():
                print(extra, part.stat().st_size, "bytes")
        print("\nSamples grouped by sensor:")
        for uid, n in con.execute(
            "SELECT unique_id, count(*) FROM samples GROUP BY unique_id ORDER BY count(*) DESC"):
            print("  {}: {}".format(uid, n))
        print("\nLast 10 events:")
        for at, src, before, after in con.execute(
            "SELECT timestamp, source, old_value, new_value FROM events "
            "ORDER BY id DESC LIMIT 10"):
            print("  {}  {}: {} -> {}".format(at, src, before, after))
        for kind, output, query, headers in (
            ("samples", samples_csv,
             "SELECT timestamp, unique_id, value, unit FROM samples ORDER BY id",
             ("timestamp", "unique_id", "value", "unit")),
            ("events", events_csv,
             "SELECT timestamp, event_type, source, old_value, new_value "
             "FROM events ORDER BY id",
             ("timestamp", "event_type", "source", "old_value", "new_value")),
        ):
            if output:
                target = Path(output)
                if target.resolve() == db.resolve():
                    raise ValueError("CSV output cannot overwrite PR8 database")
                if target.exists():
                    raise FileExistsError("Refusing to overwrite existing file: " + str(target))
                target.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(headers)
                    for row in con.execute(query):
                        writer.writerow(row)
                print("Exported {}: {}".format(kind, target))
    finally:
        con.close()


def main():
    p = argparse.ArgumentParser(description="Safe read-only HaierPi PR8 SQLite report")
    p.add_argument("--db", default="/var/lib/haierpi/history.sqlite")
    p.add_argument("--samples-csv", help="Optional new CSV path; never overwrites")
    p.add_argument("--events-csv", help="Optional new CSV path; never overwrites")
    args = p.parse_args()
    try:
        report(args.db, args.samples_csv, args.events_csv)
    except (OSError, sqlite3.Error, ValueError) as e:
        sys.exit("ERROR: " + str(e))


if __name__ == "__main__":
    main()
