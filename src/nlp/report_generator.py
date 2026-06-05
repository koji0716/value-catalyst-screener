import csv
import html
from pathlib import Path

from src.utils.file_utils import DISCLAIMER, PROJECT_ROOT, ensure_runtime_dirs


DISPLAY_COLUMNS = [
    "ticker",
    "company_name",
    "market",
    "industry",
    "latest_price",
    "market_cap",
    "per",
    "pbr",
    "ev_ebitda",
    "roe",
    "equity_ratio",
    "fcf_yield",
    "return_3m",
    "return_6m",
    "catalyst_count",
    "total_score",
    "recommendation_label",
    "reason_summary",
]


def export_results(results, preset, output_format="csv", output_path=None):
    ensure_runtime_dirs()
    output_format = output_format.lower()
    if output_path is None:
        suffix = "html" if output_format == "html" else "csv"
        output_path = PROJECT_ROOT / "data" / "exports" / ("%s_report.%s" % (preset, suffix))
    else:
        output_path = Path(output_path)

    if output_format == "html":
        write_html(results, preset, output_path)
    else:
        write_csv(results, output_path)
    return output_path


def write_csv(results, output_path):
    with open(output_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=DISPLAY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for item in results:
            writer.writerow(flatten(item))


def write_html(results, preset, output_path):
    rows = []
    for item in results:
        flat = flatten(item)
        cells = "".join("<td>%s</td>" % html.escape(str(flat.get(col, ""))) for col in DISPLAY_COLUMNS)
        rows.append("<tr>%s</tr>" % cells)
    headers = "".join("<th>%s</th>" % html.escape(col) for col in DISPLAY_COLUMNS)
    content = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>Value Catalyst Screener - {preset}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #d8dee9; padding: 6px 8px; text-align: right; }}
    th:nth-child(2), td:nth-child(2), th:nth-child(18), td:nth-child(18) {{ text-align: left; }}
    th {{ background: #f3f6fa; }}
    .notice {{ padding: 10px 12px; border-left: 4px solid #3b82f6; background: #eef6ff; }}
  </style>
</head>
<body>
  <h1>Value Catalyst Screener: {preset}</h1>
  <p class="notice">{disclaimer}</p>
  <table>
    <thead><tr>{headers}</tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>
""".format(
        preset=html.escape(preset),
        disclaimer=html.escape(DISCLAIMER),
        headers=headers,
        rows="".join(rows),
    )
    output_path.write_text(content, encoding="utf-8")


def flatten(item):
    flat = {}
    for key, value in item.items():
        if isinstance(value, (list, dict)):
            continue
        if isinstance(value, float):
            if key in ("fcf_yield", "return_3m", "return_6m"):
                flat[key] = round(value * 100, 2)
            else:
                flat[key] = round(value, 2)
        else:
            flat[key] = value
    return flat

