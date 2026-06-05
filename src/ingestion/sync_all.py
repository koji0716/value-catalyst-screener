from src.db.session import get_connection
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
    sync_jquants_prices,
)
from src.ingestion.sample_data import seed_sample_data
from src.ingestion.sync_state import begin_sync_job, finish_sync_job, upsert_sync_state
from src.providers.jquants_client import JQuantsClient, JQuantsError
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
    if record_state:
        conn = get_connection()
        try:
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
    if market not in ("jp", "all"):
        return {
            "market": market,
            "source": source,
            "mode": mode,
            "inserted_companies": 0,
            "message": "現時点では日本株同期を優先実装しています。",
        }

    if source not in ("auto", "sample", "jquants", "edinetdb"):
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
        inserted = seed_sample_data(conn, reset=reset_sample)
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
            "message": "サンプル日本株データを同期しました。",
        }
    finally:
        conn.close()


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
                inserted_events = sync_jquants_earnings_events(conn, client, codes=target_codes)
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
