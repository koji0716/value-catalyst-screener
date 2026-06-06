import argparse
import ctypes
import json
from datetime import datetime, timezone


SYNCHRONIZE = 0x00100000
INFINITE = 0xFFFFFFFF


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def wait_for_pid(pid):
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        return False
    try:
        ctypes.windll.kernel32.WaitForSingleObject(handle, INFINITE)
        return True
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def write_jsonl(path, payload):
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def show_message(title, message, notify):
    if notify == "none":
        return
    if notify in ("beep", "messagebox"):
        try:
            ctypes.windll.user32.MessageBeep(0x40)
        except Exception:
            print("\a", end="", flush=True)
    if notify == "messagebox":
        try:
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)
        except Exception:
            print(message, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--title", default="Value Catalyst Screener")
    parser.add_argument("--message", default="refresh_until_complete.py finished.")
    parser.add_argument("--notify", default="messagebox", choices=["messagebox", "beep", "none"])
    parser.add_argument("--log", default="data/raw/refresh_until_complete.notify.jsonl")
    args = parser.parse_args()

    write_jsonl(args.log, {"at": now_utc(), "event": "watch_start", "pid": args.pid})
    found = wait_for_pid(args.pid)
    payload = {"at": now_utc(), "event": "process_exit", "pid": args.pid, "process_found": found}
    write_jsonl(args.log, payload)
    show_message(args.title, args.message, args.notify)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
