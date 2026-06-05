from src.ingestion.jquants_sync import sync_jquants_companies
from src.ingestion.sample_data import seed_sample_data


def sync_companies(conn, market="jp", use_sample=True, client=None, codes=None, limit=None):
    if market not in ("jp", "all"):
        return 0
    if client is not None:
        return sync_jquants_companies(conn, client, codes=codes, limit=limit)
    if use_sample:
        return seed_sample_data(conn, reset=False)
    return 0
