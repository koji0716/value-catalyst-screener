SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS company_master (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      market TEXT NOT NULL,
      ticker TEXT,
      security_code TEXT,
      cik TEXT,
      edinet_code TEXT,
      company_name TEXT NOT NULL,
      exchange TEXT,
      sector TEXT,
      industry TEXT,
      country TEXT,
      currency TEXT,
      is_active BOOLEAN DEFAULT 1,
      listed_date DATE,
      delisted_date DATE,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS filings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      company_id INTEGER NOT NULL,
      source TEXT NOT NULL,
      document_id TEXT NOT NULL,
      document_type TEXT,
      filing_date DATE,
      period_end DATE,
      title TEXT,
      url TEXT,
      local_path TEXT,
      parsed_status TEXT DEFAULT 'pending',
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(company_id) REFERENCES company_master(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS financial_facts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      company_id INTEGER NOT NULL,
      source TEXT NOT NULL,
      fiscal_year INTEGER,
      fiscal_quarter TEXT,
      period_type TEXT,
      period_end DATE,
      currency TEXT,
      revenue REAL,
      operating_income REAL,
      net_income REAL,
      ebitda REAL,
      eps REAL,
      total_assets REAL,
      total_liabilities REAL,
      total_equity REAL,
      cash_and_equivalents REAL,
      interest_bearing_debt REAL,
      operating_cash_flow REAL,
      investing_cash_flow REAL,
      financing_cash_flow REAL,
      free_cash_flow REAL,
      shares_outstanding REAL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(company_id) REFERENCES company_master(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prices (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      company_id INTEGER NOT NULL,
      trade_date DATE NOT NULL,
      open REAL,
      high REAL,
      low REAL,
      close REAL,
      adjusted_close REAL,
      volume REAL,
      market_cap REAL,
      source TEXT,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(company_id) REFERENCES company_master(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS corporate_actions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      company_id INTEGER NOT NULL,
      action_type TEXT NOT NULL,
      announced_date DATE,
      effective_date DATE,
      amount REAL,
      ratio REAL,
      description TEXT,
      source TEXT,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(company_id) REFERENCES company_master(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      company_id INTEGER NOT NULL,
      event_date DATE,
      event_type TEXT,
      title TEXT,
      description TEXT,
      source TEXT,
      sentiment_score REAL,
      catalyst_score REAL,
      local_path TEXT,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(company_id) REFERENCES company_master(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS screening_results (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id TEXT NOT NULL,
      company_id INTEGER NOT NULL,
      preset_name TEXT,
      total_score REAL,
      valuation_score REAL,
      quality_score REAL,
      safety_score REAL,
      momentum_score REAL,
      catalyst_score REAL,
      risk_score REAL,
      recommendation_label TEXT,
      reason_summary TEXT,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(company_id) REFERENCES company_master(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_presets (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      preset_name TEXT UNIQUE NOT NULL,
      description TEXT,
      config_json TEXT NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS watchlist (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      company_id INTEGER NOT NULL UNIQUE,
      label TEXT,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(company_id) REFERENCES company_master(id)
    )
    """,
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_company_market_ticker ON company_master(market, ticker)",
    "CREATE INDEX IF NOT EXISTS idx_company_market_security_code ON company_master(market, security_code)",
    "CREATE INDEX IF NOT EXISTS idx_financial_company_period ON financial_facts(company_id, period_end)",
    "CREATE INDEX IF NOT EXISTS idx_prices_company_date ON prices(company_id, trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_events_company_date ON events(company_id, event_date)",
    "CREATE INDEX IF NOT EXISTS idx_screening_run ON screening_results(run_id)",
]

