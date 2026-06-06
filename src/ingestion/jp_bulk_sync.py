from src.ingestion.jquants_sync import (
    default_price_start,
    parse_code_list,
    sync_jquants_dividends,
    sync_jquants_earnings_events,
    sync_jquants_financials,
    sync_jquants_prices,
    sync_jquants_statement_catalysts,
    upsert_company_from_jquants,
)
from src.providers.jquants_client import JQuantsClient, JQuantsError, first_value, normalize_issue_code


SECTION_ALIASES = {
    "prime": ["prime", "プライム"],
    "standard": ["standard", "スタンダード"],
    "growth": ["growth", "グロース"],
    "tokyo pro": ["tokyo pro", "tokyo pro market"],
}


def parse_section_list(sections):
    if not sections or str(sections).lower() == "all":
        return []
    if isinstance(sections, str):
        parts = sections.split(",")
    else:
        parts = sections
    return [str(section).strip().lower() for section in parts if str(section).strip()]


def section_filter_terms(sections):
    terms = []
    for section in parse_section_list(sections):
        terms.extend(SECTION_ALIASES.get(section, [section]))
    return terms


def record_code(record):
    return normalize_issue_code(first_value(record, "Code", "LocalCode"))


def record_section(record):
    return str(
        first_value(record, "MarketCodeName", "MktNm", "Section", "ScaleCategory", "ScaleCat") or ""
    ).strip()


def filtered_jp_records(records, sections=None, offset=0, limit=None):
    section_filters = section_filter_terms(sections)
    filtered = []
    for record in records:
        code = record_code(record)
        if not code:
            continue
        if section_filters:
            section = record_section(record).lower()
            if not any(part in section for part in section_filters):
                continue
        filtered.append(record)
    start = max(int(offset or 0), 0)
    end = None if limit in (None, "") else start + max(int(limit), 0)
    return filtered[start:end], len(filtered)


def find_jp_company(conn, code):
    normalized = normalize_issue_code(code)
    return conn.execute(
        """
        SELECT *
        FROM company_master
        WHERE market = 'jp' AND (ticker = ? OR security_code = ?)
        LIMIT 1
        """,
        (normalized, normalized),
    ).fetchone()


def company_has_requested_jp_data(
    conn,
    company_id,
    include_prices=True,
    include_financials=True,
    include_dividends=True,
    include_events=True,
):
    checks = []
    if include_prices:
        checks.append(("prices", "source IN ('jquants', 'yfinance')"))
    if include_financials:
        checks.append(("financial_facts", "source IN ('jquants', 'edinetdb')"))
    if include_dividends:
        checks.append(("corporate_actions", "source IN ('jquants', 'yfinance') AND action_type = 'dividend'"))
    if include_events:
        checks.append(("events", "source IN ('jquants', 'edinetdb')"))
    if not checks:
        return True
    for table, condition in checks:
        row = conn.execute(
            "SELECT 1 FROM %s WHERE company_id = ? AND %s LIMIT 1" % (table, condition),
            (company_id,),
        ).fetchone()
        if not row:
            return False
    return True


def is_rate_limit_error(exc):
    text = str(exc).lower()
    return "429" in text or "rate limit" in text


def sync_jp_bulk_market(
    conn,
    client=None,
    sections=None,
    offset=0,
    limit=None,
    start_date=None,
    end_date=None,
    include_prices=True,
    include_financials=True,
    include_dividends=True,
    include_events=True,
    resume=True,
):
    close_client = client is None
    client = client or JQuantsClient()
    if not client.is_configured():
        raise JQuantsError("JQUANTS_API_KEY is not configured.")

    result = {
        "market": "jp",
        "source": "jquants",
        "mode": "bulk",
        "offset": int(offset or 0),
        "limit": limit,
        "sections": parse_section_list(sections) or ["all"],
        "available_records": 0,
        "selected_records": 0,
        "processed_codes": [],
        "skipped_existing": 0,
        "inserted_companies": 0,
        "updated_companies": 0,
        "inserted_prices": 0,
        "inserted_financials": 0,
        "inserted_dividends": 0,
        "inserted_events": 0,
        "rate_limited": False,
        "warnings": [],
    }
    try:
        records, available = filtered_jp_records(
            client.fetch_listed_info(),
            sections=sections,
            offset=offset,
            limit=limit,
        )
        result["available_records"] = available
        result["selected_records"] = len(records)
        result["next_offset"] = int(offset or 0)
        statement_event_codes = []

        for idx, record in enumerate(records):
            current_offset = int(offset or 0) + idx
            code = record_code(record)
            existing = find_jp_company(conn, code)
            if resume and existing and company_has_requested_jp_data(
                conn,
                existing["id"],
                include_prices=include_prices,
                include_financials=include_financials,
                include_dividends=include_dividends,
                include_events=include_events,
            ):
                result["skipped_existing"] += 1
                result["next_offset"] = current_offset + 1
                continue

            company_id = upsert_company_from_jquants(conn, record)
            conn.commit()
            if existing:
                result["updated_companies"] += 1
            else:
                result["inserted_companies"] += 1
            result["processed_codes"].append(code)

            try:
                if include_prices:
                    result["inserted_prices"] += sync_jquants_prices(
                        conn,
                        client,
                        [code],
                        start_date=start_date or default_price_start(),
                        end_date=end_date,
                    )
                if include_financials:
                    result["inserted_financials"] += sync_jquants_financials(conn, client, [code])
                if include_dividends:
                    result["inserted_dividends"] += sync_jquants_dividends(conn, client, [code])
                if include_events:
                    result["inserted_events"] += sync_jquants_statement_catalysts(conn, client, codes=[code])
                    statement_event_codes.append(code)
                result["next_offset"] = current_offset + 1
            except JQuantsError as exc:
                result["warnings"].append("%s: %s" % (code, exc))
                if is_rate_limit_error(exc):
                    result["rate_limited"] = True
                    result["next_offset"] = current_offset
                    break

        if include_events and statement_event_codes and not result["rate_limited"]:
            try:
                result["inserted_events"] += sync_jquants_earnings_events(
                    conn,
                    client,
                    codes=statement_event_codes,
                )
            except JQuantsError as exc:
                result["warnings"].append("earnings_calendar: %s" % exc)
                if is_rate_limit_error(exc):
                    result["rate_limited"] = True
        return result
    finally:
        if close_client:
            client.close()
