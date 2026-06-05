def valuation_score(per, pbr, ev_ebitda, fcf_yield):
    score = 0

    if per is not None and per > 0:
        if per <= 8:
            score += 25
        elif per <= 12:
            score += 20
        elif per <= 18:
            score += 12
        elif per <= 25:
            score += 5

    if pbr is not None and pbr > 0:
        if pbr <= 0.7:
            score += 25
        elif pbr <= 1.0:
            score += 20
        elif pbr <= 1.5:
            score += 12
        elif pbr <= 2.0:
            score += 5

    if ev_ebitda is not None and ev_ebitda > 0:
        if ev_ebitda <= 5:
            score += 25
        elif ev_ebitda <= 8:
            score += 18
        elif ev_ebitda <= 12:
            score += 10

    if fcf_yield is not None:
        if fcf_yield >= 0.10:
            score += 25
        elif fcf_yield >= 0.07:
            score += 18
        elif fcf_yield >= 0.04:
            score += 10

    return min(score, 100)

