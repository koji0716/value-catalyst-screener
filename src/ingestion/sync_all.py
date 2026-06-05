from src.db.session import get_connection
from src.ingestion.sample_data import seed_sample_data


def sync_market(market="jp", start_date=None, end_date=None, use_sample=True, reset_sample=False):
    if market not in ("jp", "all"):
        return {
            "market": market,
            "inserted_companies": 0,
            "message": "MVP 1は日本株サンプルデータのみ同期します。",
        }
    conn = get_connection()
    try:
        inserted = seed_sample_data(conn, reset=reset_sample) if use_sample else 0
        return {
            "market": market,
            "from": start_date,
            "to": end_date,
            "inserted_companies": inserted,
            "message": "サンプル日本株データを同期しました。",
        }
    finally:
        conn.close()

