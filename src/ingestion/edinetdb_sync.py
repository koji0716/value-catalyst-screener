import json
import hashlib
from datetime import date, timedelta

from src.providers.edinet_client import EdinetDbClient, EdinetError


RISK_KEYWORDS = [
    ("going_concern", ["継続企業", "重要な疑義", "going concern"]),
    ("negative_equity", ["債務超過", "negative equity"]),
    ("delisting_risk", ["上場廃止", "監理銘柄", "整理銘柄"]),
    ("impairment", ["減損損失", "impairment"]),
    ("litigation", ["訴訟", "係争", "litigation"]),
    ("financing_risk", ["資金繰り", "借換", "財務制限条項"]),
]


def first_value(record, *keys):
    for key in keys:
        if isinstance(record, dict) and record.get(key) not in (None, "", "-", "－"):
            return record.get(key)
    return None


def to_float(value):
    if value in (None, "", "-", "－"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def to_int(value):
    number = to_float(value)
    return int(number) if number is not None else None


def parse_codes(codes):
    if not codes:
        return []
    if isinstance(codes, str):
        return [part.strip().upper() for part in codes.replace(" ", "").split(",") if part.strip()]
    return [str(code).strip().upper() for code in codes if str(code).strip()]


def find_company(conn, code):
    value = str(code).strip().upper()
    return conn.execute(
        """
        SELECT *
        FROM company_master
        WHERE UPPER(COALESCE(ticker, '')) = ?
           OR security_code = ?
           OR UPPER(COALESCE(edinet_code, '')) = ?
        LIMIT 1
        """,
        (value, value, value),
    ).fetchone()


def known_company_codes(conn, limit=None):
    query = """
        SELECT COALESCE(edinet_code, security_code, ticker) AS code
        FROM company_master
        WHERE market = 'jp'
        ORDER BY security_code, ticker
    """
    params = []
    if limit:
        query += " LIMIT ?"
        params.append(int(limit))
    return [row["code"] for row in conn.execute(query, params).fetchall() if row["code"]]


def resolve_edinet_code(conn, client, code):
    value = str(code).strip().upper()
    if value.startswith("E") and len(value) >= 5:
        return value

    company = find_company(conn, value)
    if company and company["edinet_code"]:
        return company["edinet_code"]

    search_term = value
    if company:
        search_term = company["security_code"] or company["ticker"] or company["company_name"]
    results = client.search_companies(search_term, limit=10)
    edinet_code = choose_edinet_code(results, value, company)
    if edinet_code and company:
        conn.execute(
            "UPDATE company_master SET edinet_code = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (edinet_code, company["id"]),
        )
        conn.commit()
    return edinet_code


def choose_edinet_code(results, requested_code, company=None):
    for item in results:
        edinet_code = first_value(item, "edinet_code", "edinetCode", "code")
        security_code = str(first_value(item, "security_code", "securityCode", "ticker", "local_code") or "")
        if security_code.startswith(requested_code) or requested_code.startswith(security_code):
            return edinet_code
    if company:
        company_name = company["company_name"]
        for item in results:
            name = first_value(item, "company_name", "name", "canonical_name", "name_ja")
            if name and company_name and (company_name in name or name in company_name):
                return first_value(item, "edinet_code", "edinetCode", "code")
    if results:
        return first_value(results[0], "edinet_code", "edinetCode", "code")
    return None


def upsert_company_profile(conn, edinet_code, profile):
    security_code = first_value(profile, "security_code", "securityCode", "ticker", "local_code")
    company_name = first_value(profile, "company_name", "name", "canonical_name", "name_ja", "companyName")
    industry = first_value(profile, "industry", "industry_name", "industryName", "sector")
    company = find_company(conn, edinet_code) or (find_company(conn, security_code) if security_code else None)

    if company:
        company_id = company["id"]
        conn.execute(
            """
            UPDATE company_master
            SET edinet_code = ?, company_name = COALESCE(?, company_name),
                security_code = COALESCE(?, security_code),
                ticker = COALESCE(ticker, ?),
                industry = COALESCE(?, industry),
                country = COALESCE(country, 'JP'),
                currency = COALESCE(currency, 'JPY'),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (edinet_code, company_name, security_code, security_code, industry, company_id),
        )
        return company_id

    cur = conn.execute(
        """
        INSERT INTO company_master (
          market, ticker, security_code, edinet_code, company_name, industry, country, currency, is_active
        ) VALUES ('jp', ?, ?, ?, ?, ?, 'JP', 'JPY', 1)
        """,
        (security_code, security_code, edinet_code, company_name or edinet_code, industry),
    )
    return cur.lastrowid


def map_financial(record):
    total_assets = to_float(first_value(record, "total_assets", "totalAssets"))
    total_equity = to_float(first_value(record, "net_assets", "netAssets", "equity", "total_equity", "totalEquity"))
    total_liabilities = to_float(first_value(record, "total_liabilities", "totalLiabilities"))
    if total_liabilities is None and total_assets is not None and total_equity is not None:
        total_liabilities = total_assets - total_equity
    operating_cf = to_float(first_value(record, "cf_operating", "operating_cash_flow", "cashFlowsFromOperatingActivities"))
    investing_cf = to_float(first_value(record, "cf_investing", "investing_cash_flow", "cashFlowsFromInvestingActivities"))
    free_cash_flow = to_float(first_value(record, "free_cash_flow", "freeCashFlow"))
    if free_cash_flow is None and operating_cf is not None and investing_cf is not None:
        free_cash_flow = operating_cf + investing_cf

    return {
        "fiscal_year": to_int(first_value(record, "fiscal_year", "fiscalYear", "year")),
        "fiscal_quarter": first_value(record, "fiscal_quarter", "fiscalQuarter"),
        "period_type": first_value(record, "period", "period_type", "periodType") or "annual",
        "period_end": first_value(record, "period_end", "periodEnd", "fiscal_year_end", "fiscalYearEnd"),
        "currency": first_value(record, "currency") or "JPY",
        "revenue": to_float(first_value(record, "revenue", "net_sales", "netSales")),
        "operating_income": to_float(first_value(record, "operating_income", "operatingIncome")),
        "net_income": to_float(first_value(record, "net_income", "netIncome", "profit")),
        "ebitda": to_float(first_value(record, "ebitda")),
        "eps": to_float(first_value(record, "eps", "adjusted_eps", "adjustedEps")),
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "cash_and_equivalents": to_float(first_value(record, "cash", "cash_and_equivalents", "cashAndEquivalents")),
        "interest_bearing_debt": to_float(first_value(record, "interest_bearing_debt", "interestBearingDebt", "ibd")),
        "operating_cash_flow": operating_cf,
        "investing_cash_flow": investing_cf,
        "financing_cash_flow": to_float(first_value(record, "cf_financing", "financing_cash_flow", "cashFlowsFromFinancingActivities")),
        "free_cash_flow": free_cash_flow,
        "shares_outstanding": to_float(first_value(record, "shares_outstanding", "sharesOutstanding", "number_of_shares")),
    }


def upsert_financial(conn, company_id, record):
    mapped = map_financial(record)
    if not (mapped["period_end"] or mapped["fiscal_year"]):
        return False
    conn.execute(
        """
        DELETE FROM financial_facts
        WHERE company_id = ? AND source = 'edinetdb'
          AND COALESCE(period_end, '') = COALESCE(?, '')
          AND COALESCE(fiscal_year, 0) = COALESCE(?, 0)
          AND COALESCE(fiscal_quarter, '') = COALESCE(?, '')
        """,
        (company_id, mapped["period_end"], mapped["fiscal_year"], mapped["fiscal_quarter"] or ""),
    )
    conn.execute(
        """
        INSERT INTO financial_facts (
          company_id, source, fiscal_year, fiscal_quarter, period_type, period_end, currency,
          revenue, operating_income, net_income, ebitda, eps,
          total_assets, total_liabilities, total_equity, cash_and_equivalents,
          interest_bearing_debt, operating_cash_flow, investing_cash_flow,
          financing_cash_flow, free_cash_flow, shares_outstanding
        ) VALUES (?, 'edinetdb', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company_id,
            mapped["fiscal_year"],
            mapped["fiscal_quarter"],
            mapped["period_type"],
            mapped["period_end"],
            mapped["currency"],
            mapped["revenue"],
            mapped["operating_income"],
            mapped["net_income"],
            mapped["ebitda"],
            mapped["eps"],
            mapped["total_assets"],
            mapped["total_liabilities"],
            mapped["total_equity"],
            mapped["cash_and_equivalents"],
            mapped["interest_bearing_debt"],
            mapped["operating_cash_flow"],
            mapped["investing_cash_flow"],
            mapped["financing_cash_flow"],
            mapped["free_cash_flow"],
            mapped["shares_outstanding"],
        ),
    )
    return True


def upsert_disclosure(conn, company_id, record):
    document_id = first_value(record, "document_id", "documentId", "doc_id", "docID", "source_doc_id")
    filing_date = first_value(record, "filing_date", "filingDate", "submit_date", "submitDate", "date", "disclosure_date")
    fiscal_year = first_value(record, "fiscal_year", "fiscalYear")
    period_end = first_value(record, "period_end", "periodEnd", "fiscal_year_end")
    if period_end is None and fiscal_year:
        period_end = "%s-03-31" % fiscal_year
    title = first_value(record, "title", "document_title", "documentTitle", "type")
    doc_type = first_value(record, "document_type", "documentType", "type")
    url = first_value(record, "url", "source_url", "sourceUrl", "pdf_url")
    if not document_id:
        digest = hashlib.sha1((title or "").encode("utf-8")).hexdigest()[:12]
        document_id = "EDINETDB-%s-%s-%s-%s" % (
            doc_type or "disclosure",
            fiscal_year or "",
            filing_date or "",
            digest,
        )
    conn.execute(
        """
        DELETE FROM filings
        WHERE company_id = ? AND source = 'edinetdb' AND document_id = ?
        """,
        (company_id, document_id),
    )
    conn.execute(
        """
        INSERT INTO filings (
          company_id, source, document_id, document_type, filing_date, period_end,
          title, url, parsed_status
        ) VALUES (?, 'edinetdb', ?, ?, ?, ?, ?, ?, 'parsed')
        """,
        (company_id, document_id, doc_type, filing_date, period_end, title, url),
    )
    return True


def detect_risk_flags(text):
    if not text:
        return []
    lowered = text.lower()
    flags = []
    for flag, words in RISK_KEYWORDS:
        if any(word.lower() in lowered for word in words):
            flags.append(flag)
    return flags


def upsert_text_block(conn, company_id, block):
    text = first_value(block, "text", "content", "body", "excerpt") or ""
    if not text:
        return False, []
    fiscal_year = to_int(first_value(block, "fiscal_year", "fiscalYear", "year"))
    section = first_value(block, "element_type", "section", "type")
    title = first_value(block, "title", "heading", "label")
    flags = detect_risk_flags(text)
    conn.execute(
        """
        INSERT INTO filing_text_blocks (
          company_id, source, fiscal_year, section, title, text_excerpt, risk_flags_json
        ) VALUES (?, 'edinetdb', ?, ?, ?, ?, ?)
        """,
        (company_id, fiscal_year, section, title, text[:2000], json.dumps(flags, ensure_ascii=False)),
    )
    return True, flags


def insert_risk_events(conn, company_id, flags):
    inserted = 0
    for flag in sorted(set(flags)):
        event_type = "going_concern" if flag == "going_concern" else "edinet_risk_note"
        conn.execute(
            """
            DELETE FROM events
            WHERE company_id = ? AND source = 'edinetdb' AND event_type = ? AND title = ?
            """,
            (company_id, event_type, flag),
        )
        conn.execute(
            """
            INSERT INTO events (
              company_id, event_date, event_type, title, description, source,
              sentiment_score, catalyst_score
            ) VALUES (?, ?, ?, ?, ?, 'edinetdb', -0.5, 0)
            """,
            (
                company_id,
                date.today().isoformat(),
                event_type,
                flag,
                "EDINET DBの有報テキストからリスク語を検出しました。",
            ),
        )
        inserted += 1
    return inserted


def sync_edinetdb_market(
    conn,
    client=None,
    codes=None,
    limit=None,
    years=6,
    include_financials=True,
    include_disclosures=True,
    include_text=True,
):
    close_client = client is None
    client = client or EdinetDbClient()
    if not client.is_configured():
        raise EdinetError("EDINETDB_API_KEY or EDINETDB_AUTH is not configured.")

    target_codes = parse_codes(codes) or known_company_codes(conn, limit=limit)
    if limit and codes:
        target_codes = target_codes[: int(limit)]

    result = {
        "source": "edinetdb",
        "target_codes": target_codes,
        "updated_companies": 0,
        "inserted_financials": 0,
        "inserted_filings": 0,
        "inserted_text_blocks": 0,
        "inserted_risk_events": 0,
        "warnings": [],
    }
    try:
        for code in target_codes:
            try:
                edinet_code = resolve_edinet_code(conn, client, code)
                if not edinet_code:
                    result["warnings"].append("%s: EDINETコードを解決できませんでした" % code)
                    continue
                profile = client.get_company(edinet_code, fields=["profile"])
                company_id = upsert_company_profile(conn, edinet_code, profile)
                result["updated_companies"] += 1

                if include_financials:
                    records = client.get_financials(edinet_code, years=years)
                    for record in records:
                        if upsert_financial(conn, company_id, record):
                            result["inserted_financials"] += 1

                if include_disclosures:
                    since = (date.today() - timedelta(days=365 * 2)).isoformat()
                    for record in client.get_disclosures(edinet_code, since=since):
                        if upsert_disclosure(conn, company_id, record):
                            result["inserted_filings"] += 1

                if include_text:
                    flags = []
                    conn.execute("DELETE FROM filing_text_blocks WHERE company_id = ? AND source = 'edinetdb'", (company_id,))
                    for block in client.get_text_blocks(edinet_code):
                        inserted, block_flags = upsert_text_block(conn, company_id, block)
                        if inserted:
                            result["inserted_text_blocks"] += 1
                            flags.extend(block_flags)
                    result["inserted_risk_events"] += insert_risk_events(conn, company_id, flags)
                conn.commit()
            except EdinetError as exc:
                result["warnings"].append("%s: %s" % (code, exc))
        return result
    finally:
        if close_client:
            client.close()
