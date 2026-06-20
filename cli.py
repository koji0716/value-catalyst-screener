import argparse
import importlib.util
import json
import shutil
import subprocess
import sys

from src.analysis.scoring import explain_ticker, screen_companies
from src.db.migrations import init_db
from src.db.session import get_connection
from src.ingestion.coverage import data_coverage_rows
from src.utils.file_utils import DISCLAIMER, ensure_runtime_dirs, load_presets


DEFAULT_JP_SECTIONS = "Prime,Standard,Growth"
DEFAULT_US_EXCHANGES = "Nasdaq,NYSE"


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


def format_percent(value):
    if value is None:
        return "N/A"
    return "%.1f%%" % value


def format_progress(done, total, pct_value):
    if not total:
        return "N/A"
    return "%s/%s (%s)" % (int(done or 0), int(total), format_percent(pct_value))


def add_common_screen_args(parser):
    parser.add_argument("--market", default="all", choices=["all", "jp", "us"])
    parser.add_argument("--preset", default="balanced")
    parser.add_argument("--max-per", type=float, dest="max_per")
    parser.add_argument("--max-pbr", type=float, dest="max_pbr")
    parser.add_argument("--min-equity-ratio", type=float, dest="min_equity_ratio")
    parser.add_argument("--limit", type=int)


def command_init(args):
    from src.ingestion.sync_all import sync_market

    ensure_runtime_dirs()
    init_db()
    result = sync_market(market="all", use_sample=True, reset_sample=args.reset_sample)
    print("Initialized database.")
    print(result["message"])
    print(DISCLAIMER)


def command_sync(args):
    from src.ingestion.sync_all import sync_market

    init_db()
    result = sync_market(
        market=args.market,
        start_date=args.start_date,
        end_date=args.end_date,
        source=args.source,
        mode=args.mode,
        codes=args.codes,
        limit=args.limit,
        include_prices=not args.no_prices,
        include_financials=not args.no_financials,
        include_dividends=not args.no_dividends,
        include_events=not args.no_events,
        reset_sample=args.reset_sample,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(DISCLAIMER)


def command_bulk_sync_us(args):
    from src.ingestion.sync_all import sync_edgar_bulk_source
    from src.providers.edgar_client import EdgarError

    init_db()
    try:
        result = sync_edgar_bulk_source(
            start_date=args.start_date,
            end_date=args.end_date,
            exchanges=args.exchange,
            offset=args.offset,
            limit=args.limit,
            user_agent=args.user_agent,
            include_prices=not args.no_prices and not args.master_only,
            include_financials=not args.no_financials and not args.master_only,
            include_filings=not args.no_filings and not args.master_only,
            include_dividends=not args.no_dividends and not args.master_only,
            resume=not args.no_resume,
        )
    except EdgarError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(DISCLAIMER)


def command_bulk_sync_jp(args):
    from src.ingestion.sync_all import sync_jp_bulk_source
    from src.providers.jquants_client import JQuantsError

    init_db()
    try:
        result = sync_jp_bulk_source(
            start_date=args.start_date,
            end_date=args.end_date,
            sections=args.section,
            offset=args.offset,
            limit=args.limit,
            include_prices=not args.no_prices and not args.master_only,
            include_financials=not args.no_financials and not args.master_only,
            include_dividends=not args.no_dividends and not args.master_only,
            include_events=not args.no_events and not args.master_only,
            resume=not args.no_resume,
        )
    except JQuantsError as exc:
        raise SystemExit(str(exc)) from exc
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
    from src.nlp.report_generator import export_results

    results, _ = screen_companies(preset_name=args.preset, market=args.market, limit=args.limit, save=True)
    path = export_results(results, preset=args.preset, output_format=args.format)
    print("Report written: %s" % path)
    print(DISCLAIMER)


def command_backtest(args):
    from src.analysis.backtest import run_simple_backtest

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


def command_coverage(args):
    init_db()
    conn = get_connection()
    try:
        rows = data_coverage_rows(conn)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    print(
        "market | master_offset | db_companies | detail_offset | major_data | price | financial | filings | actions | major_freshness | price_fresh | financial_fresh"
    )
    for row in rows:
        print(
            "%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s"
            % (
                row["market"],
                format_progress(row["master_next_offset"], row["universe_records"], row["master_progress_pct"]),
                format_progress(row["company_count"], row["universe_records"], row["master_coverage_pct"]),
                format_progress(row["detail_next_offset"], row["universe_records"], row["detail_progress_pct"]),
                format_percent(row["major_data_coverage_pct"]),
                format_progress(row["price_company_count"], row["company_count"], row["price_coverage_pct"]),
                format_progress(
                    row["financial_company_count"],
                    row["company_count"],
                    row["financial_coverage_pct"],
                ),
                format_progress(row["filing_company_count"], row["company_count"], row["filing_coverage_pct"]),
                format_progress(row["action_company_count"], row["company_count"], row["action_coverage_pct"]),
                format_percent(row["major_freshness_pct"]),
                format_progress(
                    row["fresh_price_company_count"],
                    row["company_count"],
                    row["price_freshness_pct"],
                ),
                format_progress(
                    row["fresh_financial_company_count"],
                    row["company_count"],
                    row["financial_freshness_pct"],
                ),
            )
        )
    print("freshness assumptions: prices within 10 days, financial period_end within 18 months.")


def command_refresh(args):
    from src.ingestion.refresh import refresh_until_current

    init_db()
    result = refresh_until_current(
        market=args.market,
        start_date=args.start_date,
        end_date=args.end_date,
        batch_limit=args.limit,
        max_batches=args.max_batches,
        sleep_sec=args.sleep_sec,
        jp_sections=args.section,
        us_exchanges=args.exchange,
        include_prices=not args.no_prices,
        include_financials=not args.no_financials,
        include_dividends=not args.no_dividends,
        include_events=not args.no_events,
        include_filings=not args.no_filings,
        resume=not args.no_resume,
        ensure_master=not args.no_master,
        target_detail_progress_pct=args.target_detail_progress,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(DISCLAIMER)


def command_refresh_stale_us(args):
    from src.ingestion.us_stale_refresh import refresh_stale_us_prices

    init_db()
    result = refresh_stale_us_prices(
        start_date=args.start_date,
        end_date=args.end_date,
        stale_before=args.stale_before,
        batch_limit=args.limit,
        max_batches=args.max_batches,
        sleep_sec=args.sleep_sec,
        include_no_price=not args.exclude_no_price,
        include_financials=args.with_financials,
        include_filings=args.with_filings,
        include_dividends=args.with_dividends,
        user_agent=args.user_agent,
        exclude_recent_unavailable=not args.include_recent_unavailable,
        unavailable_retry_days=args.retry_unavailable_days,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
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


def command_mcp(args):
    try:
        from src.mcp_server.server import run_server
    except (ImportError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        print(
            'MCP requires Python 3.10+. Install it with: python -m pip install "mcp[cli]>=1.0,<2.0"',
            file=sys.stderr,
        )
        return 1
    try:
        return run_server(
            db_path=args.db_path,
            transport=args.transport,
            host=args.host,
            port=args.port,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


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

    mcp = sub.add_parser("mcp")
    mcp.add_argument("--db-path", help="SQLite path. Defaults to DB_PATH or data/value_screener.sqlite.")
    mcp.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http"])
    mcp.add_argument("--host", default="127.0.0.1")
    mcp.add_argument("--port", type=int, default=8000)
    mcp.set_defaults(func=command_mcp)

    sync = sub.add_parser("sync")
    sync.add_argument("--market", default="jp", choices=["jp", "us", "all"])
    sync.add_argument("--from", dest="start_date")
    sync.add_argument("--to", dest="end_date")
    sync.add_argument("--source", default="auto", choices=["auto", "sample", "jquants", "edinetdb", "edgar"])
    sync.add_argument("--mode", default="manual", choices=["manual", "daily", "backfill"], help="Label the sync run for state tracking.")
    sync.add_argument("--codes", help="Comma-separated issue codes, for example: 7203,9432")
    sync.add_argument("--limit", type=int, help="Limit the starter universe for price/financial sync.")
    sync.add_argument("--no-prices", action="store_true", help="Skip stock price synchronization.")
    sync.add_argument("--no-financials", action="store_true", help="Skip financial statement synchronization.")
    sync.add_argument("--no-dividends", action="store_true", help="Skip dividend synchronization.")
    sync.add_argument("--no-events", action="store_true", help="Skip earnings calendar event synchronization.")
    sync.add_argument("--reset-sample", action="store_true", help="Reset sample tables when source=sample or auto fallback.")
    sync.set_defaults(func=command_sync)

    bulk_us = sub.add_parser("bulk-sync-us")
    bulk_us.add_argument("--from", dest="start_date")
    bulk_us.add_argument("--to", dest="end_date")
    bulk_us.add_argument("--exchange", help="Comma-separated SEC exchange names. Use all or omit for all exchanges.")
    bulk_us.add_argument("--offset", type=int, default=0, help="Start position in the SEC ticker list after filtering.")
    bulk_us.add_argument("--limit", type=int, help="Maximum number of SEC ticker records to process.")
    bulk_us.add_argument("--user-agent", help="Temporary SEC User-Agent, e.g. 'ValueCatalystScreener name@example.com'.")
    bulk_us.add_argument("--master-only", action="store_true", help="Only import SEC ticker/CIK company master records.")
    bulk_us.add_argument("--no-prices", action="store_true", help="Skip yfinance stock price synchronization.")
    bulk_us.add_argument("--no-financials", action="store_true", help="Skip SEC companyfacts synchronization.")
    bulk_us.add_argument("--no-filings", action="store_true", help="Skip SEC submissions/filing list synchronization.")
    bulk_us.add_argument("--no-dividends", action="store_true", help="Skip yfinance dividend synchronization.")
    bulk_us.add_argument("--no-resume", action="store_true", help="Reprocess records even when requested data already exists.")
    bulk_us.set_defaults(func=command_bulk_sync_us)

    bulk_jp = sub.add_parser("bulk-sync-jp")
    bulk_jp.add_argument("--from", dest="start_date")
    bulk_jp.add_argument("--to", dest="end_date")
    bulk_jp.add_argument("--section", help="Comma-separated market sections, e.g. Prime,Standard,Growth. Use all or omit for all.")
    bulk_jp.add_argument("--offset", type=int, default=0, help="Start position in the J-Quants listed-info records after filtering.")
    bulk_jp.add_argument("--limit", type=int, help="Maximum number of Japanese issue records to process.")
    bulk_jp.add_argument("--master-only", action="store_true", help="Only import J-Quants listed company master records.")
    bulk_jp.add_argument("--no-prices", action="store_true", help="Skip J-Quants stock price synchronization.")
    bulk_jp.add_argument("--no-financials", action="store_true", help="Skip J-Quants financial summary synchronization.")
    bulk_jp.add_argument("--no-dividends", action="store_true", help="Skip J-Quants dividend synchronization.")
    bulk_jp.add_argument("--no-events", action="store_true", help="Skip J-Quants catalyst/event synchronization.")
    bulk_jp.add_argument("--no-resume", action="store_true", help="Reprocess records even when requested data already exists.")
    bulk_jp.set_defaults(func=command_bulk_sync_jp)

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

    coverage = sub.add_parser("coverage")
    coverage.add_argument("--json", action="store_true", help="Output raw coverage rows as JSON.")
    coverage.set_defaults(func=command_coverage)

    refresh = sub.add_parser("refresh")
    refresh.add_argument("--market", default="all", choices=["jp", "us", "all"])
    refresh.add_argument("--from", dest="start_date")
    refresh.add_argument("--to", dest="end_date")
    refresh.add_argument("--limit", type=int, default=10, help="Records per refresh batch.")
    refresh.add_argument("--max-batches", type=int, default=10, help="Maximum batches to run before yielding.")
    refresh.add_argument("--sleep-sec", type=float, default=0, help="Sleep seconds between batches.")
    refresh.add_argument("--section", default=DEFAULT_JP_SECTIONS, help="Japanese market sections for J-Quants.")
    refresh.add_argument("--exchange", default=DEFAULT_US_EXCHANGES, help="US exchanges for SEC EDGAR.")
    refresh.add_argument("--target-detail-progress", type=float, default=100.0)
    refresh.add_argument("--no-master", action="store_true", help="Do not fill missing company master records first.")
    refresh.add_argument("--no-prices", action="store_true", help="Skip stock price synchronization.")
    refresh.add_argument("--no-financials", action="store_true", help="Skip financial statement synchronization.")
    refresh.add_argument("--no-dividends", action="store_true", help="Skip dividend/corporate action synchronization.")
    refresh.add_argument("--no-events", action="store_true", help="Skip Japanese catalyst/event synchronization.")
    refresh.add_argument("--no-filings", action="store_true", help="Skip SEC filing synchronization.")
    refresh.add_argument("--no-resume", action="store_true", help="Reprocess records even when requested data already exists.")
    refresh.set_defaults(func=command_refresh)

    stale_us = sub.add_parser("refresh-stale-us")
    stale_us.add_argument("--from", dest="start_date", help="Override price fetch start date. Defaults to the oldest selected latest price date.")
    stale_us.add_argument("--to", dest="end_date")
    stale_us.add_argument("--stale-before", help="Refresh companies whose latest US price date is older than this YYYY-MM-DD date. Defaults to today minus 10 days.")
    stale_us.add_argument("--limit", type=int, default=50, help="Records per stale refresh batch.")
    stale_us.add_argument("--max-batches", type=int, default=1, help="Maximum stale batches to run before yielding.")
    stale_us.add_argument("--sleep-sec", type=float, default=0, help="Sleep seconds between batches.")
    stale_us.add_argument("--exclude-no-price", action="store_true", help="Do not include US companies with no price rows.")
    stale_us.add_argument("--with-financials", action="store_true", help="Also refresh SEC companyfacts for selected stale tickers.")
    stale_us.add_argument("--with-filings", action="store_true", help="Also refresh SEC submissions/filing lists for selected stale tickers.")
    stale_us.add_argument("--with-dividends", action="store_true", help="Also refresh yfinance dividend actions for selected stale tickers.")
    stale_us.add_argument("--user-agent", help="Temporary SEC User-Agent.")
    stale_us.add_argument("--include-recent-unavailable", action="store_true", help="Retry tickers recently marked as having no yfinance prices.")
    stale_us.add_argument("--retry-unavailable-days", type=int, default=30, help="Days to defer tickers after yfinance returns no newer prices.")
    stale_us.set_defaults(func=command_refresh_stale_us)

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
