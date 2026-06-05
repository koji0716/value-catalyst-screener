from src.ingestion.jquants_sync import sync_jquants_financials


def sync_financials(conn, market="jp", use_sample=True, client=None, codes=None):
    if market not in ("jp", "all"):
        return 0
    if client is not None and codes:
        return sync_jquants_financials(conn, client, codes)
    # Sample financials are seeded with sample companies.
    return 0
