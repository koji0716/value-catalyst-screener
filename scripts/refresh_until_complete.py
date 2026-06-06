import argparse
import ctypes
import json
import os
import sys
import time
from datetime import datetime, timezone

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.db.migrations import init_db
from src.db.session import get_connection
from src.ingestion.coverage import data_coverage_rows
from src.ingestion.refresh import refresh_until_current


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append_log(path, payload):
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path, payload):
    if not path:
        return
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def coverage(markets):
    conn = get_connection()
    try:
        return {row["market"]: row for row in data_coverage_rows(conn, markets=markets)}
    finally:
        conn.close()


def is_complete(row, target):
    return (
        row
        and float(row.get("master_progress_pct") or 0.0) >= 100.0
        and float(row.get("detail_progress_pct") or 0.0) >= float(target)
    )


def parse_markets(value):
    if value == "all":
        return ["jp", "us"]
    return [value]


def coverage_summary(rows):
    parts = []
    for market in sorted(rows):
        row = rows[market]
        parts.append(
            "%s detail %.1f%%, master %.1f%%"
            % (
                market,
                float(row.get("detail_progress_pct") or 0.0),
                float(row.get("master_progress_pct") or 0.0),
            )
        )
    return "; ".join(parts)


def notify_completion(args, rows):
    payload = {
        "at": utc_now(),
        "event": "complete",
        "coverage": rows,
        "summary": coverage_summary(rows),
        "log": args.log,
    }
    write_json(args.done_file, payload)
    append_log(args.log, {"at": utc_now(), "event": "notified", "method": args.notify, "done_file": args.done_file})

    if args.notify == "none":
        return
    message = "DB refresh complete.\n%s\n\nLog: %s\nDone: %s" % (
        payload["summary"],
        args.log,
        args.done_file,
    )
    if args.notify == "beep":
        try:
            ctypes.windll.user32.MessageBeep(0x40)
        except Exception:
            print("\a", end="", flush=True)
        return
    if args.notify == "messagebox":
        try:
            ctypes.windll.user32.MessageBeep(0x40)
            ctypes.windll.user32.MessageBoxW(0, message, "Value Catalyst Screener", 0x40)
        except Exception:
            print(message, flush=True)


def run(args):
    init_db()
    markets = parse_markets(args.market)
    consecutive_errors = 0

    while True:
        rows = coverage(markets)
        if all(is_complete(rows.get(market), args.target_detail_progress) for market in markets):
            append_log(args.log, {"at": utc_now(), "event": "complete", "coverage": rows})
            notify_completion(args, rows)
            return 0

        progressed = False
        for market in markets:
            row = rows.get(market)
            if is_complete(row, args.target_detail_progress):
                continue

            params = {
                "market": market,
                "start_date": args.start_date,
                "end_date": args.end_date,
                "batch_limit": args.jp_limit if market == "jp" else args.us_limit,
                "max_batches": args.jp_batches if market == "jp" else args.us_batches,
                "sleep_sec": args.batch_sleep,
                "jp_sections": args.jp_sections,
                "us_exchanges": args.us_exchanges,
                "target_detail_progress_pct": args.target_detail_progress,
            }
            append_log(
                args.log,
                {
                    "at": utc_now(),
                    "event": "run_start",
                    "market": market,
                    "coverage": row,
                    "params": params,
                },
            )

            try:
                result = refresh_until_current(**params)
                consecutive_errors = 0
                progressed = True
                append_log(
                    args.log,
                    {
                        "at": utc_now(),
                        "event": "run_finish",
                        "market": market,
                        "stopped_reason": result.get("stopped_reason"),
                        "batches_run": result.get("batches_run"),
                        "next_action": result.get("next_action"),
                        "coverage_after": result.get("coverage_after", {}).get(market),
                    },
                )
                if result.get("stopped_reason") == "rate_limited":
                    append_log(
                        args.log,
                        {
                            "at": utc_now(),
                            "event": "sleep",
                            "market": market,
                            "seconds": args.rate_limit_sleep,
                            "reason": "rate_limited",
                        },
                    )
                    time.sleep(float(args.rate_limit_sleep))
            except Exception as exc:
                consecutive_errors += 1
                wait_seconds = min(float(args.error_sleep) * consecutive_errors, float(args.max_error_sleep))
                append_log(
                    args.log,
                    {
                        "at": utc_now(),
                        "event": "error",
                        "market": market,
                        "error": str(exc),
                        "seconds": wait_seconds,
                    },
                )
                time.sleep(wait_seconds)

        if not progressed:
            append_log(
                args.log,
                {
                    "at": utc_now(),
                    "event": "sleep",
                    "seconds": args.idle_sleep,
                    "reason": "no_progress",
                },
            )
            time.sleep(float(args.idle_sleep))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", default="all", choices=["jp", "us", "all"])
    parser.add_argument("--from", dest="start_date", default="2025-01-01")
    parser.add_argument("--to", dest="end_date")
    parser.add_argument("--jp-sections", default="all")
    parser.add_argument("--us-exchanges", default="all")
    parser.add_argument("--jp-limit", type=int, default=5)
    parser.add_argument("--us-limit", type=int, default=25)
    parser.add_argument("--jp-batches", type=int, default=5)
    parser.add_argument("--us-batches", type=int, default=4)
    parser.add_argument("--batch-sleep", type=float, default=1.0)
    parser.add_argument("--rate-limit-sleep", type=float, default=180.0)
    parser.add_argument("--error-sleep", type=float, default=60.0)
    parser.add_argument("--max-error-sleep", type=float, default=900.0)
    parser.add_argument("--idle-sleep", type=float, default=60.0)
    parser.add_argument("--target-detail-progress", type=float, default=100.0)
    parser.add_argument("--log", default="data/raw/refresh_until_complete.jsonl")
    parser.add_argument("--done-file", default="data/raw/refresh_until_complete.done.json")
    parser.add_argument("--notify", default="messagebox", choices=["messagebox", "beep", "none"])
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
