import time
from datetime import date, timedelta

from src.db.session import get_connection
from src.ingestion.coverage import data_coverage_rows
from src.ingestion.sync_all import sync_edgar_bulk_source, sync_jp_bulk_source
from src.ingestion.sync_state import begin_sync_job, finish_sync_job, upsert_sync_state


DEFAULT_START_DAYS = 420
DEFAULT_JP_SECTIONS = "Prime,Standard,Growth"
DEFAULT_US_EXCHANGES = "Nasdaq,NYSE"


def default_start_date():
    return (date.today() - timedelta(days=DEFAULT_START_DAYS)).isoformat()


def normalize_markets(market):
    if market == "all":
        return ["jp", "us"]
    return [market]


def pct_done(value, target):
    if value is None:
        return False
    return float(value) >= float(target)


def coverage_map(db_path=None, markets=("jp", "us")):
    conn = get_connection(db_path)
    try:
        return {row["market"]: row for row in data_coverage_rows(conn, markets=markets)}
    finally:
        conn.close()


def next_refresh_task(rows, markets, ensure_master=True, target_detail_progress_pct=100.0):
    for market in markets:
        row = rows.get(market)
        if not row:
            continue
        universe = int(row.get("universe_records") or 0)
        if ensure_master and (universe == 0 or not pct_done(row.get("master_progress_pct"), 100.0)):
            return {
                "market": market,
                "phase": "master",
                "offset": int(row.get("master_next_offset") or 0),
                "universe_records": universe,
            }
        if not pct_done(row.get("detail_progress_pct"), target_detail_progress_pct):
            return {
                "market": market,
                "phase": "detail",
                "offset": int(row.get("detail_next_offset") or 0),
                "universe_records": universe,
            }
    return None


def compact_result(result):
    keys = [
        "market",
        "source",
        "mode",
        "offset",
        "limit",
        "available_records",
        "selected_records",
        "processed_codes",
        "processed_tickers",
        "skipped_existing",
        "inserted_companies",
        "updated_companies",
        "inserted_prices",
        "inserted_financials",
        "inserted_filings",
        "inserted_dividends",
        "inserted_actions",
        "inserted_events",
        "next_offset",
        "rate_limited",
        "warnings",
    ]
    compact = {key: result.get(key) for key in keys if key in result}
    if isinstance(compact.get("warnings"), list):
        compact["warnings"] = compact["warnings"][:5]
        compact["warnings_count"] = len(result.get("warnings") or [])
    return compact


def run_refresh_task(
    task,
    start_date=None,
    end_date=None,
    batch_limit=10,
    jp_sections=DEFAULT_JP_SECTIONS,
    us_exchanges=DEFAULT_US_EXCHANGES,
    include_prices=True,
    include_financials=True,
    include_dividends=True,
    include_events=True,
    include_filings=True,
    resume=True,
    sync_jp_func=sync_jp_bulk_source,
    sync_us_func=sync_edgar_bulk_source,
):
    phase = task["phase"]
    market = task["market"]
    include_detail = phase == "detail"
    if market == "jp":
        return sync_jp_func(
            start_date=start_date,
            end_date=end_date,
            sections=jp_sections,
            offset=task["offset"],
            limit=batch_limit,
            include_prices=include_detail and include_prices,
            include_financials=include_detail and include_financials,
            include_dividends=include_detail and include_dividends,
            include_events=include_detail and include_events,
            resume=resume,
        )
    return sync_us_func(
        start_date=start_date,
        end_date=end_date,
        exchanges=us_exchanges,
        offset=task["offset"],
        limit=batch_limit,
        include_prices=include_detail and include_prices,
        include_financials=include_detail and include_financials,
        include_filings=include_detail and include_filings,
        include_dividends=include_detail and include_dividends,
        resume=resume,
    )


def finish_status(stopped_reason):
    if stopped_reason == "complete":
        return "success"
    if stopped_reason in ("rate_limited", "max_batches", "not_advancing", "no_records"):
        return "warning"
    return "failed"


def next_action(stopped_reason, task=None, result=None):
    if stopped_reason == "complete":
        return "全対象のマスター同期と詳細同期が完了しています。"
    if stopped_reason == "rate_limited":
        offset = (result or {}).get("next_offset")
        return "API制限が解けた後、同じ条件でoffset %sから再実行してください。" % offset
    if stopped_reason == "max_batches":
        return "最大バッチ数に達しました。続きは同じ条件で再実行してください。"
    if stopped_reason == "not_advancing":
        return "next_offsetが進まなかったため停止しました。直近ジョブの警告を確認してください。"
    if stopped_reason == "no_records":
        return "対象レコードがありません。市場区分や取引所フィルターを確認してください。"
    return "エラー内容を確認してください。"


def refresh_until_current(
    market="all",
    start_date=None,
    end_date=None,
    batch_limit=10,
    max_batches=10,
    sleep_sec=0,
    jp_sections=DEFAULT_JP_SECTIONS,
    us_exchanges=DEFAULT_US_EXCHANGES,
    include_prices=True,
    include_financials=True,
    include_dividends=True,
    include_events=True,
    include_filings=True,
    resume=True,
    ensure_master=True,
    target_detail_progress_pct=100.0,
    db_path=None,
    record_state=True,
    sync_jp_func=sync_jp_bulk_source,
    sync_us_func=sync_edgar_bulk_source,
    sleep_func=time.sleep,
):
    markets = normalize_markets(market)
    start_date = start_date or default_start_date()
    params = {
        "market": market,
        "start_date": start_date,
        "end_date": end_date,
        "batch_limit": batch_limit,
        "max_batches": max_batches,
        "sleep_sec": sleep_sec,
        "jp_sections": jp_sections,
        "us_exchanges": us_exchanges,
        "include_prices": include_prices,
        "include_financials": include_financials,
        "include_dividends": include_dividends,
        "include_events": include_events,
        "include_filings": include_filings,
        "resume": resume,
        "ensure_master": ensure_master,
        "target_detail_progress_pct": target_detail_progress_pct,
    }
    job_id = None
    if record_state:
        conn = get_connection(db_path)
        try:
            job_id = begin_sync_job(conn, "refresh_until_current", market, "refresh", "until_current", params)
            upsert_sync_state(conn, market, "refresh", "until_current", "running", params, message="最新化ジョブ実行中")
        finally:
            conn.close()

    coverage_before = coverage_map(db_path, markets)
    batches = []
    stopped_reason = "complete"
    last_task = None
    last_result = None
    try:
        for _ in range(max(int(max_batches or 0), 0)):
            rows = coverage_map(db_path, markets)
            task = next_refresh_task(
                rows,
                markets,
                ensure_master=ensure_master,
                target_detail_progress_pct=target_detail_progress_pct,
            )
            if not task:
                stopped_reason = "complete"
                break

            last_task = task
            result = run_refresh_task(
                task,
                start_date=start_date,
                end_date=end_date,
                batch_limit=batch_limit,
                jp_sections=jp_sections,
                us_exchanges=us_exchanges,
                include_prices=include_prices,
                include_financials=include_financials,
                include_dividends=include_dividends,
                include_events=include_events,
                include_filings=include_filings,
                resume=resume,
                sync_jp_func=sync_jp_func,
                sync_us_func=sync_us_func,
            )
            last_result = result
            batches.append({"task": task, "result": compact_result(result)})

            if result.get("rate_limited"):
                stopped_reason = "rate_limited"
                break
            if int(result.get("selected_records") or 0) == 0:
                stopped_reason = "no_records"
                break
            if int(result.get("next_offset") or 0) <= int(task["offset"]):
                stopped_reason = "not_advancing"
                break
            if sleep_sec:
                sleep_func(float(sleep_sec))
        else:
            rows = coverage_map(db_path, markets)
            task = next_refresh_task(
                rows,
                markets,
                ensure_master=ensure_master,
                target_detail_progress_pct=target_detail_progress_pct,
            )
            stopped_reason = "max_batches" if task else "complete"

        coverage_after = coverage_map(db_path, markets)
        result = {
            "market": market,
            "source": "refresh",
            "mode": "until_current",
            "message": "最新化ジョブを実行しました。",
            "stopped_reason": stopped_reason,
            "next_action": next_action(stopped_reason, last_task, last_result),
            "batches_run": len(batches),
            "batches": batches,
            "coverage_before": coverage_before,
            "coverage_after": coverage_after,
        }
        if record_state:
            conn = get_connection(db_path)
            try:
                status = finish_status(stopped_reason)
                finish_sync_job(conn, job_id, status, result, result["next_action"])
                upsert_sync_state(conn, market, "refresh", "until_current", status, params, result, result["next_action"])
            finally:
                conn.close()
        return result
    except Exception as exc:
        if record_state:
            conn = get_connection(db_path)
            try:
                result = {"error": str(exc), "batches_run": len(batches), "batches": batches}
                finish_sync_job(conn, job_id, "failed", result, str(exc))
                upsert_sync_state(conn, market, "refresh", "until_current", "failed", params, result, str(exc))
            finally:
                conn.close()
        raise
