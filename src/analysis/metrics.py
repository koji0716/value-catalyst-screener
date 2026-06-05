def safe_div(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def percentage(value):
    if value is None:
        return None
    return value * 100


def quality_score(roe, operating_margin, fcf_margin, revenue_growth):
    score = 0

    if roe is not None:
        if roe >= 15:
            score += 30
        elif roe >= 10:
            score += 20
        elif roe >= 5:
            score += 10

    if operating_margin is not None:
        if operating_margin >= 15:
            score += 25
        elif operating_margin >= 8:
            score += 15
        elif operating_margin >= 3:
            score += 8

    if fcf_margin is not None:
        if fcf_margin >= 10:
            score += 25
        elif fcf_margin >= 5:
            score += 15
        elif fcf_margin > 0:
            score += 8

    if revenue_growth is not None:
        if revenue_growth >= 10:
            score += 20
        elif revenue_growth >= 3:
            score += 10
        elif revenue_growth >= 0:
            score += 5

    return min(score, 100)


def safety_score(equity_ratio, net_debt_ebitda, operating_cf_positive):
    score = 0

    if equity_ratio is not None:
        if equity_ratio >= 50:
            score += 40
        elif equity_ratio >= 35:
            score += 30
        elif equity_ratio >= 25:
            score += 15

    if net_debt_ebitda is not None:
        if net_debt_ebitda <= 0:
            score += 30
        elif net_debt_ebitda <= 1:
            score += 25
        elif net_debt_ebitda <= 2:
            score += 15
        elif net_debt_ebitda <= 3:
            score += 5

    if operating_cf_positive:
        score += 30

    return min(score, 100)

