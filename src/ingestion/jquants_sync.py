from datetime import date, timedelta

from src.providers.jquants_client import (
    first_value,
    jquants_date,
    normalize_issue_code,
    to_float,
)


STARTER_UNIVERSE = ["7203", "9432", "8058", "6758", "7974", "7267", "6902", "1605"]


def parse_code_list(codes):
    if not codes:
        return []
    if isinstance(codes, str):
        parts = codes.replace(" ", "").split(",")
    else:
        parts = codes
    return [normalize_issue_code(code) for code in parts if str(code).strip()]


def starter_codes(settings=None):
    configured = ((settings or {}).get("providers") or {}).get("jquants_starter_codes")
    return parse_code_list(configured) or STARTER_UNIVERSE


def upsert_company_from_jquants(conn, record):
    raw_code = first_value(record, "Code", "LocalCode")
    code = normalize_issue_code(raw_code)
    if not code:
        return None
    company_name = first_value(record, "CompanyName", "CoName", "CompanyNameEnglish", "CoNameEn") or "JP %s" % code
    item = {
        "market": "jp",
        "ticker": code,
        "security_code": code,
        "edinet_code": None,
        "company_name": company_name,
        "exchange": first_value(record, "MarketCodeName", "MktNm", "Section", "ScaleCategory", "ScaleCat"),
        "sector": first_value(record, "Sector33CodeName", "S33Nm", "Sector17CodeName", "S17Nm"),
        "industry": first_value(record, "Sector17CodeName", "S17Nm", "Sector33CodeName", "S33Nm"),
        "country": "JP",
        "currency": "JPY",
        "is_active": 1,
    }
    existing = conn.execute(
        """
        SELECT id FROM company_master
        WHERE market = 'jp' AND (ticker = ? OR security_code = ?)
        LIMIT 1
        """,
        (code, code),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE company_master
            SET ticker = ?, security_code = ?, company_name = ?, exchange = ?,
                sector = ?, industry = ?, country = ?, currency = ?,
                is_active = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                item["ticker"],
                item["security_code"],
                item["company_name"],
                item["exchange"],
                item["sector"],
                item["industry"],
                item["country"],
                item["currency"],
                existing["id"],
            ),
        )
        return existing["id"]

    cur = conn.execute(
        """
        INSERT INTO company_master (
          market, ticker, security_code, edinet_code, company_name, exchange,
          sector, industry, country, currency, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            item["market"],
            item["ticker"],
            item["security_code"],
            item["edinet_code"],
            item["company_name"],
            item["exchange"],
            item["sector"],
            item["industry"],
            item["country"],
            item["currency"],
        ),
    )
    return cur.lastrowid


def sync_jquants_companies(conn, client, listed_date=None, codes=None, limit=None):
    parsed_codes = parse_code_list(codes)
    records = []
    if parsed_codes:
        for code in parsed_codes:
            records.extend(client.fetch_listed_info(date_value=listed_date, code=code))
    else:
        records = client.fetch_listed_info(date_value=listed_date)
    if limit:
        records = records[: int(limit)]

    count = 0
    for record in records:
        if upsert_company_from_jquants(conn, record):
            count += 1
    conn.commit()
    return count


def find_company_id(conn, code):
    normalized = normalize_issue_code(code)
    row = conn.execute(
        """
        SELECT id FROM company_master
        WHERE market = 'jp' AND (ticker = ? OR security_code = ?)
        LIMIT 1
        """,
        (normalized, normalized),
    ).fetchone()
    return row["id"] if row else None


def delete_sample_rows(conn, company_id, tables):
    for table in tables:
        conn.execute("DELETE FROM %s WHERE company_id = ? AND source = 'sample'" % table, (company_id,))


def ensure_company_for_code(conn, code):
    company_id = find_company_id(conn, code)
    if company_id:
        return company_id
    normalized = normalize_issue_code(code)
    cur = conn.execute(
        """
        INSERT INTO company_master (
          market, ticker, security_code, company_name, exchange, country, currency, is_active
        ) VALUES ('jp', ?, ?, ?, 'TSE', 'JP', 'JPY', 1)
        """,
        (normalized, normalized, "JP %s" % normalized),
    )
    return cur.lastrowid


def sync_jquants_prices(conn, client, codes, start_date=None, end_date=None):
    count = 0
    for code in parse_code_list(codes):
        company_id = ensure_company_for_code(conn, code)
        records = client.fetch_prices(code, start_date=start_date, end_date=end_date)
        if records:
            delete_sample_rows(conn, company_id, ["prices"])
        for record in records:
            trade_date = jquants_date(first_value(record, "Date"))
            if not trade_date:
                continue
            close = to_float(first_value(record, "Close", "C"))
            adjusted_close = to_float(first_value(record, "AdjustmentClose", "AdjC")) or close
            conn.execute("DELETE FROM prices WHERE company_id = ? AND trade_date = ?", (company_id, trade_date))
            conn.execute(
                """
                INSERT INTO prices (
                  company_id, trade_date, open, high, low, close, adjusted_close,
                  volume, market_cap, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'jquants')
                """,
                (
                    company_id,
                    trade_date,
                    to_float(first_value(record, "Open", "O")),
                    to_float(first_value(record, "High", "H")),
                    to_float(first_value(record, "Low", "L")),
                    close,
                    adjusted_close,
                    to_float(first_value(record, "AdjustmentVolume", "AdjVo", "Volume", "Vo")),
                ),
            )
            count += 1
    conn.commit()
    return count


def statement_period_type(record):
    current_period = str(first_value(record, "TypeOfCurrentPeriod", "CurPerType") or "").upper()
    document_type = str(first_value(record, "TypeOfDocument", "DocType") or "").upper()
    if current_period in ("FY", "ANNUAL") or "ANNUAL" in document_type:
        return "annual"
    if current_period:
        return "quarterly"
    return None


def statement_fiscal_quarter(record):
    current_period = str(first_value(record, "TypeOfCurrentPeriod", "CurPerType") or "")
    return current_period or None


def statement_period_end(record):
    return jquants_date(
        first_value(
            record,
            "CurrentPeriodEndDate",
            "CurrentFiscalYearEndDate",
            "CurPerEn",
            "CurFYEn",
            "DisclosedDate",
            "DiscDate",
        )
    )


def fiscal_year_from_period_end(period_end):
    if not period_end:
        return None
    try:
        return int(str(period_end)[:4])
    except ValueError:
        return None


def statement_revenue(record):
    return to_float(
        first_value(
            record,
            "NetSales",
            "Sales",
            "Revenue",
            "OperatingRevenue",
            "GrossOperatingRevenue",
        )
    )


def statement_operating_income(record):
    return to_float(first_value(record, "OperatingProfit", "OperatingIncome", "OP"))


def statement_net_income(record):
    return to_float(
        first_value(
            record,
            "Profit",
            "NP",
            "ProfitAttributableToOwnersOfParent",
            "ProfitLossAttributableToOwnersOfParent",
            "NetIncome",
        )
    )


def statement_shares(record, total_equity=None):
    shares = to_float(
        first_value(
            record,
            "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock",
            "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYear",
            "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStockResult",
            "ShOutFY",
            "AvgSh",
        )
    )
    if shares:
        return shares
    book_value_per_share = to_float(first_value(record, "BookValuePerShare", "BPS"))
    if total_equity and book_value_per_share:
        return total_equity / book_value_per_share
    return None


def upsert_statement(conn, company_id, record):
    period_end = statement_period_end(record)
    if not period_end:
        return False
    revenue = statement_revenue(record)
    operating_income = statement_operating_income(record)
    net_income = statement_net_income(record)
    total_assets = to_float(first_value(record, "TotalAssets", "TA"))
    total_equity = to_float(first_value(record, "Equity", "NetAssets", "Eq"))
    total_liabilities = total_assets - total_equity if total_assets is not None and total_equity is not None else None
    cash = to_float(first_value(record, "CashAndEquivalents", "CashAndCashEquivalents", "CashEq"))
    operating_cf = to_float(first_value(record, "CashFlowsFromOperatingActivities", "CFO"))
    investing_cf = to_float(first_value(record, "CashFlowsFromInvestingActivities", "CFI"))
    financing_cf = to_float(first_value(record, "CashFlowsFromFinancingActivities", "CFF"))
    free_cash_flow = operating_cf + investing_cf if operating_cf is not None and investing_cf is not None else None
    shares = statement_shares(record, total_equity=total_equity)
    fiscal_quarter = statement_fiscal_quarter(record)

    conn.execute(
        """
        DELETE FROM financial_facts
        WHERE company_id = ? AND source = 'jquants' AND period_end = ? AND COALESCE(fiscal_quarter, '') = ?
        """,
        (company_id, period_end, fiscal_quarter or ""),
    )
    conn.execute(
        """
        INSERT INTO financial_facts (
          company_id, source, fiscal_year, fiscal_quarter, period_type, period_end, currency,
          revenue, operating_income, net_income, ebitda, eps,
          total_assets, total_liabilities, total_equity, cash_and_equivalents,
          interest_bearing_debt, operating_cash_flow, investing_cash_flow,
          financing_cash_flow, free_cash_flow, shares_outstanding
        ) VALUES (?, 'jquants', ?, ?, ?, ?, 'JPY', ?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
        """,
        (
            company_id,
            fiscal_year_from_period_end(period_end),
            fiscal_quarter,
            statement_period_type(record),
            period_end,
            revenue,
            operating_income,
            net_income,
            to_float(first_value(record, "EarningsPerShare", "BasicEarningsPerShare", "EPS")),
            total_assets,
            total_liabilities,
            total_equity,
            cash,
            operating_cf,
            investing_cf,
            financing_cf,
            free_cash_flow,
            shares,
        ),
    )
    return True


def sync_jquants_financials(conn, client, codes):
    count = 0
    for code in parse_code_list(codes):
        company_id = ensure_company_for_code(conn, code)
        records = client.fetch_financial_statements(code=code)
        if records:
            delete_sample_rows(conn, company_id, ["financial_facts"])
        for record in records:
            if upsert_statement(conn, company_id, record):
                count += 1
    conn.commit()
    return count


def dividend_amount_from_summary(record):
    return to_float(first_value(record, "DivAnn", "FDivAnn", "NxFDivAnn"))


def upsert_dividend_from_summary(conn, company_id, record):
    amount = dividend_amount_from_summary(record)
    if amount is None:
        return False
    announced_date = jquants_date(first_value(record, "DiscDate", "Date")) or statement_period_end(record)
    effective_date = statement_period_end(record)
    description = "年間配当 %.2f 円" % amount
    conn.execute(
        """
        DELETE FROM corporate_actions
        WHERE company_id = ?
          AND source = 'jquants'
          AND action_type = 'dividend'
          AND COALESCE(announced_date, '') = COALESCE(?, '')
          AND COALESCE(effective_date, '') = COALESCE(?, '')
        """,
        (company_id, announced_date, effective_date),
    )
    conn.execute(
        """
        INSERT INTO corporate_actions (
          company_id, action_type, announced_date, effective_date, amount,
          ratio, description, source
        ) VALUES (?, 'dividend', ?, ?, ?, NULL, ?, 'jquants')
        """,
        (company_id, announced_date, effective_date, amount, description),
    )
    return True


def sync_jquants_dividends(conn, client, codes):
    count = 0
    for code in parse_code_list(codes):
        company_id = ensure_company_for_code(conn, code)
        records = client.fetch_financial_statements(code=code)
        if records:
            delete_sample_rows(conn, company_id, ["corporate_actions"])
        for record in records:
            if upsert_dividend_from_summary(conn, company_id, record):
                count += 1
    conn.commit()
    return count


def sync_jquants_earnings_events(conn, client, codes=None):
    target_codes = set(parse_code_list(codes))
    records = client.fetch_earnings_calendar()
    count = 0
    for record in records:
        code = normalize_issue_code(first_value(record, "Code", "LocalCode"))
        if not code:
            continue
        if target_codes and code not in target_codes:
            continue
        company_id = ensure_company_for_code(conn, code)
        event_date = jquants_date(first_value(record, "Date")) or date.today().isoformat()
        title = "%s 決算発表予定" % (first_value(record, "FiscalQuarter") or "")
        conn.execute(
            """
            DELETE FROM events
            WHERE company_id = ? AND source = 'jquants' AND event_type = 'earnings_date_soon' AND event_date = ?
            """,
            (company_id, event_date),
        )
        conn.execute(
            """
            INSERT INTO events (
              company_id, event_date, event_type, title, description, source,
              sentiment_score, catalyst_score
            ) VALUES (?, ?, 'earnings_date_soon', ?, ?, 'jquants', 0, 10)
            """,
            (
                company_id,
                event_date,
                title.strip(),
                "%s のJ-Quants決算発表予定です。" % (first_value(record, "CompanyName") or code),
            ),
        )
        count += 1
    conn.commit()
    return count


def default_price_start(days=420):
    return (date.today() - timedelta(days=days)).isoformat()


def clear_sample_events_and_filings(conn, codes):
    for code in parse_code_list(codes):
        company_id = find_company_id(conn, code)
        if company_id:
            delete_sample_rows(conn, company_id, ["events", "filings"])
    conn.commit()
