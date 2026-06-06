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
from src.ingestion.sync_all import sync_edgar_bulk_source, sync_jp_bulk_source, sync_market
from src.ingestion.sync_state import latest_sync_jobs, latest_sync_states
from src.nlp.report_generator import export_results
from src.ui.components import disclaimer, format_money, format_pct, format_ratio
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


def render_manual_update_panel(market):
    st.header("データ更新")
    default_codes = "AAPL" if market == "us" else "7203"
    codes = st.text_input("銘柄コード / ティッカー", value=default_codes, key="update_codes_%s" % market)
    start = st.date_input("株価取得開始日", value=date.today() - timedelta(days=420))
    update_jquants = st.button("J-Quants手動更新", type="secondary", disabled=market == "us")
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

    if st.button("EDINET DB補完更新", disabled=market == "us"):
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

    if st.button("SEC EDGAR更新", disabled=market == "jp"):
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

    if st.button("サンプルデータ更新"):
        result = sync_market(market=market, source="sample", mode="manual")
        st.success(result.get("message", "サンプルデータを更新しました。"))
    return first_code(codes)


def render_bulk_update_panel(market):
    st.header("一括取り込み")
    bulk_limit = st.number_input("一回の処理件数", min_value=1, max_value=1000, value=50, step=10)
    bulk_offset = st.number_input("開始offset", min_value=0, value=0, step=10)
    master_only = st.checkbox("会社マスターのみ", value=True)
    resume = st.checkbox("取得済みをスキップ", value=True)
    bulk_start = st.date_input("一括取得開始日", value=date.today() - timedelta(days=420), key="bulk_start")

    if market in ("jp", "all"):
        sections = st.text_input("日本株市場区分", value="Prime,Standard,Growth")
        if st.button("日本株一括取り込み"):
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
        exchanges = st.text_input("米国株取引所", value="Nasdaq,NYSE")
        if st.button("米国株一括取り込み"):
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
    c1.metric("総合スコア", metrics["total_score"])
    c2.metric("ラベル", metrics["recommendation_label"])
    c3.metric("PER", format_ratio(metrics["per"]))
    c4.metric("PBR", format_ratio(metrics["pbr"]))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ROE", format_pct(metrics["roe"]))
    c2.metric("自己資本比率", format_pct(metrics["equity_ratio"]))
    c3.metric("営業利益率", format_pct(metrics["operating_margin"]))
    c4.metric("カタリスト数", metrics["catalyst_count"])

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
            st.plotly_chart(px.bar(score_df, x="項目", y="スコア", range_y=[0, 100]), use_container_width=True)
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
        market_label = st.radio("市場", ["日本株", "米国株", "両方"], index=0)
        market = {"日本株": "jp", "米国株": "us", "両方": "all"}[market_label]
        preset = st.selectbox("プリセット", list(presets.keys()))
        max_per = st.number_input("PER上限", min_value=0.0, value=float(presets[preset].get("filters", {}).get("max_per", 18)))
        max_pbr = st.number_input("PBR上限", min_value=0.0, value=float(presets[preset].get("filters", {}).get("max_pbr", 1.5)))
        min_equity_ratio = st.number_input(
            "自己資本比率下限(%)",
            min_value=0.0,
            value=float(presets[preset].get("filters", {}).get("min_equity_ratio", 30)),
        )
        run = st.button("スクリーニング実行", type="primary")
        detail_hint = render_manual_update_panel(market)
        render_bulk_update_panel(market)

    with st.expander("更新状態", expanded=True):
        states = sync_states_dataframe()
        if len(states):
            st.markdown("##### 最終更新状態")
            st.dataframe(states, use_container_width=True)
        else:
            st.write("更新履歴はまだありません。")
        jobs = sync_jobs_dataframe()
        if len(jobs):
            st.markdown("##### 同期ジョブ履歴")
            st.dataframe(jobs, use_container_width=True)

    overrides = {"max_per": max_per, "max_pbr": max_pbr, "min_equity_ratio": min_equity_ratio}
    results, run_id = screen_companies(preset_name=preset, market=market, overrides=overrides, save=run)
    strong = len([r for r in results if r["recommendation_label"] == "Strong Candidate"])
    candidate = len([r for r in results if r["recommendation_label"] == "Candidate"])
    watch = len([r for r in results if r["recommendation_label"] == "Watch"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("総候補数", len(results))
    c2.metric("Strong Candidate", strong)
    c3.metric("Candidate", candidate)
    c4.metric("Watch", watch)

    df = dataframe(results)
    st.dataframe(df, use_container_width=True)

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
