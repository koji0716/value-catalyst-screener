import json
from datetime import date, timedelta


MARKET_SOURCES = {"jp": "jquants", "us": "edgar"}
MARKET_LABELS = {"jp": "日本株", "us": "米国株"}


def parse_json_dict(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def percent(numerator, denominator):
    if denominator in (None, 0):
        return None
    return round((float(numerator or 0) / float(denominator)) * 100, 1)


def average_percent(values):
    numbers = [value for value in values if value is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 1)


def scalar(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def company_count(conn, market):
    return scalar(conn, "SELECT COUNT(*) FROM company_master WHERE market = ?", (market,)) or 0


def distinct_company_count(conn, table, market, condition=None, params=()):
    where = "cm.market = ?"
    all_params = [market]
    if condition:
        where += " AND " + condition
        all_params.extend(params)
    return (
        scalar(
            conn,
            """
            SELECT COUNT(DISTINCT d.company_id)
            FROM %s d
            JOIN company_master cm ON cm.id = d.company_id
            WHERE %s
            """
            % (table, where),
            tuple(all_params),
        )
        or 0
    )


def max_date(conn, table, column, market):
    return scalar(
        conn,
        """
        SELECT MAX(d.%s)
        FROM %s d
        JOIN company_master cm ON cm.id = d.company_id
        WHERE cm.market = ?
        """
        % (column, table),
        (market,),
    )


def bulk_payloads(conn, market, source):
    rows = conn.execute(
        """
        SELECT params_json, result_json
        FROM sync_jobs
        WHERE market = ? AND source = ? AND mode = 'bulk'
        """,
        (market, source),
    ).fetchall()
    payloads = [(parse_json_dict(row["params_json"]), parse_json_dict(row["result_json"])) for row in rows]

    state = conn.execute(
        """
        SELECT target_codes_json AS params_json, result_json
        FROM sync_state
        WHERE market = ? AND source = ? AND mode = 'bulk'
        """,
        (market, source),
    ).fetchone()
    if state:
        payloads.append((parse_json_dict(state["params_json"]), parse_json_dict(state["result_json"])))
    return payloads


def is_detail_payload(params, result):
    detail_keys = ("include_prices", "include_financials", "include_filings", "include_dividends", "include_events")
    if any(params.get(key) for key in detail_keys):
        return True
    inserted_keys = ("inserted_prices", "inserted_financials", "inserted_filings", "inserted_dividends", "inserted_actions")
    return any((result.get(key) or 0) > 0 for key in inserted_keys)


def bulk_progress(conn, market):
    source = MARKET_SOURCES.get(market)
    if not source:
        return {"available_records": 0, "master_next_offset": 0, "detail_next_offset": 0}
    payloads = bulk_payloads(conn, market, source)
    available_records = 0
    master_next_offset = 0
    detail_next_offset = 0
    for params, result in payloads:
        available_records = max(available_records, int(result.get("available_records") or 0))
        if is_detail_payload(params, result):
            detail_next_offset = max(detail_next_offset, int(result.get("next_offset") or 0))
        else:
            master_next_offset = max(master_next_offset, int(result.get("next_offset") or 0))
    return {
        "available_records": available_records,
        "master_next_offset": master_next_offset,
        "detail_next_offset": detail_next_offset,
    }


def market_data_coverage(conn, market, as_of=None, price_fresh_days=10, financial_fresh_days=548):
    as_of = as_of or date.today()
    price_cutoff = (as_of - timedelta(days=price_fresh_days)).isoformat()
    financial_cutoff = (as_of - timedelta(days=financial_fresh_days)).isoformat()

    master_count = company_count(conn, market)
    progress = bulk_progress(conn, market)
    universe_records = max(progress["available_records"], master_count)

    price_companies = distinct_company_count(conn, "prices", market)
    financial_companies = distinct_company_count(conn, "financial_facts", market)
    filing_companies = distinct_company_count(conn, "filings", market)
    action_companies = distinct_company_count(conn, "corporate_actions", market)

    fresh_price_companies = distinct_company_count(conn, "prices", market, "d.trade_date >= ?", (price_cutoff,))
    fresh_financial_companies = distinct_company_count(
        conn,
        "financial_facts",
        market,
        "d.period_end >= ?",
        (financial_cutoff,),
    )

    price_coverage_pct = percent(price_companies, master_count)
    financial_coverage_pct = percent(financial_companies, master_count)
    filing_coverage_pct = percent(filing_companies, master_count)
    action_coverage_pct = percent(action_companies, master_count)
    price_freshness_pct = percent(fresh_price_companies, master_count)
    financial_freshness_pct = percent(fresh_financial_companies, master_count)

    return {
        "market": market,
        "market_label": MARKET_LABELS.get(market, market),
        "source": MARKET_SOURCES.get(market),
        "universe_records": universe_records,
        "company_count": master_count,
        "master_next_offset": min(progress["master_next_offset"], universe_records),
        "master_progress_pct": percent(min(progress["master_next_offset"], universe_records), universe_records),
        "master_coverage_pct": percent(master_count, universe_records),
        "detail_next_offset": min(progress["detail_next_offset"], universe_records),
        "detail_progress_pct": percent(min(progress["detail_next_offset"], universe_records), universe_records),
        "price_company_count": price_companies,
        "price_coverage_pct": price_coverage_pct,
        "financial_company_count": financial_companies,
        "financial_coverage_pct": financial_coverage_pct,
        "filing_company_count": filing_companies,
        "filing_coverage_pct": filing_coverage_pct,
        "action_company_count": action_companies,
        "action_coverage_pct": action_coverage_pct,
        "major_data_coverage_pct": average_percent(
            [price_coverage_pct, financial_coverage_pct, filing_coverage_pct]
        ),
        "fresh_price_company_count": fresh_price_companies,
        "price_freshness_pct": price_freshness_pct,
        "fresh_financial_company_count": fresh_financial_companies,
        "financial_freshness_pct": financial_freshness_pct,
        "major_freshness_pct": average_percent([price_freshness_pct, financial_freshness_pct]),
        "latest_price_date": max_date(conn, "prices", "trade_date", market),
        "latest_financial_period_end": max_date(conn, "financial_facts", "period_end", market),
        "latest_filing_date": max_date(conn, "filings", "filing_date", market),
        "price_fresh_days": price_fresh_days,
        "financial_fresh_days": financial_fresh_days,
    }


def data_coverage_rows(conn, markets=("jp", "us"), as_of=None, price_fresh_days=10, financial_fresh_days=548):
    return [
        market_data_coverage(
            conn,
            market,
            as_of=as_of,
            price_fresh_days=price_fresh_days,
            financial_fresh_days=financial_fresh_days,
        )
        for market in markets
    ]
