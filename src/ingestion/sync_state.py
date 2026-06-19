import json
import os
import sqlite3
import socket


SYNC_LOCKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_locks (
  lock_key TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  acquired_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  expires_at DATETIME NOT NULL
)
"""


def sync_lock_owner():
    return "%s:%s" % (socket.gethostname(), os.getpid())


def ensure_sync_locks_table(conn):
    conn.execute(SYNC_LOCKS_SCHEMA)


def acquire_sync_lock(conn, lock_key, owner=None, ttl_minutes=240):
    owner = owner or sync_lock_owner()
    ensure_sync_locks_table(conn)
    conn.execute("DELETE FROM sync_locks WHERE expires_at <= CURRENT_TIMESTAMP")
    try:
        conn.execute(
            """
            INSERT INTO sync_locks (lock_key, owner, expires_at)
            VALUES (?, ?, datetime(CURRENT_TIMESTAMP, ?))
            """,
            (lock_key, owner, "+%d minutes" % int(ttl_minutes)),
        )
        conn.commit()
        return owner
    except sqlite3.IntegrityError:
        conn.rollback()
        existing = conn.execute(
            """
            SELECT owner, acquired_at, expires_at
            FROM sync_locks
            WHERE lock_key = ?
            """,
            (lock_key,),
        ).fetchone()
        if existing:
            raise RuntimeError(
                "別のデータ取得が実行中です。完了後に再実行してください。"
                " lock=%s owner=%s acquired_at=%s expires_at=%s"
                % (lock_key, existing["owner"], existing["acquired_at"], existing["expires_at"])
            )
        raise


def release_sync_lock(conn, lock_key, owner):
    if not owner:
        return
    ensure_sync_locks_table(conn)
    conn.execute(
        """
        DELETE FROM sync_locks
        WHERE lock_key = ? AND owner = ?
        """,
        (lock_key, owner),
    )
    conn.commit()

def make_state_key(market, source, mode):
    return "%s:%s:%s" % (market or "all", source or "auto", mode or "manual")


def begin_sync_job(conn, job_type, market, source, mode, params):
    cur = conn.execute(
        """
        INSERT INTO sync_jobs (
          job_type, market, source, mode, status, params_json, started_at
        ) VALUES (?, ?, ?, ?, 'running', ?, CURRENT_TIMESTAMP)
        """,
        (job_type, market, source, mode, json.dumps(params, ensure_ascii=False, sort_keys=True)),
    )
    conn.commit()
    return cur.lastrowid


def finish_sync_job(conn, job_id, status, result=None, message=None):
    conn.execute(
        """
        UPDATE sync_jobs
        SET status = ?, result_json = ?, message = ?, finished_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            status,
            json.dumps(result or {}, ensure_ascii=False, sort_keys=True),
            message,
            job_id,
        ),
    )
    conn.commit()


def upsert_sync_state(conn, market, source, mode, status, params, result=None, message=None):
    key = make_state_key(market, source, mode)
    conn.execute(
        """
        INSERT INTO sync_state (
          state_key, market, source, mode, status, last_success_at,
          last_attempt_at, last_from_date, last_to_date, target_codes_json,
          result_json, message, updated_at
        ) VALUES (?, ?, ?, ?, ?, CASE WHEN ? = 'success' THEN CURRENT_TIMESTAMP ELSE NULL END,
                  CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(state_key) DO UPDATE SET
          status = excluded.status,
          last_success_at = CASE
            WHEN excluded.status = 'success' THEN CURRENT_TIMESTAMP
            ELSE sync_state.last_success_at
          END,
          last_attempt_at = CURRENT_TIMESTAMP,
          last_from_date = excluded.last_from_date,
          last_to_date = excluded.last_to_date,
          target_codes_json = excluded.target_codes_json,
          result_json = excluded.result_json,
          message = excluded.message,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            key,
            market,
            source,
            mode,
            status,
            status,
            params.get("start_date"),
            params.get("end_date"),
            json.dumps(params.get("codes") or [], ensure_ascii=False),
            json.dumps(result or {}, ensure_ascii=False, sort_keys=True),
            message,
        ),
    )
    conn.commit()


def latest_sync_states(conn, limit=10):
    rows = conn.execute(
        """
        SELECT *
        FROM sync_state
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def latest_sync_jobs(conn, limit=10):
    rows = conn.execute(
        """
        SELECT *
        FROM sync_jobs
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]
