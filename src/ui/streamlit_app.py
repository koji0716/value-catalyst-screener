import json
from datetime import date, timedelta

try:
    import streamlit as st
except Exception:
    print("Streamlit is not installed. Run: python -m pip install -r requirements.txt")
    raise SystemExit(1)

try:
    import pandas as pd
except Exception:
    pd = None

try:
    import plotly.express as px
except Exception:
    px = None

from src.analysis.scoring import explain_ticker, screen_companies
from src.db.migrations import init_db
from src.db.session import get_connection
from src.ingestion.coverage import data_coverage_rows
from src.ingestion.refresh import refresh_until_current
from src.ingestion.sync_all import sync_jp_screening_source, sync_market
from src.ingestion.sync_state import latest_sync_jobs, latest_sync_states
from src.nlp.report_generator import export_results
from src.ui.components import disclaimer, format_money, format_pct, format_ratio
from src.ui.glossary import GLOSSARY_ORDER, term_help, term_rows
from src.utils.file_utils import load_presets


st.set_page_config(page_title="Value Catalyst Screener", layout="wide")


DEFAULT_START_DAYS = 420
RUN_RESULT_KEYS = [
    "market",
    "source",
    "mode",
    "message",
    "stopped_reason",
    "next_action",
    "from",
    "to",
    "batches_run",
    "inserted_companies",
    "updated_companies",
    "inserted_prices",
    "inserted_financials",
    "inserted_filings",
    "inserted_dividends",
    "inserted_actions",
    "inserted_events",
    "inserted_text_blocks",
    "inserted_risk_events",
    "processed_price_dates",
    "processed_financial_dates",
    "first_price_date",
    "last_price_date",
    "first_financial_date",
    "last_financial_date",
    "warnings",
    "error",
]
RECOMMENDATION_TERMS = ["Strong Candidate", "Candidate", "Watch", "Weak", "Exclude"]
SCREENING_HELP_TERMS = [
    "PER",
    "PBR",
    "EV/EBITDA",
    "ROE",
    "自己資本比率",
    "営業利益率",
    "FCF利回り",
    "時価総額",
    "売買代金",
    "カタリスト",
    "52週高値からの下落率",
    "総合スコア",
] + RECOMMENDATION_TERMS
DEEP_HELP_TERMS = [
    "総合スコア",
    "PER",
    "PBR",
    "EV/EBITDA",
    "ROE",
    "自己資本比率",
    "営業利益率",
    "カタリスト",
    "バリュートラップ",
    "EDINET",
    "EDGAR",
    "J-Quants",
] + RECOMMENDATION_TERMS
NUMERIC_FILTERS = [
    {
        "key": "max_per",
        "label": "PER上限",
        "term": "PER",
        "default": 20.0,
        "min_value": 0.0,
        "step": 1.0,
    },
    {
        "key": "max_pbr",
        "label": "PBR上限",
        "term": "PBR",
        "default": 2.0,
        "min_value": 0.0,
        "step": 0.1,
    },
    {
        "key": "max_ev_ebitda",
        "label": "EV/EBITDA上限",
        "term": "EV/EBITDA",
        "default": 10.0,
        "min_value": 0.0,
        "step": 0.5,
    },
    {
        "key": "min_roe",
        "label": "ROE下限(%)",
        "term": "ROE",
        "default": 5.0,
        "min_value": -100.0,
        "step": 1.0,
    },
    {
        "key": "min_operating_margin",
        "label": "営業利益率下限(%)",
        "term": "営業利益率",
        "default": 0.0,
        "min_value": -100.0,
        "step": 1.0,
    },
    {
        "key": "min_equity_ratio",
        "label": "自己資本比率下限(%)",
        "term": "自己資本比率",
        "default": 30.0,
        "min_value": -100.0,
        "step": 1.0,
    },
    {
        "key": "min_market_cap",
        "label": "時価総額下限",
        "term": "時価総額",
        "default": 30_000_000_000.0,
        "min_value": 0.0,
        "step": 1_000_000_000.0,
    },
    {
        "key": "min_average_volume",
        "label": "平均売買代金下限",
        "term": "売買代金",
        "default": 50_000_000.0,
        "min_value": 0.0,
        "step": 10_000_000.0,
    },
    {
        "key": "max_drawdown_from_52w_high",
        "label": "52週高値からの下落率条件(%)",
        "term": "52週高値からの下落率",
        "default": -25.0,
        "min_value": -100.0,
        "step": 1.0,
    },
]
BOOLEAN_FILTERS = [
    ("exclude_negative_equity", "債務超過を除外", "自己資本比率"),
    ("exclude_operating_cf_negative", "営業CF赤字を除外", "営業CF"),
    ("require_recent_catalyst", "直近カタリストありに限定", "カタリスト"),
]


def ensure_data():
    init_db()
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM company_master").fetchone()["c"]
    finally:
        conn.close()
    if count == 0:
        sync_market(market="all", use_sample=True)


def init_session_state():
    defaults = {
        "fetch_result": None,
        "screening": None,
        "deep_fetch_result": None,
        "deep_ticker": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def parse_json_dict(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def result_count(result, scalar_key, list_key):
    scalar = result.get(scalar_key)
    if isinstance(scalar, list):
        return len(scalar)
    if scalar is not None:
        return scalar
    value = result.get(list_key)
    if isinstance(value, list):
        return len(value)
    return None


def pct_text(value):
    if value is None:
        return "N/A"
    return "%.1f%%" % value


def count_with_pct(count, pct_value):
    if count is None:
        return "N/A"
    return "%s (%s)" % (f"{int(count):,}", pct_text(pct_value))


def progress_text(done, total, pct_value):
    if not total:
        return "N/A"
    return "%s / %s (%s)" % (f"{int(done or 0):,}", f"{int(total):,}", pct_text(pct_value))


def clamp_progress(value):
    if value is None:
        return 0.0
    return max(0.0, min(float(value) / 100.0, 1.0))


def coverage_rows():
    conn = get_connection()
    try:
        return data_coverage_rows(conn)
    finally:
        conn.close()


def coverage_dataframe():
    display_rows = []
    for row in coverage_rows():
        display_rows.append(
            {
                "市場": row["market_label"],
                "会社数": progress_text(row["company_count"], row["universe_records"], row["master_coverage_pct"]),
                "主要データ取り込み率": pct_text(row["major_data_coverage_pct"]),
                "株価取得": count_with_pct(row["price_company_count"], row["price_coverage_pct"]),
                "財務取得": count_with_pct(row["financial_company_count"], row["financial_coverage_pct"]),
                "開示取得": count_with_pct(row["filing_company_count"], row["filing_coverage_pct"]),
                "配当等取得": count_with_pct(row["action_company_count"], row["action_coverage_pct"]),
                "主要データ最新化率": pct_text(row["major_freshness_pct"]),
                "最新株価日": row["latest_price_date"],
                "最新財務期末": row["latest_financial_period_end"],
                "最終マスター進捗": progress_text(
                    row["master_next_offset"],
                    row["universe_records"],
                    row["master_progress_pct"],
                ),
                "最終詳細進捗": progress_text(
                    row["detail_next_offset"],
                    row["universe_records"],
                    row["detail_progress_pct"],
                ),
            }
        )
    if pd:
        return pd.DataFrame(display_rows)
    return display_rows


def sync_states_dataframe():
    conn = get_connection()
    try:
        states = latest_sync_states(conn, limit=8)
    finally:
        conn.close()
    rows = []
    for state in states:
        result = parse_json_dict(state.get("result_json"))
        rows.append(
            {
                "市場": state.get("market"),
                "ソース": state.get("source"),
                "モード": state.get("mode"),
                "状態": state.get("status"),
                "対象": result_count(result, "selected_records", "target_codes"),
                "処理済み": result_count(result, "processed_codes", "processed_tickers"),
                "次offset": result.get("next_offset"),
                "最終成功": state.get("last_success_at"),
                "最終試行": state.get("last_attempt_at"),
                "メッセージ": state.get("message"),
            }
        )
    if pd:
        return pd.DataFrame(rows)
    return rows


def sync_jobs_dataframe():
    conn = get_connection()
    try:
        jobs = latest_sync_jobs(conn, limit=12)
    finally:
        conn.close()
    rows = []
    for job in jobs:
        result = parse_json_dict(job.get("result_json"))
        rows.append(
            {
                "ID": job.get("id"),
                "種類": job.get("job_type"),
                "市場": job.get("market"),
                "ソース": job.get("source"),
                "モード": job.get("mode"),
                "状態": job.get("status"),
                "対象": result_count(result, "selected_records", "target_codes"),
                "処理済み": result_count(result, "processed_codes", "processed_tickers"),
                "次offset": result.get("next_offset"),
                "開始": job.get("started_at"),
                "終了": job.get("finished_at"),
                "メッセージ": job.get("message"),
            }
        )
    if pd:
        return pd.DataFrame(rows)
    return rows


def active_progress_dataframe():
    conn = get_connection()
    try:
        states = conn.execute(
            """
            SELECT *
            FROM sync_state
            WHERE status = 'running'
            ORDER BY updated_at DESC
            LIMIT 8
            """
        ).fetchall()
    finally:
        conn.close()

    rows = []
    for state in states:
        result = parse_json_dict(state["result_json"])
        done = result.get("processed_dates")
        total = result.get("total_dates")
        rows.append(
            {
                "市場": state["market"],
                "ソース": state["source"],
                "モード": state["mode"],
                "フェーズ": result.get("phase_label") or result.get("phase"),
                "現在日付": result.get("current_date"),
                "進捗": progress_text(done, total, pct_value=(float(done) / float(total) * 100) if done and total else None),
                "今回取得": result.get("inserted"),
                "累計取得": result.get("inserted_total"),
                "会社マスター": result.get("inserted_companies"),
                "メッセージ": state["message"],
                "更新時刻": state["updated_at"],
            }
        )
    if pd:
        return pd.DataFrame(rows)
    return rows


def render_active_progress():
    progress = active_progress_dataframe()
    if len(progress):
        st.markdown("#### 実行中の取得")
        st.dataframe(progress, width="stretch")
    else:
        st.caption("実行中の取得ジョブはありません。")


def dataframe(results):
    rows = []
    for item in results:
        rows.append(
            {
                "コード": item["ticker"],
                "会社名": item["company_name"],
                "市場": item["market"],
                "業種": item["industry"],
                "株価": round(item["latest_price"], 2) if item["latest_price"] else None,
                "時価総額": format_money(item["market_cap"], item.get("currency")),
                "PER": round(item["per"], 2) if item["per"] else None,
                "PBR": round(item["pbr"], 2) if item["pbr"] else None,
                "EV/EBITDA": round(item["ev_ebitda"], 2) if item["ev_ebitda"] else None,
                "ROE": format_pct(item["roe"]),
                "自己資本比率": format_pct(item["equity_ratio"]),
                "FCF利回り": format_pct(item["fcf_yield"]),
                "3か月リターン": format_pct(item["return_3m"]),
                "6か月リターン": format_pct(item["return_6m"]),
                "カタリスト数": item["catalyst_count"],
                "総合スコア": item["total_score"],
                "推奨ラベル": item["recommendation_label"],
            }
        )
    if pd:
        return pd.DataFrame(rows)
    return rows


def to_plain(value):
    if hasattr(value, "keys") and not isinstance(value, dict):
        try:
            return {key: to_plain(value[key]) for key in value.keys()}
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    return value


def trim_value(value, max_items=10):
    value = to_plain(value)
    if isinstance(value, list):
        if len(value) <= max_items:
            return [trim_value(item, max_items=max_items) for item in value]
        return {
            "count": len(value),
            "sample": [trim_value(item, max_items=max_items) for item in value[:max_items]],
        }
    if isinstance(value, dict):
        return {key: trim_value(item, max_items=max_items) for key, item in value.items()}
    return value


def compact_sync_result(result):
    plain = to_plain(result or {})
    if not isinstance(plain, dict):
        return plain
    compact = {key: trim_value(plain[key]) for key in RUN_RESULT_KEYS if key in plain}
    if "target_codes" in plain:
        compact["target_codes"] = trim_value(plain["target_codes"])
    if "batches" in plain:
        batches = plain.get("batches") or []
        compact["batches_count"] = len(batches)
        if batches:
            compact["last_batch"] = trim_value(batches[-1])
    if "results" in plain:
        compact["results"] = trim_value(plain["results"])
    return compact


def market_label(market):
    return {"jp": "日本株", "us": "米国株", "all": "日米"}.get(market, market)


def run_update_step(market, start_date, end_date, batch_limit, max_batches, sleep_sec, progress_callback=None):
    if market == "jp":
        def forward_jp_progress(progress):
            if not progress_callback:
                return
            done = int(progress.get("processed_dates") or 0)
            total = int(progress.get("total_dates") or 0)
            message = (
                "%s: %s/%s日 (%s) / 今回取得 %s件 / 累計 %s件"
                % (
                    progress.get("message") or "日本株データ取得中",
                    done,
                    total,
                    progress.get("current_date") or "-",
                    progress.get("inserted") or 0,
                    progress.get("inserted_total") or 0,
                )
            )
            progress_callback(done, total, message)

        result = sync_jp_screening_source(
            start_date=start_date,
            end_date=end_date,
            sections="all",
            include_prices=True,
            include_financials=True,
            include_dividends=False,
            progress_callback=forward_jp_progress,
        )
        return "success", result

    result = refresh_until_current(
        market="us",
        start_date=start_date,
        end_date=end_date,
        batch_limit=batch_limit,
        max_batches=max_batches,
        sleep_sec=sleep_sec,
        us_exchanges="all",
        include_prices=True,
        include_financials=True,
        include_dividends=False,
        include_events=False,
        include_filings=False,
        resume=True,
        ensure_master=True,
    )
    status = "success" if result.get("stopped_reason") == "complete" else "warning"
    return status, result


def run_market_data_update(target, start_date, end_date, batch_limit, max_batches, sleep_sec, progress_callback=None):
    markets = ["jp", "us"] if target == "all" else [target]
    runs = []
    for index, market in enumerate(markets):
        if progress_callback:
            progress_callback(index, len(markets), "%sデータを取得しています..." % market_label(market))
        try:
            status, result = run_update_step(
                market,
                start_date,
                end_date,
                batch_limit,
                max_batches,
                sleep_sec,
                progress_callback=progress_callback,
            )
        except Exception as exc:
            status = "failed"
            result = {"market": market, "error": str(exc)}
        runs.append({"market": market, "status": status, "result": result})
        if progress_callback:
            progress_callback(index + 1, len(markets), "%sデータ取得を処理しました。" % market_label(market))

    statuses = [run["status"] for run in runs]
    if all(status == "success" for status in statuses):
        overall = "success"
        message = "データ取得が完了しました。"
    elif all(status == "failed" for status in statuses):
        overall = "failed"
        message = "データ取得に失敗しました。"
    else:
        overall = "warning"
        message = "一部のデータ取得が途中停止または失敗しました。"
    return {"market": target, "status": overall, "message": message, "runs": runs}


def run_deep_fetch(market, ticker, start_date, progress_callback=None):
    steps = []
    if market == "jp":
        steps = [
            (
                "J-Quants",
                lambda: sync_market(
                    market="jp",
                    source="jquants",
                    mode="manual",
                    codes=ticker,
                    start_date=start_date,
                    include_prices=True,
                    include_financials=True,
                    include_dividends=True,
                    include_events=True,
                ),
            ),
            (
                "EDINET DB",
                lambda: sync_market(
                    market="jp",
                    source="edinetdb",
                    mode="manual",
                    codes=ticker,
                    include_prices=False,
                    include_financials=True,
                    include_dividends=False,
                    include_events=True,
                ),
            ),
        ]
    else:
        steps = [
            (
                "SEC EDGAR + yfinance",
                lambda: sync_market(
                    market="us",
                    source="edgar",
                    mode="manual",
                    codes=ticker,
                    start_date=start_date,
                    include_prices=True,
                    include_financials=True,
                    include_dividends=True,
                    include_events=True,
                ),
            )
        ]

    runs = []
    for index, (label, func) in enumerate(steps):
        if progress_callback:
            progress_callback(index, len(steps), "%sから深掘り用データを取得しています..." % label)
        try:
            result = func()
            status = "warning" if result.get("warnings") else "success"
        except Exception as exc:
            result = {"source": label, "error": str(exc)}
            status = "failed"
        runs.append({"source": label, "status": status, "result": result})
        if progress_callback:
            progress_callback(index + 1, len(steps), "%sの取得を処理しました。" % label)

    statuses = [run["status"] for run in runs]
    if all(status == "success" for status in statuses):
        overall = "success"
        message = "深掘り用データ取得が完了しました。"
    elif all(status == "failed" for status in statuses):
        overall = "failed"
        message = "深掘り用データ取得に失敗しました。"
    else:
        overall = "warning"
        message = "深掘り用データ取得の一部が途中停止または失敗しました。"
    return {"market": market, "ticker": ticker, "status": overall, "message": message, "runs": runs}


def render_status_message(result):
    if not result:
        return
    if result["status"] == "success":
        st.success(result["message"])
    elif result["status"] == "warning":
        st.warning(result["message"])
    else:
        st.error(result["message"])


def render_run_details(result):
    if not result:
        return
    for run in result.get("runs", []):
        label = market_label(run.get("market")) if run.get("market") else run.get("source", "run")
        with st.expander("%s: %s" % (label, run.get("status")), expanded=run.get("status") != "success"):
            detail = compact_sync_result(run.get("result"))
            if isinstance(detail, dict) and detail.get("next_action"):
                st.info(detail["next_action"])
            st.json(detail)


def render_progress_summary():
    rows = coverage_rows()
    if not rows:
        st.info("まだデータ取得履歴がありません。")
        return

    cols = st.columns(len(rows))
    for col, row in zip(cols, rows):
        with col:
            st.metric(row["market_label"], f"{int(row['company_count'] or 0):,}社")
            st.progress(clamp_progress(row["major_data_coverage_pct"]))
            st.caption("主要データ: %s" % pct_text(row["major_data_coverage_pct"]))
            st.caption("株価 %s / 財務 %s" % (pct_text(row["price_coverage_pct"]), pct_text(row["financial_coverage_pct"])))

    coverage = coverage_dataframe()
    if len(coverage):
        st.dataframe(coverage, width="stretch")


def rows_dataframe(rows):
    if pd:
        return pd.DataFrame(rows)
    return rows


def render_terms_table(terms):
    rows = term_rows(terms)
    if pd:
        st.dataframe(pd.DataFrame(rows), width="stretch")
    else:
        st.table(rows)


def render_term_help_panel(key_prefix, terms, expanded=False):
    with st.expander("用語ヘルプ", expanded=expanded):
        term = st.selectbox("用語", terms or GLOSSARY_ORDER, key="%s_term_help" % key_prefix)
        st.info(term_help(term))
        st.markdown("#### 推奨ラベル")
        render_terms_table(RECOMMENDATION_TERMS)
        if st.checkbox("主要用語一覧を表示", value=False, key="%s_terms_all" % key_prefix):
            render_terms_table(terms or GLOSSARY_ORDER)


def filter_field(key):
    for field in NUMERIC_FILTERS:
        if field["key"] == key:
            return field
    return None


def filter_label(key):
    field = filter_field(key)
    if field:
        return field["label"]
    for bool_key, label, _term in BOOLEAN_FILTERS:
        if bool_key == key:
            return label
    return key


def format_filter_value(key, value):
    if isinstance(value, bool):
        return "はい" if value else "いいえ"
    if value is None:
        return "未指定"
    if key in ("min_market_cap", "min_average_volume"):
        return f"{int(value):,}"
    if key in ("min_roe", "min_operating_margin", "min_equity_ratio", "max_drawdown_from_52w_high"):
        return "%.1f%%" % float(value)
    return "%.2f" % float(value)


def filter_summary_rows(filters):
    rows = []
    for field in NUMERIC_FILTERS:
        key = field["key"]
        if filters.get(key) is not None:
            rows.append({"条件": field["label"], "値": format_filter_value(key, filters[key])})
    for key, label, _term in BOOLEAN_FILTERS:
        if filters.get(key) is not None:
            rows.append({"条件": label, "値": format_filter_value(key, filters[key])})
    return rows


def render_filter_summary(filters):
    rows = filter_summary_rows(filters)
    if rows:
        st.dataframe(rows_dataframe(rows), width="stretch")
    else:
        st.caption("条件は未指定です。")


def build_effective_filters(preset_config, overrides, replace_filters):
    filters = {} if replace_filters else dict(preset_config.get("filters", {}))
    filters.update({key: value for key, value in (overrides or {}).items() if value is not None})
    return filters


def render_filter_controls(preset_config):
    base_filters = dict(preset_config.get("filters", {}))
    st.caption(preset_config.get("description", ""))

    with st.expander("スクリーニング条件を設定", expanded=False):
        st.markdown("#### 現在のプリセット条件")
        render_filter_summary(base_filters)

        use_custom = st.checkbox("自分で条件を設定する", value=False, key="use_custom_filters")
        overrides = {}
        replace_filters = False
        if use_custom:
            mode = st.radio(
                "条件モード",
                ["プリセット条件に追加/上書き", "手動条件だけで絞る"],
                horizontal=True,
                key="custom_filter_mode",
            )
            replace_filters = mode == "手動条件だけで絞る"

            st.markdown("#### 数値条件")
            for row_index in range(0, len(NUMERIC_FILTERS), 3):
                cols = st.columns(3)
                for col, field in zip(cols, NUMERIC_FILTERS[row_index : row_index + 3]):
                    key = field["key"]
                    with col:
                        enabled = st.checkbox(
                            "%sを使う" % field["label"],
                            value=key in base_filters,
                            key="filter_enabled_%s" % key,
                            help=term_help(field["term"]),
                        )
                        value = base_filters.get(key, field["default"])
                        if enabled:
                            overrides[key] = st.number_input(
                                field["label"],
                                value=float(value),
                                min_value=float(field["min_value"]),
                                step=float(field["step"]),
                                key="filter_value_%s" % key,
                                help=term_help(field["term"]),
                            )

            st.markdown("#### 除外条件")
            bool_cols = st.columns(3)
            for col, (key, label, term) in zip(bool_cols, BOOLEAN_FILTERS):
                with col:
                    overrides[key] = st.checkbox(
                        label,
                        value=bool(base_filters.get(key, False)),
                        key="filter_value_%s" % key,
                        help=term_help(term),
                    )

        effective_filters = build_effective_filters(preset_config, overrides, replace_filters)
        st.markdown("#### 実行時に使う条件")
        render_filter_summary(effective_filters)
        return overrides, replace_filters, effective_filters

    return {}, False, base_filters


def render_fetch_panel():
    st.subheader("全銘柄データ取得")
    st.caption("日本株はJ-Quantsを日付単位で取得し、米国株はSECマスターとyfinanceの複数ticker取得を使います。")

    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        start = c1.date_input("取得開始日", value=date.today() - timedelta(days=DEFAULT_START_DAYS), key="fetch_start")
        end_enabled = c2.checkbox("終了日を指定", value=False, key="fetch_end_enabled")
        end = c2.date_input("取得終了日", value=date.today(), key="fetch_end") if end_enabled else None
        batch_limit = c3.number_input("米国株バッチ件数", min_value=1, max_value=500, value=50, step=10)
        max_batches = c4.number_input("米国株最大バッチ数", min_value=1, max_value=500, value=30, step=5)
        sleep_sec = st.number_input("米国株バッチ間隔(秒)", min_value=0.0, max_value=120.0, value=0.0, step=1.0)

    b1, b2, b3 = st.columns(3)
    target = None
    if b1.button("日本株を日付単位で取得", type="primary", width="stretch"):
        target = "jp"
    if b2.button("米国株をまとめて取得", width="stretch"):
        target = "us"
    if b3.button("日米まとめて取得", width="stretch"):
        target = "all"

    if target:
        progress_bar = st.progress(0.0)
        status_text = st.empty()

        def update_progress(done, total, message):
            progress_bar.progress(done / total if total else 0.0)
            status_text.info(message)

        result = run_market_data_update(
            target,
            start.isoformat(),
            end.isoformat() if end else None,
            int(batch_limit),
            int(max_batches),
            float(sleep_sec),
            progress_callback=update_progress,
        )
        st.session_state.fetch_result = result
        progress_bar.progress(1.0)
        status_text.empty()

    render_status_message(st.session_state.fetch_result)
    render_run_details(st.session_state.fetch_result)

    render_active_progress()

    st.markdown("#### 現在の進捗")
    render_progress_summary()


def run_screening(market, preset, overrides=None, replace_filters=False, effective_filters=None):
    results, run_id = screen_companies(
        preset_name=preset,
        market=market,
        overrides=overrides,
        save=True,
        replace_filters=replace_filters,
    )
    st.session_state.screening = {
        "market": market,
        "preset": preset,
        "results": results,
        "run_id": run_id,
        "overrides": overrides or {},
        "replace_filters": replace_filters,
        "effective_filters": effective_filters or {},
    }
    st.session_state.deep_ticker = None
    st.session_state.deep_fetch_result = None


def render_screening_panel(presets):
    st.subheader("スクリーニング")
    preset = st.selectbox("プリセット", list(presets.keys()), help=term_help("プリセット"), key="screening_preset")
    overrides, replace_filters, effective_filters = render_filter_controls(presets[preset])
    render_term_help_panel("screening", SCREENING_HELP_TERMS)

    c1, c2 = st.columns(2)
    if c1.button("日本株スクリーニング", type="primary", width="stretch"):
        with st.spinner("日本株をスクリーニングしています..."):
            run_screening("jp", preset, overrides, replace_filters, effective_filters)
    if c2.button("米国株スクリーニング", width="stretch"):
        with st.spinner("米国株をスクリーニングしています..."):
            run_screening("us", preset, overrides, replace_filters, effective_filters)

    screening = st.session_state.screening
    if not screening:
        st.info("日本株または米国株のスクリーニングを実行してください。")
        return

    results = screening["results"]
    strong = len([item for item in results if item["recommendation_label"] == "Strong Candidate"])
    candidate = len([item for item in results if item["recommendation_label"] == "Candidate"])
    watch = len([item for item in results if item["recommendation_label"] == "Watch"])

    st.success("%sスクリーニングが完了しました。" % market_label(screening["market"]))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("総候補数", len(results))
    c2.metric("Strong Candidate", strong, help=term_help("Strong Candidate"))
    c3.metric("Candidate", candidate, help=term_help("Candidate"))
    c4.metric("Watch", watch, help=term_help("Watch"))
    with st.expander("今回適用した条件", expanded=False):
        mode = "手動条件だけ" if screening.get("replace_filters") else "プリセット条件 + 手動条件"
        st.caption("条件モード: %s" % mode)
        render_filter_summary(screening.get("effective_filters") or {})

    if not results:
        st.warning("条件に一致する候補がありません。")
        return

    df = dataframe(results)
    st.dataframe(df, width="stretch")
    csv_path = export_results(results, screening["preset"], "csv")
    st.download_button("CSV出力", csv_path.read_bytes(), file_name=csv_path.name, mime="text/csv")

    st.markdown("#### 深掘り対象")
    ticker_options = [item["ticker"] for item in results]
    c1, c2 = st.columns([2, 1])
    selected = c1.selectbox("銘柄", ticker_options, key="screening_deep_candidate")
    if c2.button("選択銘柄を深掘り対象にする", width="stretch"):
        st.session_state.deep_ticker = selected
        st.session_state.deep_ticker_select = selected
        st.success("深掘りタブでデータ取得と分析を実行できます。")


def parse_risk_flags(value):
    if not value:
        return ""
    try:
        flags = json.loads(value)
    except (TypeError, ValueError):
        return str(value)
    return ", ".join(flags)


def render_detail(ticker, preset):
    try:
        metrics, explanation = explain_ticker(ticker, preset_name=preset)
    except Exception as exc:
        st.error(str(exc))
        return

    st.subheader("%s %s" % (metrics["ticker"], metrics["company_name"]))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("総合スコア", metrics["total_score"], help=term_help("総合スコア"))
    c2.metric("ラベル", metrics["recommendation_label"], help=term_help(metrics["recommendation_label"]))
    c3.metric("PER", format_ratio(metrics["per"]), help=term_help("PER"))
    c4.metric("PBR", format_ratio(metrics["pbr"]), help=term_help("PBR"))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ROE", format_pct(metrics["roe"]), help=term_help("ROE"))
    c2.metric("自己資本比率", format_pct(metrics["equity_ratio"]), help=term_help("自己資本比率"))
    c3.metric("営業利益率", format_pct(metrics["operating_margin"]), help=term_help("営業利益率"))
    c4.metric("カタリスト数", metrics["catalyst_count"], help=term_help("カタリスト"))

    st.markdown("#### 分析コメント")
    st.info(explanation)

    st.markdown("#### スコア内訳")
    score_rows = [
        {"項目": "割安度", "スコア": metrics["valuation_score"]},
        {"項目": "品質", "スコア": metrics["quality_score"]},
        {"項目": "安全性", "スコア": metrics["safety_score"]},
        {"項目": "モメンタム", "スコア": metrics["momentum_score"]},
        {"項目": "カタリスト", "スコア": metrics["catalyst_score"]},
        {"項目": "リスク", "スコア": metrics["risk_score"]},
    ]
    if pd:
        score_df = pd.DataFrame(score_rows)
        if px:
            st.plotly_chart(px.bar(score_df, x="項目", y="スコア", range_y=[0, 100]), width="stretch")
        else:
            st.table(score_df)
    else:
        st.table(score_rows)

    st.markdown("#### 直近カタリスト")
    if metrics["events"]:
        st.table(
            [
                {
                    "日付": event["event_date"],
                    "種別": event["event_type"],
                    "タイトル": event["title"],
                    "説明": event["description"],
                }
                for event in metrics["events"]
            ]
        )
    else:
        st.write("直近カタリストはありません。")

    st.markdown("#### 開示")
    filings = metrics.get("filings", [])
    if filings:
        st.table(
            [
                {
                    "提出日": filing["filing_date"],
                    "種別": filing["document_type"],
                    "タイトル": filing["title"],
                    "ソース": filing["source"],
                }
                for filing in filings
            ]
        )
    else:
        st.write("取得済みの開示一覧はまだありません。")

    st.markdown("#### 有報テキストリスク語")
    text_blocks = metrics.get("text_blocks", [])
    risky_blocks = [block for block in text_blocks if parse_risk_flags(block.get("risk_flags_json"))]
    if risky_blocks:
        for block in risky_blocks:
            flags = parse_risk_flags(block.get("risk_flags_json"))
            st.warning("%s / %s / %s" % (block.get("fiscal_year") or "-", block.get("title") or "-", flags))
            st.write(block.get("text_excerpt") or "")
    elif text_blocks:
        st.write("取得済みの有報テキストから主要なリスク語は検出されていません。")
    else:
        st.write("有報テキストはまだありません。")


def render_deep_dive_panel():
    st.subheader("深掘り分析")
    render_term_help_panel("deep", DEEP_HELP_TERMS)
    screening = st.session_state.screening
    if not screening or not screening["results"]:
        st.info("先にスクリーニングを実行すると、深掘り対象を選択できます。")
        return

    options = [item["ticker"] for item in screening["results"]]
    current = st.session_state.deep_ticker
    index = options.index(current) if current in options else 0
    ticker = st.selectbox("深掘り対象", options, index=index, key="deep_ticker_select")
    start = st.date_input(
        "深掘り用データ取得開始日",
        value=date.today() - timedelta(days=DEFAULT_START_DAYS),
        key="deep_start",
    )

    c1, c2 = st.columns(2)
    if c1.button("深掘り用データを取得", type="primary", width="stretch"):
        progress_bar = st.progress(0.0)
        status_text = st.empty()

        def update_progress(done, total, message):
            progress_bar.progress(done / total if total else 0.0)
            status_text.info(message)

        result = run_deep_fetch(
            screening["market"],
            ticker,
            start.isoformat(),
            progress_callback=update_progress,
        )
        st.session_state.deep_fetch_result = result
        st.session_state.deep_ticker = ticker
        progress_bar.progress(1.0)
        status_text.empty()

    if c2.button("深掘り分析を表示", width="stretch"):
        st.session_state.deep_ticker = ticker

    render_status_message(st.session_state.deep_fetch_result)
    render_run_details(st.session_state.deep_fetch_result)

    if st.session_state.deep_ticker:
        render_detail(st.session_state.deep_ticker, screening["preset"])


def render_history_panel():
    st.subheader("取得進捗と履歴")
    render_active_progress()
    render_progress_summary()

    states = sync_states_dataframe()
    st.markdown("#### 最終更新状態")
    if len(states):
        st.dataframe(states, width="stretch")
    else:
        st.write("更新履歴はまだありません。")

    jobs = sync_jobs_dataframe()
    st.markdown("#### 同期ジョブ履歴")
    if len(jobs):
        st.dataframe(jobs, width="stretch")
    else:
        st.write("同期ジョブ履歴はまだありません。")


def main():
    ensure_data()
    init_session_state()
    presets = load_presets()

    st.title("Value Catalyst Screener")
    st.caption(disclaimer())

    tab_fetch, tab_screen, tab_deep, tab_history = st.tabs(["データ取得", "スクリーニング", "深掘り", "進捗"])
    with tab_fetch:
        render_fetch_panel()
    with tab_screen:
        render_screening_panel(presets)
    with tab_deep:
        render_deep_dive_panel()
    with tab_history:
        render_history_panel()


if __name__ == "__main__":
    main()
