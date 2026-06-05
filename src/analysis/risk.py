def risk_score(flags):
    score = 0

    if flags.get("negative_equity"):
        score += 40
    if flags.get("going_concern"):
        score += 40
    if flags.get("operating_cf_negative_3y"):
        score += 20
    if flags.get("low_liquidity"):
        score += 20
    if flags.get("downward_revision"):
        score += 20
    if flags.get("large_dilution"):
        score += 20

    return min(score, 100)

