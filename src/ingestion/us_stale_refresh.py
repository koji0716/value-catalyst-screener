import time
from datetime import date, timedelta

from src.db.session import get_connection
from src.ingestion.edgar_sync import sync_edgar_market
from src.ingestion.sync_state import acquire_sync_lock, begin_sync_job, finish_sync_job, release_sync_lock, upsert_sync_state
from src.providers.edgar_client import EdgarClient


DEFAULT_STALE_DAYS = 10


def default_stale_before(as_of=None, stale_days=DEFAULT_STALE_DAYS):
    as_of = as_of or date.today()
    return (as_of - timedelta(days=int(stale_days))).isoformat()


def select_stale_us_price_rows(conn, stale_before=None, limit=50, include_no_price=True):
    stale_before = stale_before or default_stale_before()
    where = "latest_price_date < ?"
    params = [stale_before]
    if include_no_price:
        where = "(latest_price_date IS NULL OR latest_price_date < ?)"
    sql = """
        WITH latest AS (
          SELECT
            c.id,
            c.ticker,
            c.company_name,
            c.exchange,
            MAX(p.trade_date) AS latest_price_date
          FROM company_master c
          LEFT JOIN prices p ON p.company_id = c.id
          WHERE c.market = 'us'
            AND c.ticker IS NOT NULL
            AND TRIM(c.ticker) <> ''
          GROUP BY c.id
        )
        SELECT *
        FROM latest
        WHERE %s
        ORDER BY
          CASE WHEN latest_price_date IS NULL THEN 0 ELSE 1 END,
          latest_price_date,
          ticker
        LIMIT ?
    """ % where
    params.append(int(limit or 50))
    return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def count_stale_us_price_companies(conn, stale_before=None, include_no_price=True):
    stale_before = stale_before or default_stale_before()
    where = "latest_price_date < ?"
    params = [stale_before]
    if include_no_price:
        where = "(latest_price_date IS NULL OR latest_price_date < ?)"
    sql = """
        WITH latest AS (
          SELECT c.id, MAX(p.trade_date) AS latest_price_date
          FROM company_master c
          LEFT JOIN prices p ON p.company_id = c.id
          WHERE c.market = 'us'
          GROUP BY c.id
        )
        SELECT COUNT(*)
        FROM latest
        WHERE %s
    """ % where
    return conn.execute(sql, tuple(params)).fetchone()[0]


def batch_start_date(rows, fallback_days=420):
    dates = [row.get("latest_price_date") for row in rows if row.get("latest_price_date")]
    if dates:
        return min(dates)
    return (date.today() - timedelta(days=int(fallback_days))).isoformat()


def compact_batch_result(result):
    keys = [
        "target_codes",
        "updated_companies",
        "inserted_prices",
        "inserted_financials",
        "inserted_filings",
        "inserted_actions",
        "skipped_unavailable",
        "warnings",
    ]
    compact = {key: result.get(key) for key in keys if key in result}
    if isinstance(compact.get("warnings"), list):
        compact["warnings"] = compact["warnings"][:5]
        compact["warnings_count"] = len(result.get("warnings") or [])
    return compact


def run_selected_us_tickers(
    conn,
    tickers,
    start_date=None,
    end_date=None,
    include_financials=False,
    include_filings=False,
    include_dividends=False,
    user_agent=None,
):
    client = EdgarClient(user_agent=user_agent)
    if not client.is_configured():
        # Let the existing error message and job handling stay consistent.
        from src.providers.edgar_client import EdgarError

        raise EdgarError("SEC_USER_AGENT is not configured.")
    with client:
        return sync_edgar_market(
            conn,
            edgar_client=client,
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            include_prices=True,
            include_financials=include_financials,
            include_filings=include_filings,
            include_dividends=include_dividends,
        )


def refresh_stale_us_prices(
    start_date=None,
    end_date=None,
    stale_before=None,
    batch_limit=50,
    max_batches=1,
    sleep_sec=0,
    include_no_price=True,
    include_financials=False,
    include_filings=False,
    include_dividends=False,
    user_agent=None,
    db_path=None,
    record_state=True,
    sync_func=None,
    sleep_func=time.sleep,
):
    stale_before = stale_before or default_stale_before()
    params = {
        "market": "us",
        "source": "edgar",
        "mode": "stale_prices",
        "start_date": start_date,
        "end_date": end_date,
        "stale_before": stale_before,
        "batch_limit": batch_limit,
        "max_batches": max_batches,
        "sleep_sec": sleep_sec,
        "include_no_price": include_no_price,
        "include_financials": include_financials,
        "include_filings": include_filings,
        "include_dividends": include_dividends,
    }
    conn = get_connection(db_path)
    job_id = None
    lock_owner = None
    try:
        lock_owner = acquire_sync_lock(conn, "sync:writer")
        if record_state:
            job_id = begin_sync_job(conn, "stale_price_refresh", "us", "edgar", "stale_prices", params)
            upsert_sync_state(conn, "us", "edgar", "stale_prices", "running", params, message="古い米国株価を再取得中")

        remaining_before = count_stale_us_price_companies(conn, stale_before, include_no_price)
        batches = []
        processed_tickers = []
        stopped_reason = "complete"
        runner = sync_func or run_selected_us_tickers

        for _ in range(max(int(max_batches or 0), 0)):
            rows = select_stale_us_price_rows(conn, stale_before, batch_limit, include_no_price)
            if not rows:
                stopped_reason = "complete"
                break

            tickers = [row["ticker"] for row in rows]
            effective_start = start_date or batch_start_date(rows)
            result = runner(
                conn=conn,
                tickers=tickers,
                start_date=effective_start,
                end_date=end_date,
                include_financials=include_financials,
                include_filings=include_filings,
                include_dividends=include_dividends,
                user_agent=user_agent,
            )
            batch = {
                "selected_tickers": tickers,
                "selected_records": len(tickers),
                "stale_before": stale_before,
                "start_date": effective_start,
                "end_date": end_date,
                "result": compact_batch_result(result),
            }
            batches.append(batch)
            processed_tickers.extend(tickers)

            if (result.get("inserted_prices") or 0) <= 0:
                stopped_reason = "not_advancing"
                break
            if sleep_sec:
                sleep_func(float(sleep_sec))
        else:
            remaining = count_stale_us_price_companies(conn, stale_before, include_no_price)
            stopped_reason = "max_batches" if remaining else "complete"

        remaining_after = count_stale_us_price_companies(conn, stale_before, include_no_price)
        inserted_prices = sum((batch["result"].get("inserted_prices") or 0) for batch in batches)
        result = {
            "market": "us",
            "source": "edgar",
            "mode": "stale_prices",
            "message": "古い米国株価を再取得しました。",
            "stopped_reason": stopped_reason,
            "stale_before": stale_before,
            "batches_run": len(batches),
            "selected_records": len(processed_tickers),
            "processed_tickers": processed_tickers,
            "inserted_prices": inserted_prices,
            "remaining_stale_before": remaining_before,
            "remaining_stale_after": remaining_after,
            "batches": batches,
        }
        if record_state:
            status = "success" if stopped_reason == "complete" else "warning"
            message = "古い米国株価の再取得が完了しました。" if status == "success" else "古い米国株価の再取得を途中で停止しました。"
            finish_sync_job(conn, job_id, status, result, message)
            upsert_sync_state(conn, "us", "edgar", "stale_prices", status, params, result, message)
        return result
    except Exception as exc:
        if record_state and job_id:
            error_result = {"error": str(exc), "stale_before": stale_before}
            finish_sync_job(conn, job_id, "failed", error_result, str(exc))
            upsert_sync_state(conn, "us", "edgar", "stale_prices", "failed", params, error_result, str(exc))
        raise
    finally:
        release_sync_lock(conn, "sync:writer", lock_owner)
        conn.close()
