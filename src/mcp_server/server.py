import argparse
from typing import Any, List, Optional

from src.mcp_server.service import ValueCatalystService


INSTRUCTIONS = """
Value Catalyst Screener MCP server.

This server exposes the local SQLite database as read-only tools and resources.
It is for screening, analysis, and database inspection only. It does not update
the database, run ingestion, or provide investment advice.
"""


def create_mcp_server(db_path=None, host="127.0.0.1", port=8000):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "MCP dependencies are not installed. Use Python 3.10+ and run: "
            'python -m pip install "mcp[cli]>=1.0,<2.0"'
        ) from exc

    service = ValueCatalystService(db_path)
    mcp = FastMCP(
        "Value Catalyst Screener",
        instructions=INSTRUCTIONS.strip(),
        host=host,
        port=port,
        json_response=True,
    )

    @mcp.tool()
    def database_overview():
        """Return DB file metadata, table row counts, and market coverage."""
        return service.database_overview()

    @mcp.tool()
    def list_database_schema():
        """Return tables, columns, and indexes in the local screener database."""
        return service.list_schema()

    @mcp.tool()
    def query_database(sql: str, parameters: Optional[List[Any]] = None, max_rows: int = 100):
        """
        Execute a read-only SELECT/WITH query against the screener SQLite database.

        The query runs against the configured DB in read-only mode. Mutating SQL,
        PRAGMA, ATTACH/DETACH, extension loading, and long-running queries are denied.
        """
        return service.read_query(sql=sql, parameters=parameters, max_rows=max_rows)

    @mcp.tool()
    def list_screening_presets():
        """Return configured screening presets, filters, and scoring weights."""
        return service.list_presets()

    @mcp.tool()
    def search_companies(query: str = "", market: str = "all", limit: int = 20):
        """Search active companies by ticker, security code, company name, sector, or industry."""
        return service.search_companies(query=query, market=market, limit=limit)

    @mcp.tool()
    def analyze_company(ticker: str, preset: str = "balanced"):
        """Return existing app scoring metrics and explanation for a ticker/security code."""
        return service.analyze_company(ticker=ticker, preset=preset)

    @mcp.tool()
    def screen_stocks(
        market: str = "all",
        preset: str = "balanced",
        max_per: Optional[float] = None,
        max_pbr: Optional[float] = None,
        min_roe: Optional[float] = None,
        min_equity_ratio: Optional[float] = None,
        limit: int = 20,
    ):
        """Run the existing screener without saving a screening_results run."""
        return service.screen_stocks(
            market=market,
            preset=preset,
            max_per=max_per,
            max_pbr=max_pbr,
            min_roe=min_roe,
            min_equity_ratio=min_equity_ratio,
            limit=limit,
        )

    @mcp.tool()
    def get_price_history(
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 250,
    ):
        """Return OHLCV price history for a ticker/security code."""
        return service.price_history(ticker=ticker, start_date=start_date, end_date=end_date, limit=limit)

    @mcp.tool()
    def get_financial_history(ticker: str, limit: int = 8):
        """Return recent financial_facts rows for a ticker/security code."""
        return service.financial_history(ticker=ticker, limit=limit)

    @mcp.tool()
    def get_company_activity(ticker: str, limit: int = 20):
        """Return recent events, filings, and corporate actions for a ticker/security code."""
        return service.company_activity(ticker=ticker, limit=limit)

    @mcp.resource("value-catalyst://overview")
    def overview_resource():
        """Database overview as JSON."""
        return service.overview_json()

    @mcp.resource("value-catalyst://schema")
    def schema_resource():
        """Database schema as JSON."""
        return service.schema_json()

    @mcp.resource("value-catalyst://company/{ticker}")
    def company_resource(ticker: str):
        """Company analysis as JSON."""
        import json

        return json.dumps(service.analyze_company(ticker), ensure_ascii=False, indent=2)

    return mcp


def run_server(db_path=None, transport="stdio", host="127.0.0.1", port=8000):
    if transport not in {"stdio", "streamable-http"}:
        raise ValueError("transport must be stdio or streamable-http")
    mcp = create_mcp_server(db_path=db_path, host=host, port=port)
    mcp.run(transport=transport)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Value Catalyst Screener MCP server")
    parser.add_argument("--db-path", help="SQLite database path. Defaults to DB_PATH or data/value_screener.sqlite.")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    return run_server(db_path=args.db_path, transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
