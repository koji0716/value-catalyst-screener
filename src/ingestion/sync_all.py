from src.db.session import get_connection
from src.ingestion.edgar_sync import sync_edgar_bulk_market, sync_edgar_market
from src.ingestion.edinetdb_sync import sync_edinetdb_market
from src.ingestion.jquants_sync import (
    clear_sample_events_and_filings,
    default_price_start,
    parse_code_list,
    starter_codes,
    sync_jquants_companies,
    sync_jquants_dividends,
    sync_jquants_earnings_events,
    sync_jquants_financials,
    sync_jquants_financials_by_date_range,
    sync_jquants_prices,
    sync_jquants_prices_by_date_range,
    sync_jquants_statement_catalysts,
)
from src.ingestion.jp_bulk_sync import filtered_jp_records, record_code, sync_jp_bulk_market
from src.ingestion.sample_data import seed_sample_data
from src.ingestion.sync_state import acquire_sync_lock, begin_sync_job, finish_sync_job, release_sync_lock, upsert_sync_state
from src.providers.jquants_client import JQuantsClient, JQuantsError
from src.providers.edgar_client import EdgarClient, EdgarError
from src.utils.file_utils import load_settings


def sync_market(
    market="jp",
    start_date=None,
    end_date=None,
    source="auto",
    mode="manual",
    codes=None,
    limit=None,
    include_prices=True,
    include_financials=True,
    include_dividends=True,
    include_events=True,
    reset_sample=False,
    use_sample=None,
    record_state=True,
):
    if use_sample is True and source == "auto":
        source = "sample"

    params = {
        "market": market,
        "source": source,
        "mode": mode,
        "start_date": start_date,
        "end_date": end_date,
        "codes": parse_code_list(codes),
        "limit": limit,
        "include_prices": include_prices,
        "include_financials": include_financials,
        "include_dividends": include_dividends,
        "include_events": include_events,
    }
    job_id = None
    lock_owner = None
    if record_state:
        conn = get_connection()
        try:
            lock_owner = acquire_sync_lock(conn, "sync:writer")
            job_id = begin_sync_job(conn, "market_sync", market, source, mode, params)
            upsert_sync_state(conn, market, source, mode, "running", params, message="同期中")
        finally:
            conn.close()

    try:
        result = _sync_market_impl(
            market=market,
            start_date=start_date,
            end_date=end_date,
            source=source,
            mode=mode,
            codes=codes,
            limit=limit,
            include_prices=include_prices,
            include_financials=include_financials,
            include_dividends=include_dividends,
            include_events=include_events,
            reset_sample=reset_sample,
        )
        status = "warning" if result.get("warnings") else "success"
        result["mode"] = mode
        if record_state:
            conn = get_connection()
            try:
                finish_sync_job(conn, job_id, status, result, result.get("message"))
                upsert_sync_state(conn, market, result.get("source", source), mode, status, params, result, result.get("message"))
            finally:
                conn.close()
        return result
    except Exception as exc:
        if record_state:
            conn = get_connection()
            try:
                result = {"error": str(exc)}
                finish_sync_job(conn, job_id, "failed", result, str(exc))
                upsert_sync_state(conn, market, source, mode, "failed", params, result, str(exc))
            finally:
                conn.close()
        raise
    finally:
        if lock_owner:
            conn = get_connection()
            try:
                release_sync_lock(conn, "sync:writer", lock_owner)
            finally:
                conn.close()


def _sync_market_impl(
    market="jp",
    start_date=None,
    end_date=None,
    source="auto",
    mode="manual",
    codes=None,
    limit=None,
    include_prices=True,
    include_financials=True,
    include_dividends=True,
    include_events=True,
    reset_sample=False,
):
    if market == "all":
        if source in ("auto", "sample"):
            routes = [("jp", source), ("us", source)]
        elif source in ("jquants", "edinetdb"):
            routes = [("jp", source)]
        elif source == "edgar":
            routes = [("us", source)]
        else:
            raise ValueError("Unknown sync source: %s" % source)
        results = []
        for idx, (route_market, route_source) in enumerate(routes):
            results.append(
                _sync_market_impl(
                    market=route_market,
                    start_date=start_date,
                    end_date=end_date,
                    source=route_source,
                    mode=mode,
                    codes=codes,
                    limit=limit,
                    include_prices=include_prices,
                    include_financials=include_financials,
                    include_dividends=include_dividends,
                    include_events=include_events,
                    reset_sample=reset_sample and idx == 0,
                )
            )
        return combine_market_results(source, results)

    if market == "us":
        if source == "sample":
            return sync_sample_market(market, start_date, end_date, reset_sample=reset_sample)
        if source not in ("auto", "edgar"):
            raise ValueError("Unknown sync source for US market: %s" % source)
        client = EdgarClient()
        if not client.is_configured():
            if source == "edgar":
                raise EdgarError("SEC_USER_AGENT is not configured.")
            return sync_sample_market(market, start_date, end_date, reset_sample=reset_sample)
        try:
            with client:
                return sync_edgar_source(
                    client=client,
                    market=market,
                    start_date=start_date,
                    end_date=end_date,
                    codes=codes,
                    limit=limit,
                    include_prices=include_prices,
                    include_financials=include_financials,
                    include_filings=include_events,
                    include_dividends=include_dividends,
                )
        except EdgarError:
            if source == "edgar":
                raise
            return sync_sample_market(market, start_date, end_date, reset_sample=reset_sample)

    if market not in ("jp", "all"):
        return {
            "market": market,
            "source": source,
            "mode": mode,
            "inserted_companies": 0,
            "message": "現時点では日本株同期を優先実装しています。",
        }

    if source not in ("auto", "sample", "jquants", "edinetdb", "edgar"):
        raise ValueError("Unknown sync source: %s" % source)

    if source == "sample":
        return sync_sample_market(market, start_date, end_date, reset_sample=reset_sample)
    if source == "edinetdb":
        return sync_edinetdb_source(
            market=market,
            codes=codes,
            limit=limit,
            include_financials=include_financials,
            include_disclosures=True,
            include_text=include_events,
        )

    client = JQuantsClient()
    if not client.is_configured():
        if source == "jquants":
            raise JQuantsError("JQUANTS_API_KEY is not configured.")
        return sync_sample_market(market, start_date, end_date, reset_sample=reset_sample)

    try:
        with client:
            return sync_jquants_market(
                client=client,
                market=market,
                start_date=start_date,
                end_date=end_date,
                codes=codes,
                limit=limit,
                include_prices=include_prices,
                include_financials=include_financials,
                include_dividends=include_dividends,
                include_events=include_events,
            )
    except JQuantsError:
        if source == "jquants":
            raise
        return sync_sample_market(market, start_date, end_date, reset_sample=reset_sample)


def sync_sample_market(market, start_date=None, end_date=None, reset_sample=False):
    conn = get_connection()
    try:
        inserted = seed_sample_data(conn, reset=reset_sample, market=market)
        market_label = "日米" if market == "all" else ("米国株" if market == "us" else "日本株")
        return {
            "market": market,
            "source": "sample",
            "from": start_date,
            "to": end_date,
            "inserted_companies": inserted,
            "inserted_prices": 0,
            "inserted_financials": 0,
            "inserted_dividends": 0,
            "inserted_events": 0,
            "message": "サンプル%sデータを同期しました。" % market_label,
        }
    finally:
        conn.close()


def combine_market_results(source, results):
    combined = {
        "market": "all",
        "source": "mixed" if source == "auto" else source,
        "results": results,
        "warnings": [],
        "message": "日米データを同期しました。",
    }
    numeric_keys = [
        "inserted_companies",
        "updated_companies",
        "inserted_prices",
        "inserted_financials",
        "inserted_dividends",
        "inserted_events",
        "inserted_filings",
        "inserted_actions",
        "inserted_text_blocks",
        "inserted_risk_events",
    ]
    for key in numeric_keys:
        total = sum(int(result.get(key) or 0) for result in results)
        if total:
            combined[key] = total
    for result in results:
        for warning in result.get("warnings") or []:
            combined["warnings"].append("%s: %s" % (result.get("market"), warning))
    return combined


def sync_edinetdb_source(
    market="jp",
    codes=None,
    limit=None,
    include_financials=True,
    include_disclosures=True,
    include_text=True,
):
    conn = get_connection()
    try:
        result = sync_edinetdb_market(
            conn,
            codes=codes,
            limit=limit,
            include_financials=include_financials,
            include_disclosures=include_disclosures,
            include_text=include_text,
        )
        result.update(
            {
                "market": market,
                "message": "EDINET DBから有報・財務データを同期しました。",
            }
        )
        return result
    finally:
        conn.close()


def sync_edgar_source(
    client,
    market="us",
    start_date=None,
    end_date=None,
    codes=None,
    limit=None,
    include_prices=True,
    include_financials=True,
    include_filings=True,
    include_dividends=True,
):
    conn = get_connection()
    try:
        result = sync_edgar_market(
            conn,
            edgar_client=client,
            tickers=codes,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
            include_prices=include_prices,
            include_financials=include_financials,
            include_filings=include_filings,
            include_dividends=include_dividends,
        )
        result.update({"market": market, "message": "SEC EDGARと株価APIから米国株データを同期しました。"})
        return result
    finally:
        conn.close()


def sync_edgar_bulk_source(
    start_date=None,
    end_date=None,
    exchanges=None,
    offset=0,
    limit=None,
    user_agent=None,
    include_prices=True,
    include_financials=True,
    include_filings=True,
    include_dividends=True,
    resume=True,
    record_state=True,
):
    params = {
        "market": "us",
        "source": "edgar",
        "mode": "bulk",
        "start_date": start_date,
        "end_date": end_date,
        "exchanges": exchanges,
        "offset": offset,
        "limit": limit,
        "include_prices": include_prices,
        "include_financials": include_financials,
        "include_filings": include_filings,
        "include_dividends": include_dividends,
        "resume": resume,
    }
    job_id = None
    lock_owner = None
    if record_state:
        state_conn = get_connection()
        try:
            lock_owner = acquire_sync_lock(state_conn, "sync:writer")
            job_id = begin_sync_job(state_conn, "bulk_sync", "us", "edgar", "bulk", params)
            upsert_sync_state(state_conn, "us", "edgar", "bulk", "running", params, message="米国株一括同期中")
        finally:
            state_conn.close()
    conn = None
    try:
        client = EdgarClient(user_agent=user_agent)
        if not client.is_configured():
            raise EdgarError("SEC_USER_AGENT is not configured.")
        conn = get_connection()
        with client:
            result = sync_edgar_bulk_market(
                conn,
                edgar_client=client,
                exchanges=exchanges,
                offset=offset,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
                include_prices=include_prices,
                include_financials=include_financials,
                include_filings=include_filings,
                include_dividends=include_dividends,
                resume=resume,
            )
        result.update({"message": "SEC EDGARのticker/CIK一覧から米国株をバッチ同期しました。"})
        if record_state:
            state_conn = get_connection()
            try:
                status = "warning" if result.get("warnings") or result.get("rate_limited") else "success"
                finish_sync_job(state_conn, job_id, status, result, result.get("message"))
                upsert_sync_state(state_conn, "us", "edgar", "bulk", status, params, result, result.get("message"))
            finally:
                state_conn.close()
        return result
    except Exception as exc:
        if record_state:
            state_conn = get_connection()
            try:
                result = {"error": str(exc)}
                finish_sync_job(state_conn, job_id, "failed", result, str(exc))
                upsert_sync_state(state_conn, "us", "edgar", "bulk", "failed", params, result, str(exc))
            finally:
                state_conn.close()
        raise
    finally:
        if conn:
            conn.close()
        if lock_owner:
            state_conn = get_connection()
            try:
                release_sync_lock(state_conn, "sync:writer", lock_owner)
            finally:
                state_conn.close()


def sync_jp_bulk_source(
    start_date=None,
    end_date=None,
    sections=None,
    offset=0,
    limit=None,
    include_prices=True,
    include_financials=True,
    include_dividends=True,
    include_events=True,
    resume=True,
    record_state=True,
):
    params = {
        "market": "jp",
        "source": "jquants",
        "mode": "bulk",
        "start_date": start_date,
        "end_date": end_date,
        "sections": sections,
        "offset": offset,
        "limit": limit,
        "include_prices": include_prices,
        "include_financials": include_financials,
        "include_dividends": include_dividends,
        "include_events": include_events,
        "resume": resume,
    }
    job_id = None
    lock_owner = None
    if record_state:
        state_conn = get_connection()
        try:
            lock_owner = acquire_sync_lock(state_conn, "sync:writer")
            job_id = begin_sync_job(state_conn, "bulk_sync", "jp", "jquants", "bulk", params)
            upsert_sync_state(state_conn, "jp", "jquants", "bulk", "running", params, message="日本株一括同期中")
        finally:
            state_conn.close()

    conn = None
    try:
        client = JQuantsClient()
        if not client.is_configured():
            raise JQuantsError("JQUANTS_API_KEY is not configured.")
        conn = get_connection()
        with client:
            result = sync_jp_bulk_market(
                conn,
                client=client,
                sections=sections,
                offset=offset,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
                include_prices=include_prices,
                include_financials=include_financials,
                include_dividends=include_dividends,
                include_events=include_events,
                resume=resume,
            )
        result.update({"message": "J-Quantsの銘柄一覧から日本株をバッチ同期しました。"})
        if record_state:
            state_conn = get_connection()
            try:
                status = "warning" if result.get("warnings") or result.get("rate_limited") else "success"
                finish_sync_job(state_conn, job_id, status, result, result.get("message"))
                upsert_sync_state(state_conn, "jp", "jquants", "bulk", status, params, result, result.get("message"))
            finally:
                state_conn.close()
        return result
    except Exception as exc:
        if record_state:
            state_conn = get_connection()
            try:
                result = {"error": str(exc)}
                finish_sync_job(state_conn, job_id, "failed", result, str(exc))
                upsert_sync_state(state_conn, "jp", "jquants", "bulk", "failed", params, result, str(exc))
            finally:
                state_conn.close()
        raise
    finally:
        if conn:
            conn.close()
        if lock_owner:
            state_conn = get_connection()
            try:
                release_sync_lock(state_conn, "sync:writer", lock_owner)
            finally:
                state_conn.close()


def sync_jp_screening_source(
    start_date=None,
    end_date=None,
    sections=None,
    include_prices=True,
    include_financials=True,
    include_dividends=False,
    record_state=True,
    progress_callback=None,
):
    params = {
        "market": "jp",
        "source": "jquants",
        "mode": "screening",
        "start_date": start_date,
        "end_date": end_date,
        "sections": sections,
        "include_prices": include_prices,
        "include_financials": include_financials,
        "include_dividends": include_dividends,
    }
    job_id = None
    lock_owner = None
    if record_state:
        state_conn = get_connection()
        try:
            lock_owner = acquire_sync_lock(state_conn, "sync:writer")
            job_id = begin_sync_job(state_conn, "screening_sync", "jp", "jquants", "screening", params)
            upsert_sync_state(state_conn, "jp", "jquants", "screening", "running", params, message="日本株スクリーニング同期中")
        finally:
            state_conn.close()

    conn = None
    latest_progress = {}
    try:
        client = JQuantsClient()
        if not client.is_configured():
            raise JQuantsError("JQUANTS_API_KEY is not configured.")
        start_date = start_date or default_price_start()
        conn = get_connection()
        with client:
            target_codes = None
            if sections and str(sections).lower() != "all":
                records, _ = filtered_jp_records(client.fetch_listed_info(date_value=end_date), sections=sections)
                target_codes = [record_code(record) for record in records if record_code(record)]
                inserted_companies = sync_jquants_companies(conn, client, listed_date=end_date, codes=target_codes)
            else:
                inserted_companies = sync_jquants_companies(conn, client, listed_date=end_date)

            def record_progress(payload):
                nonlocal latest_progress
                phase = payload.get("phase")
                phase_label = "株価" if phase == "prices" else "財務"
                latest_progress = {
                    "market": "jp",
                    "source": "jquants",
                    "mode": "screening",
                    "from": start_date,
                    "to": end_date,
                    "phase": phase,
                    "phase_label": phase_label,
                    "current_date": payload.get("current_date"),
                    "processed_dates": payload.get("processed_dates"),
                    "total_dates": payload.get("total_dates"),
                    "inserted": payload.get("inserted"),
                    "inserted_total": payload.get("inserted_total"),
                    "inserted_dividends": payload.get("inserted_dividends"),
                    "inserted_dividends_total": payload.get("inserted_dividends_total"),
                    "inserted_companies": inserted_companies,
                    "message": "日本株%sデータ取得中: %s/%s日 (%s)"
                    % (
                        phase_label,
                        payload.get("processed_dates"),
                        payload.get("total_dates"),
                        payload.get("current_date"),
                    ),
                }
                if record_state:
                    state_conn = get_connection()
                    try:
                        upsert_sync_state(
                            state_conn,
                            "jp",
                            "jquants",
                            "screening",
                            "running",
                            params,
                            latest_progress,
                            latest_progress["message"],
                        )
                    finally:
                        state_conn.close()
                if progress_callback:
                    progress_callback(latest_progress)

            inserted_prices = 0
            price_dates = []
            if include_prices:
                inserted_prices, price_dates = sync_jquants_prices_by_date_range(
                    conn,
                    client,
                    start_date=start_date,
                    end_date=end_date,
                    codes=target_codes,
                    progress_callback=record_progress,
                )

            inserted_financials = 0
            inserted_dividends = 0
            financial_dates = []
            if include_financials:
                inserted_financials, inserted_dividends, financial_dates = sync_jquants_financials_by_date_range(
                    conn,
                    client,
                    start_date=start_date,
                    end_date=end_date,
                    codes=target_codes,
                    include_dividends=include_dividends,
                    progress_callback=record_progress,
                )

        result = {
            "market": "jp",
            "source": "jquants",
            "mode": "screening",
            "from": start_date,
            "to": end_date,
            "target_codes": target_codes,
            "inserted_companies": inserted_companies,
            "inserted_prices": inserted_prices,
            "inserted_financials": inserted_financials,
            "inserted_dividends": inserted_dividends,
            "processed_price_dates": len(price_dates),
            "processed_financial_dates": len(financial_dates),
            "first_price_date": price_dates[0] if price_dates else None,
            "last_price_date": price_dates[-1] if price_dates else None,
            "first_financial_date": financial_dates[0] if financial_dates else None,
            "last_financial_date": financial_dates[-1] if financial_dates else None,
            "warnings": [],
            "message": "J-Quantsから日本株スクリーニング用データを日付単位で同期しました。",
        }
        if record_state:
            state_conn = get_connection()
            try:
                finish_sync_job(state_conn, job_id, "success", result, result.get("message"))
                upsert_sync_state(state_conn, "jp", "jquants", "screening", "success", params, result, result.get("message"))
            finally:
                state_conn.close()
        return result
    except Exception as exc:
        if record_state:
            state_conn = get_connection()
            try:
                result = {"error": str(exc), "last_progress": latest_progress}
                finish_sync_job(state_conn, job_id, "failed", result, str(exc))
                upsert_sync_state(state_conn, "jp", "jquants", "screening", "failed", params, result, str(exc))
            finally:
                state_conn.close()
        raise
    finally:
        if conn:
            conn.close()
        if lock_owner:
            state_conn = get_connection()
            try:
                release_sync_lock(state_conn, "sync:writer", lock_owner)
            finally:
                state_conn.close()


def sync_jquants_market(
    client,
    market="jp",
    start_date=None,
    end_date=None,
    codes=None,
    limit=None,
    include_prices=True,
    include_financials=True,
    include_dividends=True,
    include_events=True,
):
    settings = load_settings()
    target_codes = parse_code_list(codes)
    if not target_codes:
        target_codes = starter_codes(settings)
    if limit:
        target_codes = target_codes[: int(limit)]

    conn = get_connection()
    try:
        warnings = []
        company_limit = None if codes else limit
        try:
            inserted_companies = sync_jquants_companies(conn, client, codes=codes, limit=company_limit)
        except JQuantsError as exc:
            existing_targets = [code for code in target_codes if conn.execute(
                """
                SELECT 1 FROM company_master
                WHERE market = 'jp' AND (ticker = ? OR security_code = ?)
                LIMIT 1
                """,
                (code, code),
            ).fetchone()]
            if len(existing_targets) != len(target_codes):
                raise
            inserted_companies = 0
            warnings.append("companies: %s" % exc)
        clear_sample_events_and_filings(conn, target_codes)
        inserted_prices = 0
        inserted_financials = 0
        inserted_dividends = 0
        inserted_events = 0
        if include_prices:
            try:
                inserted_prices = sync_jquants_prices(
                    conn,
                    client,
                    target_codes,
                    start_date=start_date or default_price_start(),
                    end_date=end_date,
                )
            except JQuantsError as exc:
                warnings.append("prices: %s" % exc)
        if include_financials:
            try:
                inserted_financials = sync_jquants_financials(conn, client, target_codes)
            except JQuantsError as exc:
                warnings.append("financials: %s" % exc)
        if include_dividends:
            try:
                inserted_dividends = sync_jquants_dividends(conn, client, target_codes)
            except JQuantsError as exc:
                warnings.append("dividends: %s" % exc)
        if include_events:
            try:
                inserted_events += sync_jquants_statement_catalysts(conn, client, codes=target_codes)
                inserted_events += sync_jquants_earnings_events(conn, client, codes=target_codes)
            except JQuantsError as exc:
                warnings.append("events: %s" % exc)
        return {
            "market": market,
            "source": "jquants",
            "from": start_date,
            "to": end_date,
            "target_codes": target_codes,
            "inserted_companies": inserted_companies,
            "inserted_prices": inserted_prices,
            "inserted_financials": inserted_financials,
            "inserted_dividends": inserted_dividends,
            "inserted_events": inserted_events,
            "warnings": warnings,
            "message": "J-Quantsから日本株データを同期しました。",
        }
    finally:
        conn.close()
