from datetime import date, timedelta

from src.providers.edgar_client import EdgarClient, EdgarError
from src.providers.price_client import PriceClient
from src.utils.file_utils import load_settings


STARTER_US_TICKERS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "GM"]

FACT_CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "total_equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "investing_cash_flow": ["NetCashProvidedByUsedInInvestingActivities"],
    "financing_cash_flow": ["NetCashProvidedByUsedInFinancingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "shares_outstanding": ["WeightedAverageNumberOfDilutedSharesOutstanding", "EntityCommonStockSharesOutstanding"],
}

DEBT_CONCEPTS = [
    "LongTermDebtAndFinanceLeaseObligationsCurrent",
    "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
    "LongTermDebtCurrent",
    "LongTermDebtNoncurrent",
    "ShortTermBorrowings",
]


def parse_ticker_list(tickers):
    if not tickers:
        return []
    if isinstance(tickers, str):
        parts = tickers.replace(" ", "").split(",")
    else:
        parts = tickers
    return [str(ticker).strip().upper() for ticker in parts if str(ticker).strip()]


def starter_us_tickers(settings=None):
    configured = ((settings or {}).get("providers") or {}).get("us_starter_tickers")
    return parse_ticker_list(configured) or STARTER_US_TICKERS


def to_float(value):
    if value in (None, "", "-", "－"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def date_text(value):
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)[:10]


def find_company(conn, ticker=None, cik=None):
    if ticker:
        row = conn.execute(
            """
            SELECT * FROM company_master
            WHERE market = 'us' AND UPPER(COALESCE(ticker, '')) = ?
            LIMIT 1
            """,
            (str(ticker).upper(),),
        ).fetchone()
        if row:
            return row
    if cik:
        return conn.execute(
            """
            SELECT * FROM company_master
            WHERE market = 'us' AND cik = ?
            LIMIT 1
            """,
            (str(cik),),
        ).fetchone()
    return None


def upsert_company(conn, ticker, record):
    cik = str(record.get("cik") or record.get("cik_str") or "").strip()
    company_name = record.get("name") or record.get("title") or ticker
    exchange = record.get("exchange")
    existing = find_company(conn, ticker=ticker, cik=cik)
    if existing:
        conn.execute(
            """
            UPDATE company_master
            SET ticker = ?, cik = COALESCE(?, cik), company_name = COALESCE(?, company_name),
                exchange = COALESCE(?, exchange), country = 'US', currency = 'USD',
                is_active = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (ticker, cik or None, company_name, exchange, existing["id"]),
        )
        return existing["id"]
    cur = conn.execute(
        """
        INSERT INTO company_master (
          market, ticker, cik, company_name, exchange, country, currency, is_active
        ) VALUES ('us', ?, ?, ?, ?, 'US', 'USD', 1)
        """,
        (ticker, cik or None, company_name, exchange),
    )
    return cur.lastrowid


def ticker_lookup(records):
    lookup = {}
    for record in records:
        ticker = str(record.get("ticker") or "").upper()
        if ticker:
            lookup[ticker] = record
    return lookup


def annual_fact_values(companyfacts, concepts):
    facts = ((companyfacts.get("facts") or {}).get("us-gaap") or {})
    values = {}
    for concept in concepts:
        unit_map = (facts.get(concept) or {}).get("units") or {}
        for records in unit_map.values():
            for record in records or []:
                form = str(record.get("form") or "")
                fiscal_period = str(record.get("fp") or "")
                fiscal_year = record.get("fy")
                if not fiscal_year or not record.get("end"):
                    continue
                if not (form.startswith("10-K") or fiscal_period == "FY"):
                    continue
                value = to_float(record.get("val"))
                if value is None:
                    continue
                key = int(fiscal_year)
                current = values.get(key)
                if current and str(current.get("filed") or "") >= str(record.get("filed") or ""):
                    continue
                values[key] = {"value": value, "period_end": record.get("end"), "filed": record.get("filed")}
    return values


def annual_fact_total(companyfacts, concepts):
    totals = {}
    for concept in concepts:
        values = annual_fact_values(companyfacts, [concept])
        for fiscal_year, item in values.items():
            current = totals.setdefault(
                fiscal_year,
                {"value": 0.0, "period_end": item.get("period_end"), "filed": item.get("filed")},
            )
            current["value"] += item["value"]
            if str(item.get("filed") or "") > str(current.get("filed") or ""):
                current["period_end"] = item.get("period_end")
                current["filed"] = item.get("filed")
    return totals


def map_companyfacts(companyfacts, years=6):
    mapped_by_year = {}
    metric_values = {metric: annual_fact_values(companyfacts, concepts) for metric, concepts in FACT_CONCEPTS.items()}
    debt_values = annual_fact_total(companyfacts, DEBT_CONCEPTS)
    fiscal_years = sorted(
        set().union(*[set(values.keys()) for values in metric_values.values()], set(debt_values.keys())),
        reverse=True,
    )[: int(years)]
    for fiscal_year in fiscal_years:
        row = {
            "fiscal_year": fiscal_year,
            "fiscal_quarter": "FY",
            "period_type": "annual",
            "period_end": None,
            "currency": "USD",
        }
        for metric, values in metric_values.items():
            item = values.get(fiscal_year)
            if item:
                row[metric] = item["value"]
                row["period_end"] = row["period_end"] or item.get("period_end")
        debt = debt_values.get(fiscal_year)
        row["interest_bearing_debt"] = debt["value"] if debt else None
        assets = row.get("total_assets")
        equity = row.get("total_equity")
        if row.get("total_liabilities") is None and assets is not None and equity is not None:
            row["total_liabilities"] = assets - equity
        capex = row.pop("capex", None)
        operating_cf = row.get("operating_cash_flow")
        investing_cf = row.get("investing_cash_flow")
        if operating_cf is not None and capex is not None:
            row["free_cash_flow"] = operating_cf - abs(capex)
        elif operating_cf is not None and investing_cf is not None:
            row["free_cash_flow"] = operating_cf + investing_cf
        else:
            row["free_cash_flow"] = None
        mapped_by_year[fiscal_year] = row
    return [mapped_by_year[year] for year in sorted(mapped_by_year.keys(), reverse=True)]


def upsert_financial(conn, company_id, record):
    if not record.get("period_end"):
        return False
    conn.execute(
        """
        DELETE FROM financial_facts
        WHERE company_id = ? AND source = 'edgar'
          AND COALESCE(fiscal_year, 0) = COALESCE(?, 0)
          AND COALESCE(period_end, '') = COALESCE(?, '')
        """,
        (company_id, record.get("fiscal_year"), record.get("period_end")),
    )
    conn.execute(
        """
        INSERT INTO financial_facts (
          company_id, source, fiscal_year, fiscal_quarter, period_type, period_end, currency,
          revenue, operating_income, net_income, ebitda, eps,
          total_assets, total_liabilities, total_equity, cash_and_equivalents,
          interest_bearing_debt, operating_cash_flow, investing_cash_flow,
          financing_cash_flow, free_cash_flow, shares_outstanding
        ) VALUES (?, 'edgar', ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company_id,
            record.get("fiscal_year"),
            record.get("fiscal_quarter"),
            record.get("period_type"),
            record.get("period_end"),
            record.get("currency"),
            record.get("revenue"),
            record.get("operating_income"),
            record.get("net_income"),
            record.get("eps"),
            record.get("total_assets"),
            record.get("total_liabilities"),
            record.get("total_equity"),
            record.get("cash_and_equivalents"),
            record.get("interest_bearing_debt"),
            record.get("operating_cash_flow"),
            record.get("investing_cash_flow"),
            record.get("financing_cash_flow"),
            record.get("free_cash_flow"),
            record.get("shares_outstanding"),
        ),
    )
    return True


def upsert_price(conn, company_id, record):
    trade_date = date_text(record.get("date"))
    close = to_float(record.get("close"))
    if not trade_date or close is None:
        return False
    conn.execute("DELETE FROM prices WHERE company_id = ? AND trade_date = ?", (company_id, trade_date))
    conn.execute(
        """
        INSERT INTO prices (
          company_id, trade_date, open, high, low, close, adjusted_close, volume, market_cap, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'yfinance')
        """,
        (
            company_id,
            trade_date,
            to_float(record.get("open")),
            to_float(record.get("high")),
            to_float(record.get("low")),
            close,
            to_float(record.get("adjusted_close")) or close,
            to_float(record.get("volume")),
        ),
    )
    return True


def upsert_filing(conn, company_id, record):
    document_id = record.get("accessionNumber")
    if not document_id:
        return False
    form = record.get("form")
    filing_date = record.get("filingDate")
    report_date = record.get("reportDate")
    primary_document = record.get("primaryDocument")
    url = None
    if primary_document:
        accession = str(document_id).replace("-", "")
        url = "https://www.sec.gov/Archives/edgar/data/%s/%s/%s" % (
            str(record.get("cik") or "").lstrip("0"),
            accession,
            primary_document,
        )
    conn.execute("DELETE FROM filings WHERE company_id = ? AND source = 'edgar' AND document_id = ?", (company_id, document_id))
    conn.execute(
        """
        INSERT INTO filings (
          company_id, source, document_id, document_type, filing_date, period_end,
          title, url, parsed_status
        ) VALUES (?, 'edgar', ?, ?, ?, ?, ?, ?, 'parsed')
        """,
        (company_id, document_id, form, filing_date, report_date, "%s filing" % form, url),
    )
    return True


def sync_edgar_market(
    conn,
    edgar_client=None,
    price_client=None,
    tickers=None,
    limit=None,
    start_date=None,
    end_date=None,
    include_prices=True,
    include_financials=True,
    include_filings=True,
    include_dividends=True,
):
    close_edgar = edgar_client is None
    edgar_client = edgar_client or EdgarClient()
    price_client = price_client or PriceClient()
    if not edgar_client.is_configured():
        raise EdgarError("SEC_USER_AGENT is not configured.")

    settings = load_settings()
    target_tickers = parse_ticker_list(tickers) or starter_us_tickers(settings)
    if limit:
        target_tickers = target_tickers[: int(limit)]

    result = {
        "market": "us",
        "source": "edgar",
        "target_codes": target_tickers,
        "updated_companies": 0,
        "inserted_financials": 0,
        "inserted_prices": 0,
        "inserted_filings": 0,
        "inserted_actions": 0,
        "warnings": [],
    }
    try:
        ticker_records = ticker_lookup(edgar_client.fetch_company_tickers())
        for ticker in target_tickers:
            record = ticker_records.get(ticker)
            if not record:
                result["warnings"].append("%s: SEC ticker record not found" % ticker)
                continue
            company_id = upsert_company(conn, ticker, record)
            result["updated_companies"] += 1
            cik = record.get("cik") or record.get("cik_str")

            if include_financials:
                try:
                    facts = edgar_client.fetch_companyfacts(cik)
                    for financial in map_companyfacts(facts):
                        if upsert_financial(conn, company_id, financial):
                            result["inserted_financials"] += 1
                except EdgarError as exc:
                    result["warnings"].append("%s financials: %s" % (ticker, exc))

            if include_filings:
                try:
                    submissions = edgar_client.fetch_submissions(cik)
                    recent = (submissions.get("filings") or {}).get("recent") or {}
                    forms = recent.get("form") or []
                    for idx, form in enumerate(forms[:40]):
                        if form not in ("10-K", "10-Q", "8-K", "10-K/A", "10-Q/A"):
                            continue
                        filing = {key: values[idx] if idx < len(values) else None for key, values in recent.items()}
                        filing["cik"] = cik
                        if upsert_filing(conn, company_id, filing):
                            result["inserted_filings"] += 1
                except EdgarError as exc:
                    result["warnings"].append("%s filings: %s" % (ticker, exc))

            if include_prices:
                prices = price_client.fetch_ohlc(
                    ticker,
                    start_date=start_date or (date.today() - timedelta(days=420)).isoformat(),
                    end_date=end_date,
                )
                for price in prices:
                    if upsert_price(conn, company_id, price):
                        result["inserted_prices"] += 1

            if include_dividends:
                for dividend in price_client.fetch_dividends(ticker):
                    conn.execute(
                        """
                        DELETE FROM corporate_actions
                        WHERE company_id = ? AND source = 'yfinance' AND action_type = 'dividend'
                          AND announced_date = ?
                        """,
                        (company_id, dividend.get("date")),
                    )
                    conn.execute(
                        """
                        INSERT INTO corporate_actions (
                          company_id, action_type, announced_date, effective_date, amount,
                          ratio, description, source
                        ) VALUES (?, 'dividend', ?, ?, ?, NULL, ?, 'yfinance')
                        """,
                        (
                            company_id,
                            dividend.get("date"),
                            dividend.get("date"),
                            dividend.get("amount"),
                            "Dividend %.4f USD" % dividend.get("amount"),
                        ),
                    )
                    result["inserted_actions"] += 1
            conn.commit()
        return result
    finally:
        if close_edgar:
            edgar_client.close()
