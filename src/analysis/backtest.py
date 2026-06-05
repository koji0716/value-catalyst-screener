from src.analysis.scoring import screen_companies


def run_simple_backtest(market, preset, start_date, end_date, holding_months=6, top_n=20):
    """MVP backtest based on stored sample/historical prices.

    This is intentionally conservative: it reports the current database's top-N
    historical 6M/12M returns and flags that point-in-time vendor data is needed
    for production-grade backtests.
    """
    results, _ = screen_companies(preset_name=preset, market=market, limit=top_n, save=False)
    if not results:
        return {
            "preset": preset,
            "market": market,
            "period": "%s to %s" % (start_date, end_date),
            "top_n": top_n,
            "average_return": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "note": "No candidates matched the preset.",
            "holdings": [],
        }

    field = "return_6m" if int(holding_months) <= 6 else "return_12m"
    returns = [item.get(field) for item in results if item.get(field) is not None]
    wins = [value for value in returns if value > 0]
    drawdowns = [item.get("drawdown_from_52w_high") for item in results if item.get("drawdown_from_52w_high") is not None]
    average_return = sum(returns) / len(returns) if returns else 0.0
    win_rate = len(wins) / len(returns) if returns else 0.0
    max_drawdown = min(drawdowns) if drawdowns else 0.0
    return {
        "preset": preset,
        "market": market,
        "period": "%s to %s" % (start_date, end_date),
        "holding_months": holding_months,
        "top_n": top_n,
        "average_return": average_return,
        "annualized_return": average_return * (12 / max(int(holding_months), 1)),
        "win_rate": win_rate,
        "max_drawdown": max_drawdown,
        "note": "MVP簡易バックテストです。本番検証には上場廃止銘柄を含むpoint-in-timeデータが必要です。",
        "holdings": results,
    }

