import json
import re
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path

from src.analysis.scoring import explain_ticker, find_company_by_ticker, screen_companies
from src.db.session import get_connection
from src.ingestion.coverage import data_coverage_rows
from src.utils.file_utils import DISCLAIMER, get_db_path, load_presets


VALID_MARKETS = {"all", "jp", "us"}
READ_QUERY_PREFIX = re.compile(r"^(SELECT|WITH)\b", re.IGNORECASE)
MAX_TOOL_ROWS = 1000
MAX_QUERY_SECONDS = 10.0


def _bounded_limit(value, default=20, maximum=MAX_TOOL_ROWS):
    limit = default if value is None else int(value)
    if limit < 1:
        raise ValueError("limit must be at least 1")
    return min(limit, maximum)


def _market(value):
    market = str(value or "all").strip().lower()
    if market not in VALID_MARKETS:
        raise ValueError("market must be one of: all, jp, us")
    return market


def _iso_date(value, field_name):
    if value in (None, ""):
        return None
    text = str(value)
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("%s must use YYYY-MM-DD format" % field_name) from exc
    return text


def _strip_leading_comments(sql):
    remaining = str(sql or "").lstrip()
    while remaining:
        if remaining.startswith("--"):
            newline = remaining.find("\n")
            if newline < 0:
                return ""
            remaining = remaining[newline + 1 :].lstrip()
            continue
        if remaining.startswith("/*"):
            end = remaining.find("*/", 2)
            if end < 0:
                return ""
            remaining = remaining[end + 2 :].lstrip()
            continue
        break
    return remaining


def _json_value(value):
    if isinstance(value, bytes):
        return value.hex()
    return value


def _read_authorizer(action, arg1, arg2, database_name, trigger_name):
    denied_names = [
        "SQLITE_ALTER_TABLE",
        "SQLITE_ANALYZE",
        "SQLITE_ATTACH",
        "SQLITE_CREATE_INDEX",
        "SQLITE_CREATE_TABLE",
        "SQLITE_CREATE_TEMP_INDEX",
        "SQLITE_CREATE_TEMP_TABLE",
        "SQLITE_CREATE_TEMP_TRIGGER",
        "SQLITE_CREATE_TEMP_VIEW",
        "SQLITE_CREATE_TRIGGER",
        "SQLITE_CREATE_VIEW",
        "SQLITE_CREATE_VTABLE",
        "SQLITE_DELETE",
        "SQLITE_DETACH",
        "SQLITE_DROP_INDEX",
        "SQLITE_DROP_TABLE",
        "SQLITE_DROP_TEMP_INDEX",
        "SQLITE_DROP_TEMP_TABLE",
        "SQLITE_DROP_TEMP_TRIGGER",
        "SQLITE_DROP_TEMP_VIEW",
        "SQLITE_DROP_TRIGGER",
        "SQLITE_DROP_VIEW",
        "SQLITE_DROP_VTABLE",
        "SQLITE_INSERT",
        "SQLITE_PRAGMA",
        "SQLITE_REINDEX",
        "SQLITE_SAVEPOINT",
        "SQLITE_TRANSACTION",
        "SQLITE_UPDATE",
    ]
    denied_actions = {getattr(sqlite3, name, None) for name in denied_names}
    denied_actions.discard(None)
    if action in denied_actions:
        return sqlite3.SQLITE_DENY
    if action == getattr(sqlite3, "SQLITE_FUNCTION", -1):
        function_name = str(arg2 or arg1 or "").lower()
        if function_name in {"load_extension", "readfile", "writefile"}:
            return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


class ValueCatalystService:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path or get_db_path()).resolve()

    def _connect(self):
        return get_connection(self.db_path, read_only=True)

    def database_overview(self):
        if not self.db_path.exists():
            raise FileNotFoundError("Database not found: %s" % self.db_path)
        stat = self.db_path.stat()
        conn = self._connect()
        try:
            table_rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
            counts = {}
            for row in table_rows:
                table = row["name"]
                counts[table] = conn.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0]
            coverage = data_coverage_rows(conn)
        finally:
            conn.close()
        return {
            "database": {
                "path": str(self.db_path),
                "size_bytes": stat.st_size,
                "last_modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
                "read_only": True,
            },
            "table_counts": counts,
            "coverage": coverage,
            "disclaimer": DISCLAIMER,
        }

    def list_schema(self):
        conn = self._connect()
        try:
            tables = conn.execute(
                """
                SELECT name, sql
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
            result = []
            for table in tables:
                table_name = table["name"]
                columns = conn.execute('PRAGMA table_info("%s")' % table_name).fetchall()
                indexes = conn.execute(
                    """
                    SELECT name, sql
                    FROM sqlite_master
                    WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL
                    ORDER BY name
                    """,
                    (table_name,),
                ).fetchall()
                result.append(
                    {
                        "name": table_name,
                        "columns": [
                            {
                                "name": column["name"],
                                "type": column["type"],
                                "not_null": bool(column["notnull"]),
                                "default": column["dflt_value"],
                                "primary_key": bool(column["pk"]),
                            }
                            for column in columns
                        ],
                        "indexes": [dict(index) for index in indexes],
                    }
                )
            return {"tables": result}
        finally:
            conn.close()

    def list_presets(self):
        presets = load_presets()
        return {
            "presets": [
                {
                    "name": name,
                    "description": config.get("description", ""),
                    "filters": config.get("filters", {}),
                    "weights": config.get("weights", {}),
                }
                for name, config in presets.items()
            ]
        }

    def search_companies(self, query="", market="all", limit=20):
        market = _market(market)
        limit = _bounded_limit(limit, maximum=100)
        text = str(query or "").strip()
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = "%%%s%%" % escaped
        clauses = ["c.is_active = 1"]
        params = []
        if market != "all":
            clauses.append("c.market = ?")
            params.append(market)
        if text:
            clauses.append(
                """
                (
                  UPPER(COALESCE(c.ticker, '')) LIKE UPPER(?) ESCAPE '\\'
                  OR c.security_code LIKE ? ESCAPE '\\'
                  OR UPPER(c.company_name) LIKE UPPER(?) ESCAPE '\\'
                  OR UPPER(COALESCE(c.sector, '')) LIKE UPPER(?) ESCAPE '\\'
                  OR UPPER(COALESCE(c.industry, '')) LIKE UPPER(?) ESCAPE '\\'
                )
                """
            )
            params.extend([pattern] * 5)
        params.append(limit)
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT
                  c.id, c.market, c.ticker, c.security_code, c.edinet_code,
                  c.company_name, c.exchange, c.sector, c.industry, c.currency,
                  (SELECT MAX(p.trade_date) FROM prices p WHERE p.company_id = c.id) AS latest_price_date,
                  (SELECT MAX(f.period_end) FROM financial_facts f WHERE f.company_id = c.id) AS latest_financial_period_end
                FROM company_master c
                WHERE %s
                ORDER BY
                  CASE WHEN UPPER(COALESCE(c.ticker, '')) = UPPER(?) THEN 0
                       WHEN c.security_code = ? THEN 0
                       ELSE 1 END,
                  c.market, c.ticker
                LIMIT ?
                """
                % " AND ".join(clauses),
                tuple(params[:-1] + [text, text, params[-1]]),
            ).fetchall()
            return {"companies": [dict(row) for row in rows], "count": len(rows)}
        finally:
            conn.close()

    def analyze_company(self, ticker, preset="balanced"):
        metrics, explanation = explain_ticker(
            ticker,
            preset_name=preset,
            db_path=self.db_path,
            read_only=True,
        )
        return {
            "analysis": metrics,
            "explanation": explanation,
            "preset": preset,
            "disclaimer": DISCLAIMER,
        }

    def screen_stocks(
        self,
        market="all",
        preset="balanced",
        max_per=None,
        max_pbr=None,
        min_roe=None,
        min_equity_ratio=None,
        limit=20,
    ):
        market = _market(market)
        limit = _bounded_limit(limit, maximum=100)
        overrides = {
            "max_per": max_per,
            "max_pbr": max_pbr,
            "min_roe": min_roe,
            "min_equity_ratio": min_equity_ratio,
        }
        results, run_id = screen_companies(
            preset_name=preset,
            market=market,
            overrides=overrides,
            limit=limit,
            db_path=self.db_path,
            save=False,
            read_only=True,
        )
        return {
            "results": results,
            "count": len(results),
            "preset": preset,
            "market": market,
            "saved": run_id is not None,
            "disclaimer": DISCLAIMER,
        }

    def price_history(self, ticker, start_date=None, end_date=None, limit=250):
        start_date = _iso_date(start_date, "start_date")
        end_date = _iso_date(end_date, "end_date")
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        limit = _bounded_limit(limit)
        conn = self._connect()
        try:
            company = find_company_by_ticker(conn, ticker)
            if not company:
                raise ValueError("Company not found: %s" % ticker)
            clauses = ["company_id = ?"]
            params = [company["id"]]
            if start_date:
                clauses.append("trade_date >= ?")
                params.append(start_date)
            if end_date:
                clauses.append("trade_date <= ?")
                params.append(end_date)
            params.append(limit)
            rows = conn.execute(
                """
                SELECT *
                FROM (
                  SELECT trade_date, open, high, low, close, adjusted_close, volume, market_cap, source
                  FROM prices
                  WHERE %s
                  ORDER BY trade_date DESC
                  LIMIT ?
                )
                ORDER BY trade_date
                """
                % " AND ".join(clauses),
                tuple(params),
            ).fetchall()
            return {
                "company": {
                    "market": company["market"],
                    "ticker": company["ticker"],
                    "security_code": company["security_code"],
                    "company_name": company["company_name"],
                },
                "prices": [dict(row) for row in rows],
                "count": len(rows),
            }
        finally:
            conn.close()

    def financial_history(self, ticker, limit=8):
        limit = _bounded_limit(limit, maximum=50)
        conn = self._connect()
        try:
            company = find_company_by_ticker(conn, ticker)
            if not company:
                raise ValueError("Company not found: %s" % ticker)
            rows = conn.execute(
                """
                SELECT
                  source, fiscal_year, fiscal_quarter, period_type, period_end, currency,
                  revenue, operating_income, net_income, ebitda, eps,
                  total_assets, total_liabilities, total_equity,
                  cash_and_equivalents, interest_bearing_debt,
                  operating_cash_flow, investing_cash_flow, financing_cash_flow,
                  free_cash_flow, shares_outstanding
                FROM financial_facts
                WHERE company_id = ?
                ORDER BY period_end DESC, fiscal_year DESC, id DESC
                LIMIT ?
                """,
                (company["id"], limit),
            ).fetchall()
            return {
                "company": {
                    "market": company["market"],
                    "ticker": company["ticker"],
                    "security_code": company["security_code"],
                    "company_name": company["company_name"],
                },
                "financials": [dict(row) for row in rows],
                "count": len(rows),
            }
        finally:
            conn.close()

    def company_activity(self, ticker, limit=20):
        limit = _bounded_limit(limit, maximum=100)
        conn = self._connect()
        try:
            company = find_company_by_ticker(conn, ticker)
            if not company:
                raise ValueError("Company not found: %s" % ticker)
            company_id = company["id"]
            events = conn.execute(
                """
                SELECT event_date, event_type, title, description, source, sentiment_score, catalyst_score
                FROM events
                WHERE company_id = ?
                ORDER BY event_date DESC, id DESC
                LIMIT ?
                """,
                (company_id, limit),
            ).fetchall()
            filings = conn.execute(
                """
                SELECT filing_date, period_end, document_type, title, url, source, parsed_status
                FROM filings
                WHERE company_id = ?
                ORDER BY filing_date DESC, id DESC
                LIMIT ?
                """,
                (company_id, limit),
            ).fetchall()
            actions = conn.execute(
                """
                SELECT action_type, announced_date, effective_date, amount, ratio, description, source
                FROM corporate_actions
                WHERE company_id = ?
                ORDER BY announced_date DESC, id DESC
                LIMIT ?
                """,
                (company_id, limit),
            ).fetchall()
            return {
                "company": {
                    "market": company["market"],
                    "ticker": company["ticker"],
                    "security_code": company["security_code"],
                    "company_name": company["company_name"],
                },
                "events": [dict(row) for row in events],
                "filings": [dict(row) for row in filings],
                "corporate_actions": [dict(row) for row in actions],
            }
        finally:
            conn.close()

    def read_query(self, sql, parameters=None, max_rows=100):
        statement = _strip_leading_comments(sql)
        if not READ_QUERY_PREFIX.match(statement):
            raise ValueError("Only SELECT or WITH queries are allowed.")
        max_rows = _bounded_limit(max_rows)
        if parameters is None:
            parameters = []
        if not isinstance(parameters, (list, tuple)):
            raise ValueError("parameters must be a JSON array")

        conn = self._connect()
        started = time.monotonic()

        def stop_long_query():
            return 1 if time.monotonic() - started > MAX_QUERY_SECONDS else 0

        conn.set_authorizer(_read_authorizer)
        conn.set_progress_handler(stop_long_query, 10_000)
        try:
            cursor = conn.execute(statement, tuple(parameters))
            columns = [column[0] for column in cursor.description or []]
            rows = cursor.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            rows = rows[:max_rows]
            return {
                "columns": columns,
                "rows": [[_json_value(value) for value in row] for row in rows],
                "row_count": len(rows),
                "truncated": truncated,
                "max_rows": max_rows,
            }
        except sqlite3.DatabaseError as exc:
            if "not authorized" in str(exc).lower():
                raise ValueError("The query uses an operation that is not allowed.") from exc
            if "interrupted" in str(exc).lower():
                raise ValueError("The query exceeded the %s second execution limit." % MAX_QUERY_SECONDS) from exc
            raise ValueError("Query failed: %s" % exc) from exc
        finally:
            conn.set_progress_handler(None, 0)
            conn.close()

    def overview_json(self):
        return json.dumps(self.database_overview(), ensure_ascii=False, indent=2)

    def schema_json(self):
        return json.dumps(self.list_schema(), ensure_ascii=False, indent=2)
