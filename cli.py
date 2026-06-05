import argparse
import importlib.util
import json
import shutil
import subprocess
import sys

from src.analysis.backtest import run_simple_backtest
from src.analysis.scoring import explain_ticker, screen_companies
from src.db.migrations import init_db
from src.db.session import get_connection
from src.ingestion.sync_all import sync_market
from src.nlp.report_generator import export_results
from src.utils.file_utils import DISCLAIMER, ensure_runtime_dirs, load_presets


def format_number(value):
    if value is None:
        return "N/A"
    if abs(value) >= 1_000_000_000_000:
        return "%.2f兆" % (value / 1_000_000_000_000)
    if abs(value) >= 100_000_000:
        return "%.2f億" % (value / 100_000_000)
    if isinstance(value, float):
        return "%.2f" % value
    return str(value)


def add_common_screen_args(parser):
    parser.add_argument("--market", default="all", choices=["all", "jp", "us"])
    parser.add_argument("--preset", default="balanced")
    parser.add_argument("--max-per", type=float, dest="max_per")
    parser.add_argument("--max-pbr", type=float, dest="max_pbr")
    parser.add_argument("--min-equity-ratio", type=float, dest="min_equity_ratio")
    parser.add_argument("--limit", type=int)


def command_init(args):
    ensure_runtime_dirs()
    init_db()
    result = sync_market(market="jp", use_sample=True, reset_sample=args.reset_sample)
    print("Initialized database.")
    print(result["message"])
    print(DISCLAIMER)


def command_sync(args):
    init_db()
    result = sync_market(market=args.market, start_date=args.start_date, end_date=args.end_date, use_sample=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(DISCLAIMER)


def command_screen(args):
    overrides = {
        "max_per": args.max_per,
        "max_pbr": args.max_pbr,
        "min_equity_ratio": args.min_equity_ratio,
    }
    results, run_id = screen_companies(
        preset_name=args.preset,
        market=args.market,
        overrides=overrides,
        limit=args.limit,
        save=True,
    )
    print("run_id: %s" % run_id)
    print("count: %s" % len(results))
    print(
        "ticker | company | score | label | PER | PBR | ROE | eq_ratio | catalyst | reason"
    )
    for item in results:
        print(
            "%s | %s | %.2f | %s | %s | %s | %s%% | %s%% | %s | %s"
            % (
                item.get("ticker"),
                item.get("company_name"),
                item.get("total_score", 0),
                item.get("recommendation_label"),
                format_number(item.get("per")),
                format_number(item.get("pbr")),
                format_number(item.get("roe")),
                format_number(item.get("equity_ratio")),
                item.get("catalyst_count", 0),
                item.get("reason_summary"),
            )
        )
    print(DISCLAIMER)


def command_explain(args):
    _, text = explain_ticker(args.ticker, preset_name=args.preset)
    print(text)


def command_report(args):
    results, _ = screen_companies(preset_name=args.preset, market=args.market, limit=args.limit, save=True)
    path = export_results(results, preset=args.preset, output_format=args.format)
    print("Report written: %s" % path)
    print(DISCLAIMER)


def command_backtest(args):
    result = run_simple_backtest(
        market=args.market,
        preset=args.preset,
        start_date=args.start_date,
        end_date=args.end_date,
        holding_months=args.holding_months,
        top_n=args.top_n,
    )
    printable = dict(result)
    printable["holdings"] = [
        {
            "ticker": item["ticker"],
            "company_name": item["company_name"],
            "total_score": item["total_score"],
            "return_6m": item.get("return_6m"),
            "return_12m": item.get("return_12m"),
        }
        for item in result["holdings"]
    ]
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    print(DISCLAIMER)


def command_app(args):
    if importlib.util.find_spec("streamlit"):
        return subprocess.call(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "src/ui/streamlit_app.py",
                "--server.headless=true",
                "--browser.gatherUsageStats=false",
            ]
        )
    streamlit = shutil.which("streamlit")
    if not streamlit:
        print("Streamlit is not installed. Run: python -m pip install -r requirements.txt")
        print("After installing, run: python cli.py app")
        return 1
    return subprocess.call([streamlit, "run", "src/ui/streamlit_app.py"])


def find_company(conn, ticker):
    value = str(ticker).upper()
    return conn.execute(
        """
        SELECT * FROM company_master
        WHERE UPPER(COALESCE(ticker, '')) = ?
           OR security_code = ?
           OR UPPER(COALESCE(edinet_code, '')) = ?
        LIMIT 1
        """,
        (value, value, value),
    ).fetchone()


def command_watchlist(args):
    conn = get_connection()
    try:
        if args.watch_action == "show":
            rows = conn.execute(
                """
                SELECT c.ticker, c.company_name, c.market, w.label, w.created_at
                FROM watchlist w
                JOIN company_master c ON c.id = w.company_id
                ORDER BY w.created_at DESC
                """
            ).fetchall()
            if not rows:
                print("Watchlist is empty.")
            for row in rows:
                print("%s | %s | %s | %s" % (row["ticker"], row["company_name"], row["market"], row["label"] or ""))
            return

        company = find_company(conn, args.ticker)
        if not company:
            raise SystemExit("Company not found: %s" % args.ticker)
        if args.watch_action == "add":
            conn.execute(
                """
                INSERT INTO watchlist (company_id, label)
                VALUES (?, ?)
                ON CONFLICT(company_id) DO UPDATE SET label = excluded.label
                """,
                (company["id"], args.label),
            )
            conn.commit()
            print("Added: %s %s" % (company["ticker"], company["company_name"]))
        elif args.watch_action == "remove":
            conn.execute("DELETE FROM watchlist WHERE company_id = ?", (company["id"],))
            conn.commit()
            print("Removed: %s %s" % (company["ticker"], company["company_name"]))
    finally:
        conn.close()


def command_presets(args):
    presets = load_presets()
    for name, config in presets.items():
        print("%s: %s" % (name, config.get("description", "")))


def build_parser():
    parser = argparse.ArgumentParser(description="Value Catalyst Screener")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--reset-sample", action="store_true", help="Clear sample-backed tables before seeding.")
    init.set_defaults(func=command_init)

    app = sub.add_parser("app")
    app.set_defaults(func=command_app)

    sync = sub.add_parser("sync")
    sync.add_argument("--market", default="jp", choices=["jp", "us", "all"])
    sync.add_argument("--from", dest="start_date")
    sync.add_argument("--to", dest="end_date")
    sync.set_defaults(func=command_sync)

    screen = sub.add_parser("screen")
    add_common_screen_args(screen)
    screen.set_defaults(func=command_screen)

    explain = sub.add_parser("explain")
    explain.add_argument("--ticker", required=True)
    explain.add_argument("--preset", default="balanced")
    explain.set_defaults(func=command_explain)

    report = sub.add_parser("report")
    report.add_argument("--preset", default="balanced")
    report.add_argument("--market", default="all", choices=["all", "jp", "us"])
    report.add_argument("--format", default="csv", choices=["csv", "html"])
    report.add_argument("--limit", type=int)
    report.set_defaults(func=command_report)

    backtest = sub.add_parser("backtest")
    backtest.add_argument("--market", default="jp", choices=["jp", "us", "all"])
    backtest.add_argument("--preset", default="balanced")
    backtest.add_argument("--from", dest="start_date", required=True)
    backtest.add_argument("--to", dest="end_date", required=True)
    backtest.add_argument("--holding-months", type=int, default=6)
    backtest.add_argument("--top-n", type=int, default=20)
    backtest.set_defaults(func=command_backtest)

    watchlist = sub.add_parser("watchlist")
    watch_sub = watchlist.add_subparsers(dest="watch_action", required=True)
    watch_add = watch_sub.add_parser("add")
    watch_add.add_argument("--ticker", required=True)
    watch_add.add_argument("--label", default="")
    watch_add.set_defaults(func=command_watchlist)
    watch_remove = watch_sub.add_parser("remove")
    watch_remove.add_argument("--ticker", required=True)
    watch_remove.set_defaults(func=command_watchlist)
    watch_show = watch_sub.add_parser("show")
    watch_show.set_defaults(func=command_watchlist)

    presets = sub.add_parser("presets")
    presets.set_defaults(func=command_presets)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    result = args.func(args)
    return int(result or 0)


if __name__ == "__main__":
    sys.exit(main())
