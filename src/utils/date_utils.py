from datetime import date, datetime, timedelta


def today_iso():
    return date.today().isoformat()


def days_ago_iso(days):
    return (date.today() - timedelta(days=days)).isoformat()


def parse_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def iso_or_none(value):
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else None

