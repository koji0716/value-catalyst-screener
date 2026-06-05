EVENT_POINTS = {
    "earnings_revision_up": 25,
    "dividend_increase": 20,
    "share_buyback": 25,
    "large_order": 15,
    "ma_or_capital_alliance": 20,
    "earnings_date_soon": 10,
    "activist_or_large_holding": 15,
    "business_sale": 15,
    "new_product": 10,
    "earnings_recovery": 20,
}


def catalyst_score(events):
    score = 0
    for event in events or []:
        event_type = event.get("event_type") if isinstance(event, dict) else getattr(event, "event_type", None)
        score += EVENT_POINTS.get(event_type, 0)
    return min(score, 100)

