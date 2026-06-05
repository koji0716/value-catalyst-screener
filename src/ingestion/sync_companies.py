from src.ingestion.sample_data import seed_sample_data


def sync_companies(conn, market="jp", use_sample=True):
    if market not in ("jp", "all"):
        return 0
    if use_sample:
        return seed_sample_data(conn, reset=False)
    return 0

