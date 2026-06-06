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
from src.ingestion.refresh import DEFAULT_JP_SECTIONS, DEFAULT_US_EXCHANGES, refresh_until_current
from src.ingestion.sync_all import sync_edgar_bulk_source, sync_jp_bulk_source, sync_market
from src.ingestion.sync_state import latest_sync_jobs, latest_sync_states
from src.nlp.report_generator import export_results
from src.ui.components import disclaimer, format_money, format_pct, format_ratio
from src.ui.glossary import GLOSSARY_ORDER, term_help, term_rows
from src.utils.file_utils import load_presets


st.set_page_config(page_title="Value Catalyst Screener", layout="wide")


def ensure_data():
    init_db()
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM company_master").fetchone()["c"]
    finally:
        conn.close()
    if count == 0:
        sync_market(market="all", use_sample=True)


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
                "スキップ": result.get("skipped_existing"),
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
                "スキップ": result.get("skipped_existing"),
                "次offset": result.get("next_offset"),
                "開始": job.get("started_at"),
                "終了": job.get("finished_at"),
                "メッセージ": job.get("message"),
            }
        )
    if pd:
        return pd.DataFrame(rows)
    return rows


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


def coverage_dataframe():
    conn = get_connection()
    try:
        rows = data_coverage_rows(conn)
    finally:
        conn.close()

    display_rows = []
    for row in rows:
        display_rows.append(
            {
                "市場": row["market_label"],
                "会社マスター処理進捗": progress_text(
                    row["master_next_offset"],
                    row["universe_records"],
                    row["master_progress_pct"],
                ),
                "DB会社数": progress_text(
                    row["company_count"],
                    row["universe_records"],
                    row["master_coverage_pct"],
                ),
                "詳細処理進捗": progress_text(
                    row["detail_next_offset"],
                    row["universe_records"],
                    row["detail_progress_pct"],
                ),
                "主要データ取り込み率": pct_text(row["major_data_coverage_pct"]),
                "株価取得": count_with_pct(row["price_company_count"], row["price_coverage_pct"]),
                "財務取得": count_with_pct(row["financial_company_count"], row["financial_coverage_pct"]),
                "開示取得": count_with_pct(row["filing_company_count"], row["filing_coverage_pct"]),
                "配当等取得": count_with_pct(row["action_company_count"], row["action_coverage_pct"]),
                "主要データ最新化率": pct_text(row["major_freshness_pct"]),
                "株価最新化": count_with_pct(row["fresh_price_company_count"], row["price_freshness_pct"]),
                "財務最新化": count_with_pct(
                    row["fresh_financial_company_count"],
                    row["financial_freshness_pct"],
                ),
                "最新株価日": row["latest_price_date"],
                "最新財務期末": row["latest_financial_period_end"],
                "最新開示日": row["latest_filing_date"],
            }
        )
    if pd:
        return pd.DataFrame(display_rows)
    return display_rows


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
    if result.get(scalar_key) is not None:
        return result.get(scalar_key)
    value = result.get(list_key)
    if isinstance(value, list):
        return len(value)
    return None


def first_code(value):
    if not value:
        return ""
    return str(value).replace(" ", "").split(",")[0].strip().upper()


def render_glossary_panel():
    with st.expander("用語ヘルプ", expanded=False):
        term = st.selectbox("調べる用語", GLOSSARY_ORDER, key="glossary_term")
        st.info(term_help(term))
        if st.checkbox("用語一覧を表示", value=False):
            rows = term_rows()
            if pd:
                st.dataframe(pd.DataFrame(rows), width="stretch")
            else:
                st.table(rows)


def render_manual_update_panel(market):
    st.header("データ更新")
    default_codes = "AAPL" if market == "us" else "7203"
    codes = st.text_input(
        "銘柄コード / ティッカー",
        value=default_codes,
        key="update_codes_%s" % market,
        help="日本株は証券コード、米国株はティッカーを指定します。",
    )
    start = st.date_input(
        "株価取得開始日",
        value=date.today() - timedelta(days=420),
        help="株価データをどの日付から取得するかです。",
    )
    update_jquants = st.button(
        "J-Quants手動更新",
        type="secondary",
        disabled=market == "us",
        help=term_help("J-Quants"),
    )
    if update_jquants:
        with st.spinner("J-Quantsから取得しています..."):
            try:
                result = sync_market(
                    market="jp",
                    source="jquants",
                    mode="manual",
                    codes=codes,
                    start_date=start.isoformat(),
                    include_prices=True,
                    include_financials=True,
                    include_dividends=True,
                    include_events=True,
                )
                st.success(result.get("message", "更新しました。"))
                if result.get("warnings"):
                    st.warning(" / ".join(result["warnings"]))
                st.json(result)
            except Exception as exc:
                st.error(str(exc))

    if st.button("EDINET DB補完更新", disabled=market == "us", help=term_help("EDINET")):
        with st.spinner("EDINET DBから有報・年度財務を取得しています..."):
            try:
                result = sync_market(
                    market="jp",
                    source="edinetdb",
                    mode="manual",
                    codes=codes,
                    include_prices=False,
                    include_financials=True,
                    include_dividends=False,
                    include_events=True,
                )
                st.success(result.get("message", "EDINET DB補完更新が完了しました。"))
                if result.get("warnings"):
                    st.warning(" / ".join(result["warnings"]))
                st.json(result)
            except Exception as exc:
                st.error(str(exc))

    if st.button("SEC EDGAR更新", disabled=market == "jp", help=term_help("EDGAR")):
        with st.spinner("SEC EDGARと価格APIから取得しています..."):
            try:
                result = sync_market(
                    market="us",
                    source="edgar",
                    mode="manual",
                    codes=codes,
                    start_date=start.isoformat(),
                    include_prices=True,
                    include_financials=True,
                    include_dividends=True,
                    include_events=True,
                )
                st.success(result.get("message", "SEC EDGAR更新が完了しました。"))
                if result.get("warnings"):
                    st.warning(" / ".join(result["warnings"]))
                st.json(result)
            except Exception as exc:
                st.error(str(exc))

    if st.button("サンプルデータ更新", help="APIキーがなくても動作確認できるサンプルデータを投入します。"):
        result = sync_market(market=market, source="sample", mode="manual")
        st.success(result.get("message", "サンプルデータを更新しました。"))
    return first_code(codes)


def render_bulk_update_panel(market):
    st.header("一括取り込み")
    bulk_limit = st.number_input(
        "一回の処理件数",
        min_value=1,
        max_value=1000,
        value=50,
        step=10,
        help="1回のAPI実行で処理する銘柄数です。429が出る場合は小さくします。",
    )
    bulk_offset = st.number_input(
        "開始offset",
        min_value=0,
        value=0,
        step=10,
        help=term_help("next_offset"),
    )
    master_only = st.checkbox("会社マスターのみ", value=True, help=term_help("会社マスター"))
    resume = st.checkbox("取得済みをスキップ", value=True, help="既に必要データがある銘柄を飛ばして、未取得分を優先します。")
    bulk_start = st.date_input(
        "一括取得開始日",
        value=date.today() - timedelta(days=420),
        key="bulk_start",
        help="詳細データ取得時に、株価をどの日付から取得するかです。",
    )
    sections = None
    exchanges = None

    if market in ("jp", "all"):
        sections = st.text_input("日本株市場区分", value=DEFAULT_JP_SECTIONS, help="Prime、Standard、Growthなどをカンマ区切りで指定します。")
        if st.button("日本株一括取り込み", help="J-Quantsの銘柄一覧から、日本株をまとめて取り込みます。"):
            with st.spinner("J-Quants銘柄一覧から日本株を一括取り込み中..."):
                try:
                    result = sync_jp_bulk_source(
                        start_date=bulk_start.isoformat(),
                        sections=sections,
                        offset=int(bulk_offset),
                        limit=int(bulk_limit),
                        include_prices=not master_only,
                        include_financials=not master_only,
                        include_dividends=not master_only,
                        include_events=not master_only,
                        resume=resume,
                    )
                    st.success(result.get("message", "日本株一括取り込みが完了しました。"))
                    if result.get("rate_limited"):
                        st.warning("APIレート制限を検出しました。next_offsetから再開してください。")
                    if result.get("warnings"):
                        st.warning(" / ".join(result["warnings"][:5]))
                    st.json(result)
                except Exception as exc:
                    st.error(str(exc))

    if market in ("us", "all"):
        exchanges = st.text_input("米国株取引所", value=DEFAULT_US_EXCHANGES, help="Nasdaq、NYSEなどをカンマ区切りで指定します。")
        if st.button("米国株一括取り込み", help="SECのticker/CIK一覧から、米国株をまとめて取り込みます。"):
            with st.spinner("SEC ticker/CIK一覧から米国株を一括取り込み中..."):
                try:
                    result = sync_edgar_bulk_source(
                        start_date=bulk_start.isoformat(),
                        exchanges=exchanges,
                        offset=int(bulk_offset),
                        limit=int(bulk_limit),
                        include_prices=not master_only,
                        include_financials=not master_only,
                        include_filings=not master_only,
                        include_dividends=not master_only,
                        resume=resume,
                    )
                    st.success(result.get("message", "米国株一括取り込みが完了しました。"))
                    if result.get("warnings"):
                        st.warning(" / ".join(result["warnings"][:5]))
                    st.json(result)
                except Exception as exc:
                    st.error(str(exc))

    st.markdown("##### 最新化ジョブ")
    refresh_limit = st.number_input(
        "最新化バッチ件数",
        min_value=1,
        max_value=200,
        value=10,
        step=5,
        help="最新化ジョブで1回に処理する銘柄数です。",
    )
    refresh_batches = st.number_input(
        "最大バッチ数",
        min_value=1,
        max_value=100,
        value=5,
        step=1,
        help="この回で最大何バッチまで進めるかです。途中で止めても次回続きから再開できます。",
    )
    refresh_sleep = st.number_input(
        "バッチ間隔(秒)",
        min_value=0.0,
        max_value=60.0,
        value=0.0,
        step=1.0,
        help="API制限を避けるため、バッチ間に待つ秒数です。",
    )
    if st.button("最新化するまで実行", help=term_help("詳細処理進捗")):
        with st.spinner("進捗を確認しながら最新化バッチを実行しています..."):
            try:
                result = refresh_until_current(
                    market=market,
                    start_date=bulk_start.isoformat(),
                    batch_limit=int(refresh_limit),
                    max_batches=int(refresh_batches),
                    sleep_sec=float(refresh_sleep),
                    jp_sections=sections or DEFAULT_JP_SECTIONS,
                    us_exchanges=exchanges or DEFAULT_US_EXCHANGES,
                    resume=resume,
                )
                if result.get("stopped_reason") == "complete":
                    st.success(result.get("next_action", "最新化が完了しました。"))
                else:
                    st.warning(result.get("next_action", "最新化ジョブは途中で停止しました。"))
                st.json(result)
            except Exception as exc:
                st.error(str(exc))


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

    st.markdown("#### AI風の説明文")
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

    st.markdown("#### EDINET DB 有報・開示")
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
        st.write("EDINET DB由来の開示一覧はまだありません。")

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
        st.write("EDINET DB由来の有報テキストはまだありません。")


def main():
    ensure_data()
    presets = load_presets()
    st.title("Value Catalyst Screener")
    st.caption(disclaimer())

    with st.sidebar:
        st.header("条件")
        market_label = st.radio("市場", ["日本株", "米国株", "両方"], index=0, help="分析対象の市場を選びます。")
        market = {"日本株": "jp", "米国株": "us", "両方": "all"}[market_label]
        preset = st.selectbox("プリセット", list(presets.keys()), help=term_help("プリセット"))
        max_per = st.number_input(
            "PER上限",
            min_value=0.0,
            value=float(presets[preset].get("filters", {}).get("max_per", 18)),
            help=term_help("PER"),
        )
        max_pbr = st.number_input(
            "PBR上限",
            min_value=0.0,
            value=float(presets[preset].get("filters", {}).get("max_pbr", 1.5)),
            help=term_help("PBR"),
        )
        min_equity_ratio = st.number_input(
            "自己資本比率下限(%)",
            min_value=0.0,
            value=float(presets[preset].get("filters", {}).get("min_equity_ratio", 30)),
            help=term_help("自己資本比率"),
        )
        run = st.button("スクリーニング実行", type="primary", help="現在の条件で候補銘柄を抽出し、結果を保存します。")
        render_glossary_panel()
        detail_hint = render_manual_update_panel(market)
        render_bulk_update_panel(market)

    with st.expander("更新状態", expanded=True):
        coverage = coverage_dataframe()
        if len(coverage):
            st.markdown("##### データ取り込み率・最新化率")
            st.caption(
                "会社マスター処理進捗と詳細処理進捗は、それぞれのnext_offsetが直近一括同期の全体件数のどこまで進んだかを示します。"
                "最新化率は株価が直近10日以内、財務が直近18か月以内の期末データを持つ会社の割合です。"
            )
            st.dataframe(coverage, width="stretch")
        states = sync_states_dataframe()
        if len(states):
            st.markdown("##### 最終更新状態")
            st.dataframe(states, width="stretch")
        else:
            st.write("更新履歴はまだありません。")
        jobs = sync_jobs_dataframe()
        if len(jobs):
            st.markdown("##### 同期ジョブ履歴")
            st.dataframe(jobs, width="stretch")

    overrides = {"max_per": max_per, "max_pbr": max_pbr, "min_equity_ratio": min_equity_ratio}
    results, run_id = screen_companies(preset_name=preset, market=market, overrides=overrides, save=run)
    strong = len([r for r in results if r["recommendation_label"] == "Strong Candidate"])
    candidate = len([r for r in results if r["recommendation_label"] == "Candidate"])
    watch = len([r for r in results if r["recommendation_label"] == "Watch"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("総候補数", len(results), help="現在の条件に残った候補銘柄の数です。")
    c2.metric("Strong Candidate", strong, help=term_help("Strong Candidate"))
    c3.metric("Candidate", candidate, help=term_help("Candidate"))
    c4.metric("Watch", watch, help=term_help("Watch"))

    df = dataframe(results)
    st.dataframe(df, width="stretch")

    if results:
        csv_path = export_results(results, preset, "csv")
        st.download_button("CSV出力", csv_path.read_bytes(), file_name=csv_path.name, mime="text/csv")
        ticker_options = [item["ticker"] for item in results]
        selected_index = ticker_options.index(detail_hint) if detail_hint in ticker_options else 0
        selected = st.selectbox("詳細分析", ticker_options, index=selected_index)
        render_detail(selected, preset)
    else:
        st.warning("条件に一致する候補がありません。")


if __name__ == "__main__":
    main()
