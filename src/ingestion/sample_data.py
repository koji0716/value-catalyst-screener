import math
from datetime import date, timedelta


SAMPLE_COMPANIES = [
    {
        "market": "jp",
        "ticker": "7203",
        "security_code": "7203",
        "edinet_code": "E02144",
        "company_name": "トヨタ自動車",
        "exchange": "TSE Prime",
        "sector": "輸送用機器",
        "industry": "自動車",
        "country": "JP",
        "currency": "JPY",
        "price": 2600,
        "market_cap": 41_500_000_000_000,
        "revenue": 48_000_000_000_000,
        "operating_income": 4_800_000_000_000,
        "net_income": 4_760_000_000_000,
        "ebitda": 7_050_000_000_000,
        "equity": 35_900_000_000_000,
        "assets": 93_600_000_000_000,
        "debt": 38_700_000_000_000,
        "cash": 8_980_000_000_000,
        "ocf": 3_700_000_000_000,
        "fcf": -490_000_000_000,
        "eps": 359.56,
        "trend": 0.06,
        "volume": 24_000_000,
        "events": [
            ("dividend_increase", "増配発表", 35, 0.8),
            ("share_buyback", "自己株買い枠の発表", 95, 0.7),
        ],
    },
    {
        "market": "jp",
        "ticker": "7267",
        "security_code": "7267",
        "edinet_code": "E02166",
        "company_name": "本田技研工業",
        "exchange": "TSE Prime",
        "sector": "輸送用機器",
        "industry": "自動車",
        "country": "JP",
        "currency": "JPY",
        "price": 1650,
        "market_cap": 8_600_000_000_000,
        "revenue": 21_700_000_000_000,
        "operating_income": 1_380_000_000_000,
        "net_income": 835_000_000_000,
        "ebitda": 2_160_000_000_000,
        "equity": 12_100_000_000_000,
        "assets": 29_000_000_000_000,
        "debt": 9_600_000_000_000,
        "cash": 4_200_000_000_000,
        "ocf": 1_650_000_000_000,
        "fcf": 420_000_000_000,
        "eps": 160.0,
        "trend": -0.08,
        "volume": 18_000_000,
        "events": [("earnings_revision_up", "通期業績予想の上方修正", 70, 0.9)],
    },
    {
        "market": "jp",
        "ticker": "6902",
        "security_code": "6902",
        "edinet_code": "E01892",
        "company_name": "デンソー",
        "exchange": "TSE Prime",
        "sector": "輸送用機器",
        "industry": "自動車部品",
        "country": "JP",
        "currency": "JPY",
        "price": 2200,
        "market_cap": 6_900_000_000_000,
        "revenue": 7_200_000_000_000,
        "operating_income": 430_000_000_000,
        "net_income": 350_000_000_000,
        "ebitda": 790_000_000_000,
        "equity": 4_450_000_000_000,
        "assets": 8_650_000_000_000,
        "debt": 1_520_000_000_000,
        "cash": 1_100_000_000_000,
        "ocf": 710_000_000_000,
        "fcf": 180_000_000_000,
        "eps": 112.0,
        "trend": 0.14,
        "volume": 8_000_000,
        "events": [("new_product", "電動化向け新製品ライン発表", 48, 0.5)],
    },
    {
        "market": "jp",
        "ticker": "7974",
        "security_code": "7974",
        "edinet_code": "E02367",
        "company_name": "任天堂",
        "exchange": "TSE Prime",
        "sector": "その他製品",
        "industry": "ゲーム",
        "country": "JP",
        "currency": "JPY",
        "price": 10300,
        "market_cap": 12_700_000_000_000,
        "revenue": 1_700_000_000_000,
        "operating_income": 520_000_000_000,
        "net_income": 420_000_000_000,
        "ebitda": 570_000_000_000,
        "equity": 2_900_000_000_000,
        "assets": 3_400_000_000_000,
        "debt": 60_000_000_000,
        "cash": 1_600_000_000_000,
        "ocf": 510_000_000_000,
        "fcf": 450_000_000_000,
        "eps": 360.0,
        "trend": 0.28,
        "volume": 4_700_000,
        "events": [("new_product", "新型ハード関連発表", 55, 0.6)],
    },
    {
        "market": "jp",
        "ticker": "8058",
        "security_code": "8058",
        "edinet_code": "E02529",
        "company_name": "三菱商事",
        "exchange": "TSE Prime",
        "sector": "卸売業",
        "industry": "総合商社",
        "country": "JP",
        "currency": "JPY",
        "price": 3000,
        "market_cap": 12_200_000_000_000,
        "revenue": 19_600_000_000_000,
        "operating_income": 980_000_000_000,
        "net_income": 930_000_000_000,
        "ebitda": 1_350_000_000_000,
        "equity": 8_800_000_000_000,
        "assets": 25_000_000_000_000,
        "debt": 7_900_000_000_000,
        "cash": 2_000_000_000_000,
        "ocf": 1_150_000_000_000,
        "fcf": 820_000_000_000,
        "eps": 230.0,
        "trend": 0.04,
        "volume": 9_500_000,
        "events": [
            ("share_buyback", "自己株式取得と消却方針を発表", 26, 0.8),
            ("dividend_increase", "累進配当方針を更新", 62, 0.7),
        ],
    },
    {
        "market": "jp",
        "ticker": "6758",
        "security_code": "6758",
        "edinet_code": "E01777",
        "company_name": "ソニーグループ",
        "exchange": "TSE Prime",
        "sector": "電気機器",
        "industry": "エンタメ・電機",
        "country": "JP",
        "currency": "JPY",
        "price": 3800,
        "market_cap": 22_500_000_000_000,
        "revenue": 13_000_000_000_000,
        "operating_income": 1_320_000_000_000,
        "net_income": 980_000_000_000,
        "ebitda": 1_850_000_000_000,
        "equity": 9_300_000_000_000,
        "assets": 35_000_000_000_000,
        "debt": 5_200_000_000_000,
        "cash": 2_300_000_000_000,
        "ocf": 1_250_000_000_000,
        "fcf": 690_000_000_000,
        "eps": 165.0,
        "trend": 0.18,
        "volume": 12_000_000,
        "events": [("ma_or_capital_alliance", "戦略投資・資本提携を発表", 120, 0.6)],
    },
    {
        "market": "jp",
        "ticker": "9432",
        "security_code": "9432",
        "edinet_code": "E04430",
        "company_name": "NTT",
        "exchange": "TSE Prime",
        "sector": "情報・通信業",
        "industry": "通信",
        "country": "JP",
        "currency": "JPY",
        "price": 155,
        "market_cap": 13_300_000_000_000,
        "revenue": 13_300_000_000_000,
        "operating_income": 1_850_000_000_000,
        "net_income": 1_250_000_000_000,
        "ebitda": 3_250_000_000_000,
        "equity": 9_700_000_000_000,
        "assets": 29_500_000_000_000,
        "debt": 8_200_000_000_000,
        "cash": 1_000_000_000_000,
        "ocf": 2_900_000_000_000,
        "fcf": 1_050_000_000_000,
        "eps": 14.0,
        "trend": -0.22,
        "volume": 140_000_000,
        "events": [("dividend_increase", "増配予定を公表", 85, 0.5)],
    },
    {
        "market": "jp",
        "ticker": "1605",
        "security_code": "1605",
        "edinet_code": "E00043",
        "company_name": "INPEX",
        "exchange": "TSE Prime",
        "sector": "鉱業",
        "industry": "エネルギー",
        "country": "JP",
        "currency": "JPY",
        "price": 2150,
        "market_cap": 2_700_000_000_000,
        "revenue": 2_300_000_000_000,
        "operating_income": 1_000_000_000_000,
        "net_income": 420_000_000_000,
        "ebitda": 1_280_000_000_000,
        "equity": 4_400_000_000_000,
        "assets": 7_200_000_000_000,
        "debt": 1_400_000_000_000,
        "cash": 600_000_000_000,
        "ocf": 920_000_000_000,
        "fcf": 520_000_000_000,
        "eps": 330.0,
        "trend": 0.12,
        "volume": 10_000_000,
        "events": [
            ("share_buyback", "自己株式取得枠を発表", 40, 0.7),
            ("dividend_increase", "増配予定を発表", 82, 0.6),
        ],
    },
]


def seed_sample_data(conn, reset=False):
    if reset:
        clear_sample_tables(conn)

    for item in SAMPLE_COMPANIES:
        company_id = upsert_company(conn, item)
        delete_company_children(conn, company_id)
        insert_financials(conn, company_id, item)
        insert_price_history(conn, company_id, item)
        insert_events(conn, company_id, item)
        insert_filings(conn, company_id, item)
    conn.commit()
    return len(SAMPLE_COMPANIES)


def clear_sample_tables(conn):
    for table in [
        "watchlist",
        "screening_results",
        "events",
        "corporate_actions",
        "prices",
        "financial_facts",
        "filings",
        "company_master",
    ]:
        conn.execute("DELETE FROM %s" % table)
    conn.commit()


def upsert_company(conn, item):
    existing = conn.execute(
        """
        SELECT id FROM company_master
        WHERE market = ? AND (ticker = ? OR security_code = ?)
        LIMIT 1
        """,
        (item["market"], item["ticker"], item["security_code"]),
    ).fetchone()
    if existing:
        company_id = existing["id"]
        conn.execute(
            """
            UPDATE company_master
            SET ticker = ?, security_code = ?, edinet_code = ?, company_name = ?,
                exchange = ?, sector = ?, industry = ?, country = ?, currency = ?,
                is_active = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                item["ticker"],
                item["security_code"],
                item["edinet_code"],
                item["company_name"],
                item["exchange"],
                item["sector"],
                item["industry"],
                item["country"],
                item["currency"],
                company_id,
            ),
        )
        return company_id

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


def delete_company_children(conn, company_id):
    for table in ["events", "corporate_actions", "prices", "financial_facts", "filings"]:
        conn.execute("DELETE FROM %s WHERE company_id = ?" % table, (company_id,))


def insert_financials(conn, company_id, item):
    years = [2023, 2024, 2025]
    growth = [0.82, 0.94, 1.0]
    margin_variation = [0.88, 1.04, 1.0]
    for fiscal_year, factor, margin_factor in zip(years, growth, margin_variation):
        revenue = item["revenue"] * factor
        operating_income = item["operating_income"] * factor * margin_factor
        net_income = item["net_income"] * factor * margin_factor
        ebitda = item["ebitda"] * factor * margin_factor
        total_equity = item["equity"] * (0.86 + 0.07 * (fiscal_year - 2023))
        total_assets = item["assets"] * (0.88 + 0.06 * (fiscal_year - 2023))
        total_liabilities = total_assets - total_equity
        cash = item["cash"] * (0.84 + 0.08 * (fiscal_year - 2023))
        debt = item["debt"] * (0.86 + 0.07 * (fiscal_year - 2023))
        fcf = item["fcf"] * factor
        shares = item["market_cap"] / item["price"]
        eps = item["eps"] * factor * margin_factor
        conn.execute(
            """
            INSERT INTO financial_facts (
              company_id, source, fiscal_year, fiscal_quarter, period_type, period_end, currency,
              revenue, operating_income, net_income, ebitda, eps,
              total_assets, total_liabilities, total_equity, cash_and_equivalents,
              interest_bearing_debt, operating_cash_flow, investing_cash_flow,
              financing_cash_flow, free_cash_flow, shares_outstanding
            ) VALUES (?, 'sample', ?, NULL, 'annual', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                fiscal_year,
                "%s-03-31" % fiscal_year,
                item["currency"],
                revenue,
                operating_income,
                net_income,
                ebitda,
                eps,
                total_assets,
                total_liabilities,
                total_equity,
                cash,
                debt,
                item["ocf"] * factor,
                -abs(item["ocf"] * factor - fcf),
                item["ocf"] * 0.1,
                fcf,
                shares,
            ),
        )


def insert_price_history(conn, company_id, item):
    end = date.today()
    days = 420
    latest_price = item["price"]
    total_trend = item["trend"]
    start_price = latest_price / (1 + total_trend)
    shares = item["market_cap"] / latest_price
    for idx in range(days):
        progress = idx / float(days - 1)
        trade_date = end - timedelta(days=(days - idx - 1))
        wave = 0.04 * math.sin(progress * math.pi * 6 + company_id) * math.sin(progress * math.pi)
        pullback = -0.08 * math.sin(progress * math.pi) if total_trend < -0.2 else 0
        close = start_price * (1 + total_trend * progress + wave + pullback)
        close = max(close, latest_price * 0.35)
        volume_wave = 1 + 0.18 * math.sin(progress * math.pi * 8)
        volume = item["volume"] * volume_wave
        conn.execute(
            """
            INSERT INTO prices (
              company_id, trade_date, open, high, low, close, adjusted_close,
              volume, market_cap, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'sample')
            """,
            (
                company_id,
                trade_date.isoformat(),
                close * 0.995,
                close * 1.015,
                close * 0.985,
                close,
                close,
                volume,
                close * shares,
            ),
        )


def insert_events(conn, company_id, item):
    for event_type, title, days_ago, sentiment in item.get("events", []):
        event_date = (date.today() - timedelta(days=days_ago)).isoformat()
        conn.execute(
            """
            INSERT INTO events (
              company_id, event_date, event_type, title, description, source,
              sentiment_score, catalyst_score
            ) VALUES (?, ?, ?, ?, ?, 'sample', ?, NULL)
            """,
            (
                company_id,
                event_date,
                event_type,
                title,
                "%s のサンプルカタリストです。" % title,
                sentiment,
            ),
        )
        if event_type == "dividend_increase":
            conn.execute(
                """
                INSERT INTO corporate_actions (
                  company_id, action_type, announced_date, amount, description, source
                ) VALUES (?, 'dividend_increase', ?, ?, ?, 'sample')
                """,
                (company_id, event_date, 5.0, title),
            )
        if event_type == "share_buyback":
            conn.execute(
                """
                INSERT INTO corporate_actions (
                  company_id, action_type, announced_date, amount, description, source
                ) VALUES (?, 'share_buyback', ?, ?, ?, 'sample')
                """,
                (company_id, event_date, 100_000_000_000, title),
            )


def insert_filings(conn, company_id, item):
    conn.execute(
        """
        INSERT INTO filings (
          company_id, source, document_id, document_type, filing_date, period_end,
          title, url, parsed_status
        ) VALUES (?, 'sample', ?, 'annual_report', ?, ?, ?, ?, 'parsed')
        """,
        (
            company_id,
            "SAMPLE-%s-2025" % item["ticker"],
            "%s-06-30" % date.today().year,
            "2025-03-31",
            "%s FY2025 annual sample filing" % item["company_name"],
            "https://example.local/filings/%s" % item["ticker"],
        ),
    )
