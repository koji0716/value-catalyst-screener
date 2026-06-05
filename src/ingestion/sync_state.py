import json


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
