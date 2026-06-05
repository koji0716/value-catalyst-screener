import json

from src.db.models import INDEXES, SCHEMA
from src.db.session import get_connection
from src.utils.file_utils import load_presets


def init_db(db_path=None):
    conn = get_connection(db_path)
    try:
        for statement in SCHEMA:
            conn.execute(statement)
        for statement in INDEXES:
            conn.execute(statement)
        conn.commit()
        seed_presets(conn)
    finally:
        conn.close()


def seed_presets(conn):
    presets = load_presets()
    for name, config in presets.items():
        conn.execute(
            """
            INSERT INTO user_presets (preset_name, description, config_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(preset_name) DO UPDATE SET
              description = excluded.description,
              config_json = excluded.config_json,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                name,
                config.get("description", ""),
                json.dumps(config, ensure_ascii=False, sort_keys=True),
            ),
        )
    conn.commit()

