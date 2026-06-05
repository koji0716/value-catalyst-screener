from src.ingestion.jquants_sync import sync_jquants_prices


def sync_prices(conn, market="jp", use_sample=True, client=None, codes=None, start_date=None, end_date=None):
    if market not in ("jp", "all"):
        return 0
    if client is not None and codes:
        return sync_jquants_prices(conn, client, codes, start_date=start_date, end_date=end_date)
    # Sample prices are seeded with sample companies.
    return 0
