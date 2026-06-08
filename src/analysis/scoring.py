import uuid
from datetime import date, timedelta

from src.analysis.catalyst import catalyst_score
from src.analysis.metrics import percentage, quality_score, safe_div, safety_score
from src.analysis.momentum import momentum_score, return_between
from src.analysis.risk import risk_score
from src.analysis.valuation import valuation_score
from src.db.session import get_connection
from src.utils.file_utils import DISCLAIMER, load_presets


def recommendation_label(total_score):
    if total_score >= 85:
        return "Strong Candidate"
    if total_score >= 70:
        return "Candidate"
    if total_score >= 55:
        return "Watch"
    if total_score >= 40:
        return "Weak"
    return "Exclude"


def latest_financial(conn, company_id):
    return conn.execute(
        """
        SELECT *
        FROM financial_facts
        WHERE company_id = ?
        ORDER BY period_end DESC, fiscal_year DESC
        LIMIT 1
        """,
        (company_id,),
    ).fetchone()


def previous_financial(conn, company_id, latest_id):
    return conn.execute(
        """
        SELECT *
        FROM financial_facts
        WHERE company_id = ? AND id <> ?
        ORDER BY period_end DESC, fiscal_year DESC
        LIMIT 1
        """,
        (company_id, latest_id),
    ).fetchone()


def latest_price(conn, company_id):
    return conn.execute(
        """
        SELECT *
        FROM prices
        WHERE company_id = ?
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (company_id,),
    ).fetchone()


def price_on_or_before(conn, company_id, target_date):
    return conn.execute(
        """
        SELECT *
        FROM prices
        WHERE company_id = ? AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (company_id, target_date.isoformat()),
    ).fetchone()


def price_stats(conn, company_id):
    today = date.today()
    latest = latest_price(conn, company_id)
    if latest is None:
        return {}

    latest_close = latest["adjusted_close"] or latest["close"]
    if latest_close is None:
        return {"latest_price": None, "latest_trade_date": latest["trade_date"]}
    p3m = price_on_or_before(conn, company_id, today - timedelta(days=90))
    p6m = price_on_or_before(conn, company_id, today - timedelta(days=180))
    p12m = price_on_or_before(conn, company_id, today - timedelta(days=365))

    rows = conn.execute(
        """
        SELECT adjusted_close, close, volume
        FROM prices
        WHERE company_id = ? AND trade_date >= ?
        ORDER BY trade_date
        """,
        (company_id, (today - timedelta(days=365)).isoformat()),
    ).fetchall()
    closes = [(row["adjusted_close"] or row["close"]) for row in rows if (row["adjusted_close"] or row["close"])]
    volumes = [row["volume"] for row in rows if row["volume"] is not None]
    high_52w = max(closes) if closes else latest_close
    average_volume = sum(volumes) / len(volumes) if volumes else None
    average_traded_value = average_volume * latest_close if average_volume is not None and latest_close else None
    ma200 = sum(closes[-200:]) / len(closes[-200:]) if len(closes) >= 50 else None
    recent_volume = sum(volumes[-20:]) / len(volumes[-20:]) if len(volumes) >= 20 else None
    older_volume = sum(volumes[-80:-20]) / len(volumes[-80:-20]) if len(volumes) >= 80 else None

    return {
        "latest_price": latest_close,
        "latest_trade_date": latest["trade_date"],
        "return_3m": return_between(latest_close, p3m["adjusted_close"] or p3m["close"]) if p3m else None,
        "return_6m": return_between(latest_close, p6m["adjusted_close"] or p6m["close"]) if p6m else None,
        "return_12m": return_between(latest_close, p12m["adjusted_close"] or p12m["close"]) if p12m else None,
        "high_52w": high_52w,
        "drawdown_from_52w_high": return_between(latest_close, high_52w),
        "average_volume": average_volume,
        "average_traded_value": average_traded_value,
        "above_200ma": latest_close > ma200 if ma200 else False,
        "volume_change": safe_div(recent_volume, older_volume),
    }


def recent_events(conn, company_id, lookback_days=180):
    threshold = (date.today() - timedelta(days=lookback_days)).isoformat()
    rows = conn.execute(
        """
        SELECT *
        FROM events
        WHERE company_id = ? AND event_date >= ?
        ORDER BY event_date DESC
        """,
        (company_id, threshold),
    ).fetchall()
    return [dict(row) for row in rows]


def recent_filings(conn, company_id, limit=8):
    rows = conn.execute(
        """
        SELECT filing_date, document_type, title, url, source
        FROM filings
        WHERE company_id = ?
        ORDER BY filing_date DESC, id DESC
        LIMIT ?
        """,
        (company_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def recent_text_blocks(conn, company_id, limit=5):
    rows = conn.execute(
        """
        SELECT fiscal_year, section, title, text_excerpt, risk_flags_json, source
        FROM filing_text_blocks
        WHERE company_id = ?
        ORDER BY fiscal_year DESC, id DESC
        LIMIT ?
        """,
        (company_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def positive_catalyst_count(events):
    return len([event for event in events if (event.get("catalyst_score") or 0) > 0])


def build_metrics(conn, company):
    company_id = company["id"]
    fin = latest_financial(conn, company_id)
    price = latest_price(conn, company_id)
    if fin is None or price is None:
        return None

    prev = previous_financial(conn, company_id, fin["id"])
    stats = price_stats(conn, company_id)
    latest_close = stats.get("latest_price")
    if latest_close is None:
        return None
    market_cap = price["market_cap"]
    if not market_cap and latest_close and fin["shares_outstanding"]:
        market_cap = latest_close * fin["shares_outstanding"]
    net_debt = (fin["interest_bearing_debt"] or 0) - (fin["cash_and_equivalents"] or 0)
    enterprise_value = (market_cap or 0) + net_debt if market_cap is not None else None
    per = safe_div(latest_close, fin["eps"])
    pbr = safe_div(market_cap, fin["total_equity"])
    ev_ebitda = safe_div(enterprise_value, fin["ebitda"])
    fcf_yield = safe_div(fin["free_cash_flow"], market_cap)
    roe = percentage(safe_div(fin["net_income"], fin["total_equity"]))
    roa = percentage(safe_div(fin["net_income"], fin["total_assets"]))
    operating_margin = percentage(safe_div(fin["operating_income"], fin["revenue"]))
    fcf_margin = percentage(safe_div(fin["free_cash_flow"], fin["revenue"]))
    equity_ratio = percentage(safe_div(fin["total_equity"], fin["total_assets"]))
    net_debt_ebitda = safe_div(net_debt, fin["ebitda"])
    revenue_growth = None
    if prev and prev["revenue"] and fin["revenue"] is not None:
        revenue_ratio = safe_div(fin["revenue"], prev["revenue"])
        revenue_growth = percentage(revenue_ratio - 1) if revenue_ratio is not None else None
    events = recent_events(conn, company_id)
    filings = recent_filings(conn, company_id)
    text_blocks = recent_text_blocks(conn, company_id)

    risk_flags = {
        "negative_equity": (fin["total_equity"] or 0) <= 0,
        "operating_cf_negative_3y": operating_cf_negative_3y(conn, company_id),
        "low_liquidity": (stats.get("average_traded_value") or 0) < 30_000_000,
        "downward_revision": any(e["event_type"] == "downward_revision" for e in events),
        "large_dilution": any(e["event_type"] == "large_dilution" for e in events),
        "going_concern": any(e["event_type"] == "going_concern" for e in events),
    }

    return {
        "company_id": company_id,
        "market": company["market"],
        "ticker": company["ticker"],
        "security_code": company["security_code"],
        "company_name": company["company_name"],
        "exchange": company["exchange"],
        "sector": company["sector"],
        "industry": company["industry"],
        "currency": company["currency"],
        "latest_price": latest_close,
        "market_cap": market_cap,
        "enterprise_value": enterprise_value,
        "per": per,
        "pbr": pbr,
        "ev_ebitda": ev_ebitda,
        "fcf_yield": fcf_yield,
        "roe": roe,
        "roa": roa,
        "operating_margin": operating_margin,
        "fcf_margin": fcf_margin,
        "equity_ratio": equity_ratio,
        "net_debt_ebitda": net_debt_ebitda,
        "operating_cf": fin["operating_cash_flow"],
        "free_cash_flow": fin["free_cash_flow"],
        "revenue": fin["revenue"],
        "operating_income": fin["operating_income"],
        "net_income": fin["net_income"],
        "eps": fin["eps"],
        "total_assets": fin["total_assets"],
        "total_equity": fin["total_equity"],
        "interest_bearing_debt": fin["interest_bearing_debt"],
        "cash_and_equivalents": fin["cash_and_equivalents"],
        "revenue_growth": revenue_growth,
        "return_3m": stats.get("return_3m"),
        "return_6m": stats.get("return_6m"),
        "return_12m": stats.get("return_12m"),
        "drawdown_from_52w_high": stats.get("drawdown_from_52w_high"),
        "high_52w": stats.get("high_52w"),
        "average_traded_value": stats.get("average_traded_value"),
        "above_200ma": stats.get("above_200ma"),
        "volume_change": stats.get("volume_change"),
        "events": events,
        "filings": filings,
        "text_blocks": text_blocks,
        "event_count": len(events),
        "catalyst_count": positive_catalyst_count(events),
        "risk_flags": risk_flags,
    }


def operating_cf_negative_3y(conn, company_id):
    rows = conn.execute(
        """
        SELECT operating_cash_flow
        FROM financial_facts
        WHERE company_id = ?
        ORDER BY period_end DESC, fiscal_year DESC
        LIMIT 3
        """,
        (company_id,),
    ).fetchall()
    return len(rows) == 3 and all((row["operating_cash_flow"] or 0) < 0 for row in rows)


def passes_filters(metrics, filters):
    if filters.get("exclude_negative_equity") and metrics["total_equity"] is not None and metrics["total_equity"] <= 0:
        return False
    if filters.get("exclude_operating_cf_negative") and (metrics["operating_cf"] or 0) <= 0:
        return False
    if filters.get("require_recent_catalyst") and metrics["catalyst_count"] == 0:
        return False

    checks = [
        ("min_market_cap", "market_cap", ">="),
        ("min_average_volume", "average_traded_value", ">="),
        ("max_per", "per", "<="),
        ("max_pbr", "pbr", "<="),
        ("max_ev_ebitda", "ev_ebitda", "<="),
        ("min_roe", "roe", ">="),
        ("min_operating_margin", "operating_margin", ">="),
        ("min_equity_ratio", "equity_ratio", ">="),
    ]
    for filter_key, metric_key, operator in checks:
        threshold = filters.get(filter_key)
        value = metrics.get(metric_key)
        if threshold is None or value is None:
            continue
        if operator == ">=" and value < threshold:
            return False
        if operator == "<=" and value > threshold:
            return False

    max_drawdown = filters.get("max_drawdown_from_52w_high")
    drawdown = metrics.get("drawdown_from_52w_high")
    if max_drawdown is not None and drawdown is not None:
        if percentage(drawdown) > max_drawdown:
            return False

    return True


def score_metrics(metrics, preset_config):
    weights = preset_config.get("weights", {})
    filters = preset_config.get("filters", {})
    low_liquidity_threshold = filters.get("min_average_volume", 30_000_000)
    metrics["risk_flags"]["low_liquidity"] = (metrics.get("average_traded_value") or 0) < low_liquidity_threshold

    valuation = valuation_score(metrics["per"], metrics["pbr"], metrics["ev_ebitda"], metrics["fcf_yield"])
    quality = quality_score(metrics["roe"], metrics["operating_margin"], metrics["fcf_margin"], metrics["revenue_growth"])
    safety = safety_score(metrics["equity_ratio"], metrics["net_debt_ebitda"], (metrics["operating_cf"] or 0) > 0)
    momentum = momentum_score(
        metrics["return_3m"],
        metrics["return_6m"],
        metrics["above_200ma"],
        metrics["volume_change"],
    )
    catalyst = catalyst_score(metrics["events"])
    risk = risk_score(metrics["risk_flags"])
    total = (
        valuation * weights.get("valuation", 0.30)
        + quality * weights.get("quality", 0.20)
        + safety * weights.get("safety", 0.15)
        + momentum * weights.get("momentum", 0.15)
        + catalyst * weights.get("catalyst", 0.15)
        - risk * weights.get("risk", 0.05)
    )

    metrics.update(
        {
            "valuation_score": round(valuation, 2),
            "quality_score": round(quality, 2),
            "safety_score": round(safety, 2),
            "momentum_score": round(momentum, 2),
            "catalyst_score": round(catalyst, 2),
            "risk_score": round(risk, 2),
            "total_score": round(max(total, 0), 2),
        }
    )
    metrics["recommendation_label"] = recommendation_label(metrics["total_score"])
    metrics["reason_summary"] = make_reason_summary(metrics)
    return metrics


def make_reason_summary(metrics):
    reasons = []
    if metrics.get("per") is not None and metrics["per"] <= 12:
        reasons.append("PERが低く割安感があります")
    if metrics.get("pbr") is not None and metrics["pbr"] <= 1.0:
        reasons.append("PBRが1倍以下です")
    if metrics.get("roe") is not None and metrics["roe"] >= 10:
        reasons.append("ROEが10%以上で資本効率が良好です")
    if metrics.get("equity_ratio") is not None and metrics["equity_ratio"] >= 35:
        reasons.append("自己資本比率が高めです")
    if metrics.get("catalyst_count"):
        reasons.append("直近カタリストがあります")
    if metrics.get("risk_score", 0) >= 40:
        reasons.append("リスクフラグが複数あります")
    return " / ".join(reasons) if reasons else "主要指標は中立的です"


def screen_companies(
    preset_name="balanced",
    market="all",
    overrides=None,
    limit=None,
    db_path=None,
    save=True,
    replace_filters=False,
    read_only=False,
):
    presets = load_presets()
    if preset_name not in presets:
        raise ValueError("Unknown preset: %s" % preset_name)
    preset = dict(presets[preset_name])
    filters = {} if replace_filters else dict(preset.get("filters", {}))
    if overrides:
        filters.update({k: v for k, v in overrides.items() if v is not None})
    preset["filters"] = filters

    if read_only and save:
        raise ValueError("Read-only screening cannot save results.")

    conn = get_connection(db_path, read_only=read_only)
    try:
        query = "SELECT * FROM company_master WHERE is_active = 1"
        params = []
        if market and market != "all":
            query += " AND market = ?"
            params.append(market)
        companies = conn.execute(query, params).fetchall()
        results = []
        for company in companies:
            metrics = build_metrics(conn, company)
            if not metrics:
                continue
            if not passes_filters(metrics, filters):
                continue
            scored = score_metrics(metrics, preset)
            results.append(scored)
        results.sort(key=lambda item: item["total_score"], reverse=True)
        if limit:
            results = results[: int(limit)]
        run_id = None
        if save:
            run_id = save_screening_results(conn, preset_name, results)
        return results, run_id
    finally:
        conn.close()


def save_screening_results(conn, preset_name, results):
    run_id = str(uuid.uuid4())
    for item in results:
        conn.execute(
            """
            INSERT INTO screening_results (
              run_id, company_id, preset_name, total_score,
              valuation_score, quality_score, safety_score, momentum_score,
              catalyst_score, risk_score, recommendation_label, reason_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                item["company_id"],
                preset_name,
                item["total_score"],
                item["valuation_score"],
                item["quality_score"],
                item["safety_score"],
                item["momentum_score"],
                item["catalyst_score"],
                item["risk_score"],
                item["recommendation_label"],
                item["reason_summary"],
            ),
        )
    conn.commit()
    return run_id


def find_company_by_ticker(conn, ticker):
    value = str(ticker).strip().upper()
    return conn.execute(
        """
        SELECT *
        FROM company_master
        WHERE UPPER(COALESCE(ticker, '')) = ?
           OR security_code = ?
           OR UPPER(COALESCE(edinet_code, '')) = ?
        LIMIT 1
        """,
        (value, value, value),
    ).fetchone()


def explain_ticker(ticker, preset_name="balanced", db_path=None, read_only=False):
    presets = load_presets()
    preset = presets.get(preset_name, presets["balanced"])
    conn = get_connection(db_path, read_only=read_only)
    try:
        company = find_company_by_ticker(conn, ticker)
        if not company:
            raise ValueError("Company not found: %s" % ticker)
        metrics = build_metrics(conn, company)
        if not metrics:
            raise ValueError("No financial or price data for: %s" % ticker)
        metrics = score_metrics(metrics, preset)
        text = build_explanation(metrics)
        return metrics, text
    finally:
        conn.close()


def pct(value):
    return "N/A" if value is None else "%.1f%%" % value


def ratio(value):
    return "N/A" if value is None else "%.2f" % value


def build_explanation(metrics):
    lines = [
        "%s (%s) の総合評価は %s 点、ラベルは %s です。"
        % (
            metrics["company_name"],
            metrics.get("security_code") or metrics.get("ticker"),
            metrics["total_score"],
            metrics["recommendation_label"],
        ),
        "PER %s倍、PBR %s倍、EV/EBITDA %s倍、FCF利回り %s です。"
        % (
            ratio(metrics.get("per")),
            ratio(metrics.get("pbr")),
            ratio(metrics.get("ev_ebitda")),
            pct(percentage(metrics.get("fcf_yield")) if metrics.get("fcf_yield") is not None else None),
        ),
        "ROE %s、営業利益率 %s、自己資本比率 %s で、財務品質と安全性を評価しています。"
        % (pct(metrics.get("roe")), pct(metrics.get("operating_margin")), pct(metrics.get("equity_ratio"))),
        "直近3か月リターン %s、6か月リターン %s、カタリスト数 %s 件です。"
        % (
            pct(percentage(metrics.get("return_3m")) if metrics.get("return_3m") is not None else None),
            pct(percentage(metrics.get("return_6m")) if metrics.get("return_6m") is not None else None),
            metrics.get("catalyst_count", 0),
        ),
        "理由: %s。" % metrics.get("reason_summary", ""),
    ]
    risk_notes = [name for name, active in metrics.get("risk_flags", {}).items() if active]
    if risk_notes:
        lines.append("注意点: %s。" % ", ".join(risk_notes))
    edinet_blocks = [block for block in metrics.get("text_blocks", []) if block.get("risk_flags_json") not in (None, "", "[]")]
    if edinet_blocks:
        lines.append("EDINET DBの有報テキストにリスク語が検出されています。詳細画面で該当テキストを確認してください。")
    lines.append(DISCLAIMER)
    return "\n".join(lines)
