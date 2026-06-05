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
from src.ingestion.sync_all import sync_market
from src.ingestion.sync_state import latest_sync_states
from src.nlp.report_generator import export_results
from src.ui.components import disclaimer, format_jpy, format_pct, format_ratio
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
        sync_market(market="jp", use_sample=True)


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
                "時価総額": format_jpy(item["market_cap"]),
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
        rows.append(
            {
                "市場": state.get("market"),
                "ソース": state.get("source"),
                "モード": state.get("mode"),
                "状態": state.get("status"),
                "最終成功": state.get("last_success_at"),
                "最終試行": state.get("last_attempt_at"),
                "メッセージ": state.get("message"),
            }
        )
    if pd:
        return pd.DataFrame(rows)
    return rows


def render_manual_update_panel():
    st.header("データ更新")
    codes = st.text_input("銘柄コード", value="7203")
    start = st.date_input("株価取得開始日", value=date.today() - timedelta(days=420))
    update_jquants = st.button("J-Quants手動更新", type="secondary")
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

    if st.button("サンプルデータ更新"):
        result = sync_market(market="jp", source="sample", mode="manual")
        st.success(result.get("message", "サンプルデータを更新しました。"))


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
        render_manual_update_panel()

    with st.expander("更新状態", expanded=False):
        states = sync_states_dataframe()
        if len(states):
            st.dataframe(states, use_container_width=True)
        else:
            st.write("更新履歴はまだありません。")

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
        selected = st.selectbox("詳細分析", ticker_options)
        render_detail(selected, preset)
    else:
        st.warning("条件に一致する候補がありません。")


if __name__ == "__main__":
    main()
