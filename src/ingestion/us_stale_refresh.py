import time
from datetime import date, timedelta

from src.db.session import get_connection
from src.ingestion.edgar_sync import mark_unavailable, sync_edgar_market, upsert_price, yfinance_symbol
from src.ingestion.sync_state import acquire_sync_lock, begin_sync_job, finish_sync_job, release_sync_lock, upsert_sync_state
from src.providers.edgar_client import EdgarClient
from src.providers.price_client import PriceClient


DEFAULT_STALE_DAYS = 10
DEFAULT_UNAVAILABLE_RETRY_DAYS = 30


def default_stale_before(as_of=None, stale_days=DEFAULT_STALE_DAYS):
    as_of = as_of or date.today()
    return (as_of - timedelta(days=int(stale_days))).isoformat()


def unavailable_retry_modifier(days):
    return "-%d days" % max(int(days or 0), 0)


def recent_unavailable_filter(exclude_recent_unavailable=True, unavailable_retry_days=DEFAULT_UNAVAILABLE_RETRY_DAYS):
    if not exclude_recent_unavailable:
        return "", []
    return (
        """
        AND NOT EXISTS (
          SELECT 1
          FROM unavailable_data u
          WHERE u.market = 'us'
            AND u.source = 'yfinance'
            AND u.data_type = 'prices'
            AND UPPER(u.identifier) = UPPER(latest.ticker)
            AND u.last_seen_at >= datetime(CURRENT_TIMESTAMP, ?)
        )
        """,
        [unavailable_retry_modifier(unavailable_retry_days)],
    )


def select_stale_us_price_rows(
    conn,
    stale_before=None,
    limit=50,
    include_no_price=True,
    exclude_recent_unavailable=True,
    unavailable_retry_days=DEFAULT_UNAVAILABLE_RETRY_DAYS,
):
    stale_before = stale_before or default_stale_before()
    where = "latest_price_date < ?"
    params = [stale_before]
    if include_no_price:
        where = "(latest_price_date IS NULL OR latest_price_date < ?)"
    unavailable_sql, unavailable_params = recent_unavailable_filter(exclude_recent_unavailable, unavailable_retry_days)
    params.extend(unavailable_params)
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
          %s
        ORDER BY
          CASE WHEN latest_price_date IS NULL THEN 0 ELSE 1 END,
          latest_price_date,
          ticker
        LIMIT ?
    """ % (where, unavailable_sql)
    params.append(int(limit or 50))
    return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def count_stale_us_price_companies(
    conn,
    stale_before=None,
    include_no_price=True,
    exclude_recent_unavailable=True,
    unavailable_retry_days=DEFAULT_UNAVAILABLE_RETRY_DAYS,
):
    stale_before = stale_before or default_stale_before()
    where = "latest_price_date < ?"
    params = [stale_before]
    if include_no_price:
        where = "(latest_price_date IS NULL OR latest_price_date < ?)"
    unavailable_sql, unavailable_params = recent_unavailable_filter(exclude_recent_unavailable, unavailable_retry_days)
    params.extend(unavailable_params)
    sql = """
        WITH latest AS (
          SELECT c.id, c.ticker, MAX(p.trade_date) AS latest_price_date
          FROM company_master c
          LEFT JOIN prices p ON p.company_id = c.id
          WHERE c.market = 'us'
            AND c.ticker IS NOT NULL
            AND TRIM(c.ticker) <> ''
          GROUP BY c.id
        )
        SELECT COUNT(*)
        FROM latest
        WHERE %s
          %s
    """ % (where, unavailable_sql)
    return conn.execute(sql, tuple(params)).fetchone()[0]


def latest_price_dates(conn, tickers):
    tickers = [str(ticker).upper() for ticker in tickers or [] if str(ticker).strip()]
    if not tickers:
        return {}
    placeholders = ",".join("?" for _ in tickers)
    rows = conn.execute(
        """
        SELECT UPPER(c.ticker) AS ticker, MAX(p.trade_date) AS latest_price_date
        FROM company_master c
        LEFT JOIN prices p ON p.company_id = c.id
        WHERE c.market = 'us'
          AND UPPER(c.ticker) IN (%s)
        GROUP BY c.id
        """ % placeholders,
        tuple(tickers),
    ).fetchall()
    return {row["ticker"]: row["latest_price_date"] for row in rows}


def price_date_advanced(before, after):
    if not after:
        return False
    if not before:
        return True
    return str(after) > str(before)


def mark_non_advancing_price_rows(conn, rows, before_dates, reason_suffix=None):
    after_dates = latest_price_dates(conn, [row["ticker"] for row in rows])
    marked = []
    for row in rows:
        ticker = str(row["ticker"]).upper()
        before = before_dates.get(ticker)
        after = after_dates.get(ticker)
        if price_date_advanced(before, after):
            continue
        reason = "No newer yfinance price rows"
        if reason_suffix:
            reason = "%s (%s)" % (reason, reason_suffix)
        if before or after:
            reason = "%s; latest_before=%s latest_after=%s" % (reason, before, after)
        mark_unavailable(conn, "us", "yfinance", "prices", ticker, reason)
        marked.append(ticker)
    if marked:
        conn.commit()
    return marked


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
        "marked_unavailable_prices",
        "no_price_tickers",
        "warnings",
    ]
    compact = {key: result.get(key) for key in keys if key in result}
    if isinstance(compact.get("warnings"), list):
        compact["warnings"] = compact["warnings"][:5]
        compact["warnings_count"] = len(result.get("warnings") or [])
    return compact


def run_selected_us_price_tickers(conn, tickers, start_date=None, end_date=None, price_client=None, **_kwargs):
    price_client = price_client or PriceClient()
    target_tickers = [str(ticker).strip().upper() for ticker in tickers or [] if str(ticker).strip()]
    symbols_by_ticker = {ticker: yfinance_symbol(ticker) for ticker in target_tickers}
    symbols = list(dict.fromkeys(symbols_by_ticker.values()))

    if hasattr(price_client, "fetch_ohlc_batch"):
        rows_by_symbol = price_client.fetch_ohlc_batch(symbols, start_date=start_date, end_date=end_date)
    else:
        rows_by_symbol = {
            symbol: price_client.fetch_ohlc(symbol, start_date=start_date, end_date=end_date)
            for symbol in symbols
        }

    inserted_prices = 0
    inserted_by_ticker = {}
    no_price_tickers = []
    warnings = []
    for ticker in target_tickers:
        company = conn.execute(
            """
            SELECT id
            FROM company_master
            WHERE market = 'us' AND UPPER(ticker) = ?
            LIMIT 1
            """,
            (ticker,),
        ).fetchone()
        if not company:
            warnings.append("%s: company record not found" % ticker)
            no_price_tickers.append(ticker)
            continue

        ticker_inserted = 0
        for price in rows_by_symbol.get(symbols_by_ticker[ticker], []) or []:
            if upsert_price(conn, company["id"], price):
                ticker_inserted += 1
        if ticker_inserted:
            inserted_prices += ticker_inserted
            inserted_by_ticker[ticker] = ticker_inserted
        else:
            no_price_tickers.append(ticker)

    if target_tickers and not inserted_prices and len(no_price_tickers) == len(target_tickers):
        if price_provider_probe_failed(price_client, start_date=start_date, end_date=end_date):
            raise RuntimeError("yfinance price provider returned no rows for the whole batch and failed the AAPL probe.")

    conn.commit()
    return {
        "target_codes": target_tickers,
        "updated_companies": 0,
        "inserted_prices": inserted_prices,
        "inserted_prices_by_ticker": inserted_by_ticker,
        "inserted_financials": 0,
        "inserted_filings": 0,
        "inserted_actions": 0,
        "skipped_unavailable": 0,
        "no_price_tickers": no_price_tickers,
        "warnings": warnings,
    }


def price_provider_probe_failed(price_client, start_date=None, end_date=None):
    if not hasattr(price_client, "fetch_ohlc"):
        return False
    try:
        start = start_date or (date.today() - timedelta(days=30)).isoformat()
        rows = price_client.fetch_ohlc("AAPL", start_date=start, end_date=end_date)
    except Exception:
        return True
    return not bool(rows)


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
    if not include_financials and not include_filings and not include_dividends:
        return run_selected_us_price_tickers(
            conn,
            tickers,
            start_date=start_date,
            end_date=end_date,
        )

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
    exclude_recent_unavailable=True,
    unavailable_retry_days=DEFAULT_UNAVAILABLE_RETRY_DAYS,
    mark_unavailable_on_no_prices=True,
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
        "exclude_recent_unavailable": exclude_recent_unavailable,
        "unavailable_retry_days": unavailable_retry_days,
        "mark_unavailable_on_no_prices": mark_unavailable_on_no_prices,
    }
    conn = get_connection(db_path)
    job_id = None
    lock_owner = None
    try:
        lock_owner = acquire_sync_lock(conn, "sync:writer")
        if record_state:
            job_id = begin_sync_job(conn, "stale_price_refresh", "us", "edgar", "stale_prices", params)
            upsert_sync_state(conn, "us", "edgar", "stale_prices", "running", params, message="古い米国株価を再取得中")

        remaining_before = count_stale_us_price_companies(
            conn,
            stale_before,
            include_no_price,
            exclude_recent_unavailable,
            unavailable_retry_days,
        )
        batches = []
        processed_tickers = []
        marked_unavailable_tickers = []
        stopped_reason = "complete"
        runner = sync_func or run_selected_us_tickers

        for _ in range(max(int(max_batches or 0), 0)):
            rows = select_stale_us_price_rows(
                conn,
                stale_before,
                batch_limit,
                include_no_price,
                exclude_recent_unavailable,
                unavailable_retry_days,
            )
            if not rows:
                stopped_reason = "complete"
                break

            tickers = [row["ticker"] for row in rows]
            before_dates = {str(row["ticker"]).upper(): row.get("latest_price_date") for row in rows}
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
            marked_unavailable = []
            if mark_unavailable_on_no_prices:
                marked_unavailable = mark_non_advancing_price_rows(
                    conn,
                    rows,
                    before_dates,
                    reason_suffix="stale refresh start=%s end=%s" % (effective_start, end_date or "latest"),
                )
                result["marked_unavailable_prices"] = len(marked_unavailable)
            marked_unavailable_tickers.extend(marked_unavailable)
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

            if (result.get("inserted_prices") or 0) <= 0 and not marked_unavailable:
                stopped_reason = "not_advancing"
                break
            if sleep_sec:
                sleep_func(float(sleep_sec))
        else:
            remaining = count_stale_us_price_companies(
                conn,
                stale_before,
                include_no_price,
                exclude_recent_unavailable,
                unavailable_retry_days,
            )
            stopped_reason = "max_batches" if remaining else "complete"

        remaining_after = count_stale_us_price_companies(
            conn,
            stale_before,
            include_no_price,
            exclude_recent_unavailable,
            unavailable_retry_days,
        )
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
            "marked_unavailable_prices": len(marked_unavailable_tickers),
            "marked_unavailable_tickers": marked_unavailable_tickers,
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
