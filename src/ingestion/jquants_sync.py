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


def iso_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def iter_dates(start_date, end_date=None):
    current = iso_date(start_date)
    if current is None:
        return
    last = iso_date(end_date) or date.today()
    while current <= last:
        yield current.isoformat()
        current += timedelta(days=1)


def price_record_code(record):
    return normalize_issue_code(first_value(record, "Code", "LocalCode"))


def upsert_price_from_jquants(conn, company_id, record):
    trade_date = jquants_date(first_value(record, "Date"))
    if not trade_date:
        return False
    close = to_float(first_value(record, "Close", "C"))
    if close is None:
        return False
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
    return True


def sync_jquants_prices(conn, client, codes, start_date=None, end_date=None):
    count = 0
    for code in parse_code_list(codes):
        company_id = ensure_company_for_code(conn, code)
        records = client.fetch_prices(code, start_date=start_date, end_date=end_date)
        if records:
            delete_sample_rows(conn, company_id, ["prices"])
        for record in records:
            if upsert_price_from_jquants(conn, company_id, record):
                count += 1
    conn.commit()
    return count


def sync_jquants_prices_by_date(conn, client, date_value, codes=None):
    target_codes = set(parse_code_list(codes))
    count = 0
    records = client.fetch_prices(date_value=date_value)
    touched_companies = set()
    for record in records:
        code = price_record_code(record)
        if not code or (target_codes and code not in target_codes):
            continue
        company_id = ensure_company_for_code(conn, code)
        if company_id not in touched_companies:
            delete_sample_rows(conn, company_id, ["prices"])
            touched_companies.add(company_id)
        if upsert_price_from_jquants(conn, company_id, record):
            count += 1
    conn.commit()
    return count


def sync_jquants_prices_by_date_range(conn, client, start_date, end_date=None, codes=None, progress_callback=None):
    total = 0
    processed_dates = []
    date_values = list(iter_dates(start_date, end_date))
    for index, date_value in enumerate(date_values, start=1):
        inserted = sync_jquants_prices_by_date(conn, client, date_value, codes=codes)
        total += inserted
        processed_dates.append(date_value)
        if progress_callback:
            progress_callback(
                {
                    "phase": "prices",
                    "current_date": date_value,
                    "processed_dates": index,
                    "total_dates": len(date_values),
                    "inserted": inserted,
                    "inserted_total": total,
                }
            )
    return total, processed_dates


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


def sync_jquants_financials_by_date(conn, client, date_value, codes=None, include_dividends=False):
    target_codes = set(parse_code_list(codes))
    records = client.fetch_financial_statements(date_value=date_value)
    inserted_financials = 0
    inserted_dividends = 0
    touched_financials = set()
    touched_actions = set()
    for record in records:
        code = normalize_issue_code(first_value(record, "Code", "LocalCode"))
        if not code:
            continue
        if target_codes and code not in target_codes:
            continue
        company_id = ensure_company_for_code(conn, code)
        if company_id not in touched_financials:
            delete_sample_rows(conn, company_id, ["financial_facts"])
            touched_financials.add(company_id)
        if upsert_statement(conn, company_id, record):
            inserted_financials += 1
        if include_dividends:
            if company_id not in touched_actions:
                delete_sample_rows(conn, company_id, ["corporate_actions"])
                touched_actions.add(company_id)
            if upsert_dividend_from_summary(conn, company_id, record):
                inserted_dividends += 1
    conn.commit()
    return inserted_financials, inserted_dividends


def sync_jquants_financials_by_date_range(
    conn,
    client,
    start_date,
    end_date=None,
    codes=None,
    include_dividends=False,
    progress_callback=None,
):
    total_financials = 0
    total_dividends = 0
    processed_dates = []
    date_values = list(iter_dates(start_date, end_date))
    for index, date_value in enumerate(date_values, start=1):
        inserted_financials, inserted_dividends = sync_jquants_financials_by_date(
            conn,
            client,
            date_value,
            codes=codes,
            include_dividends=include_dividends,
        )
        total_financials += inserted_financials
        total_dividends += inserted_dividends
        processed_dates.append(date_value)
        if progress_callback:
            progress_callback(
                {
                    "phase": "financials",
                    "current_date": date_value,
                    "processed_dates": index,
                    "total_dates": len(date_values),
                    "inserted": inserted_financials,
                    "inserted_total": total_financials,
                    "inserted_dividends": inserted_dividends,
                    "inserted_dividends_total": total_dividends,
                }
            )
    return total_financials, total_dividends, processed_dates


def dividend_amount_from_summary(record):
    return to_float(
        first_value(
            record,
            "ForecastDividendPerShareAnnual",
            "ResultDividendPerShareAnnual",
            "NextYearForecastDividendPerShareAnnual",
            "DivAnn",
            "FDivAnn",
            "NxFDivAnn",
        )
    )


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


FORECAST_FIELDS = [
    (
        "operating_profit",
        [
            "ForecastOperatingProfit",
            "NextYearForecastOperatingProfit",
            "ForecastNonConsolidatedOperatingProfit",
            "NextYearForecastNonConsolidatedOperatingProfit",
            "FOP",
            "NFOP",
        ],
    ),
    (
        "profit",
        [
            "ForecastProfit",
            "NextYearForecastProfit",
            "ForecastNonConsolidatedProfit",
            "NextYearForecastNonConsolidatedProfit",
            "FProfit",
            "NFProfit",
            "FNP",
            "NFNP",
        ],
    ),
    (
        "eps",
        [
            "ForecastEarningsPerShare",
            "NextYearForecastEarningsPerShare",
            "ForecastNonConsolidatedEarningsPerShare",
            "NextYearForecastNonConsolidatedEarningsPerShare",
            "FEPS",
            "NFEPS",
        ],
    ),
]


def disclosure_date(record):
    return jquants_date(first_value(record, "DisclosedDate", "DiscDate", "Date")) or date.today().isoformat()


def disclosure_sort_key(record):
    return (
        disclosure_date(record),
        str(first_value(record, "DisclosedTime", "DiscTime", "Time") or ""),
        str(first_value(record, "DisclosureNumber", "DisclosureNo", "DocID") or ""),
    )


def forecast_values(record):
    values = {}
    for metric, keys in FORECAST_FIELDS:
        values[metric] = to_float(first_value(record, *keys))
    return values


def event_exists(conn, company_id, event_type, event_date, title):
    return conn.execute(
        """
        SELECT 1
        FROM events
        WHERE company_id = ? AND source = 'jquants' AND event_type = ?
          AND event_date = ? AND title = ?
        LIMIT 1
        """,
        (company_id, event_type, event_date, title),
    ).fetchone()


def insert_jquants_event(conn, company_id, event_type, event_date, title, description, sentiment_score, catalyst_score):
    if event_exists(conn, company_id, event_type, event_date, title):
        return False
    conn.execute(
        """
        INSERT INTO events (
          company_id, event_date, event_type, title, description, source,
          sentiment_score, catalyst_score
        ) VALUES (?, ?, ?, ?, ?, 'jquants', ?, ?)
        """,
        (company_id, event_date, event_type, title, description, sentiment_score, catalyst_score),
    )
    return True


def sync_jquants_statement_catalysts(conn, client, codes=None, revision_threshold=0.05):
    count = 0
    for code in parse_code_list(codes):
        company_id = ensure_company_for_code(conn, code)
        records = sorted(client.fetch_financial_statements(code=code), key=disclosure_sort_key)
        forecasts_by_period = {}
        dividends_by_period = {}
        previous_profit = None
        for record in records:
            event_date = disclosure_date(record)
            period_end = statement_period_end(record) or ""
            forecast_key = (period_end, statement_fiscal_quarter(record) or "")
            current_forecasts = forecast_values(record)
            previous_forecasts = forecasts_by_period.get(forecast_key, {})

            up_metrics = []
            down_metrics = []
            for metric, current_value in current_forecasts.items():
                previous_value = previous_forecasts.get(metric)
                if current_value is None or previous_value in (None, 0):
                    continue
                change = (current_value - previous_value) / abs(previous_value)
                if change >= revision_threshold:
                    up_metrics.append(metric)
                elif change <= -revision_threshold:
                    down_metrics.append(metric)

            if up_metrics:
                title = "業績予想の上方修正を検出"
                description = "J-Quants財務サマリーの予想値が前回開示比で改善しました: %s" % ", ".join(up_metrics)
                if insert_jquants_event(conn, company_id, "earnings_revision_up", event_date, title, description, 0.7, 25):
                    count += 1
            if down_metrics:
                title = "業績予想の下方修正を検出"
                description = "J-Quants財務サマリーの予想値が前回開示比で悪化しました: %s" % ", ".join(down_metrics)
                if insert_jquants_event(conn, company_id, "downward_revision", event_date, title, description, -0.7, 0):
                    count += 1

            if any(value is not None for value in current_forecasts.values()):
                forecasts_by_period[forecast_key] = {
                    **previous_forecasts,
                    **{metric: value for metric, value in current_forecasts.items() if value is not None},
                }

            dividend = dividend_amount_from_summary(record)
            previous_dividend = dividends_by_period.get(period_end)
            if dividend is not None and previous_dividend is not None and dividend > previous_dividend:
                title = "増配を検出"
                description = "J-Quants財務サマリーの年間配当が %.2f 円から %.2f 円へ増加しました。" % (
                    previous_dividend,
                    dividend,
                )
                if insert_jquants_event(conn, company_id, "dividend_increase", event_date, title, description, 0.6, 20):
                    count += 1
            if dividend is not None:
                dividends_by_period[period_end] = dividend

            profit = statement_net_income(record)
            if previous_profit is not None and previous_profit < 0 and profit is not None and profit > 0:
                title = "黒字転換を検出"
                description = "J-Quants財務サマリーの純利益が赤字から黒字に転換しました。"
                if insert_jquants_event(conn, company_id, "earnings_recovery", event_date, title, description, 0.6, 20):
                    count += 1
            if profit is not None:
                previous_profit = profit

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
