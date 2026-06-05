from src.utils.file_utils import DISCLAIMER


def format_pct(value):
    if value is None:
        return "N/A"
    return "%.1f%%" % (value * 100 if abs(value) <= 1 else value)


def format_ratio(value):
    if value is None:
        return "N/A"
    return "%.2f" % value


def format_jpy(value):
    if value is None:
        return "N/A"
    if abs(value) >= 1_000_000_000_000:
        return "%.2f兆円" % (value / 1_000_000_000_000)
    if abs(value) >= 100_000_000:
        return "%.2f億円" % (value / 100_000_000)
    return "%.0f円" % value


def disclaimer():
    return DISCLAIMER

