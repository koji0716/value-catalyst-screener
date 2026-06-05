from src.analysis.metrics import safe_div


def momentum_score(return_3m, return_6m, above_200ma, volume_change):
    score = 0

    if return_3m is not None:
        if return_3m >= 0.15:
            score += 25
        elif return_3m >= 0.05:
            score += 15
        elif return_3m >= -0.10:
            score += 8

    if return_6m is not None:
        if return_6m >= 0.20:
            score += 25
        elif return_6m >= 0.05:
            score += 15
        elif return_6m >= -0.15:
            score += 8

    if above_200ma:
        score += 25

    if volume_change is not None:
        if volume_change >= 1.5:
            score += 25
        elif volume_change >= 1.2:
            score += 15

    return min(score, 100)


def return_between(current_price, past_price):
    ratio = safe_div(current_price, past_price)
    if ratio is None:
        return None
    return ratio - 1

