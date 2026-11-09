#!/usr/bin/env python3
"""FTEC5660 HW3 student starter: an agent that applies 3 of Fisher's 15 points using tools."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sqlite3
import threading
import zlib
from pathlib import Path
from typing import Any


MODEL_NAME = "deepseek-v4-flash"
INTERVIEW_LIMIT = 10
MAX_SQL_ROWS = 50

# Philip Fisher, "Common Stocks and Uncommon Profits", Part One, Chapter 3.
# For every point, PASS means the company looks good on it. You choose 3
# points and decide yourself what PASS means for each of them.
FISHER_POINTS = {
    1: "Does the company have products or services with sufficient market potential to make possible a sizable increase in sales for at least several years?",
    2: "Does the management have a determination to continue to develop products or processes that will still further increase total sales potentials when the growth potentials of currently attractive product lines have largely been exploited?",
    3: "How effective are the company's research and development efforts in relation to its size?",
    4: "Does the company have an above-average sales organization?",
    5: "Does the company have a worthwhile profit margin?",
    6: "What is the company doing to maintain or improve profit margins?",
    7: "Does the company have outstanding labor and personnel relations?",
    8: "Does the company have outstanding executive relations?",
    9: "Does the company have depth to its management?",
    10: "How good are the company's cost analysis and accounting controls?",
    11: "Are there other aspects of the business, somewhat peculiar to the industry involved, which will give the investor important clues as to how outstanding the company may be in relation to its competition?",
    12: "Does the company have a short-range or long-range outlook in regard to profits?",
    13: "In the foreseeable future will the growth of the company require sufficient equity financing so that the larger number of shares then outstanding will largely cancel the existing stockholders' benefit from this anticipated growth?",
    14: "Does the management talk freely to investors about its affairs when things are going well but 'clam up' when troubles and disappointments occur?",
    15: "Does the company have a management of unquestionable integrity?",
}
VERDICTS = ("PASS", "FAIL")


def load_env_file(path: Path = Path(".env")) -> None:
    """Load the simple KEY=VALUE entries used by this homework."""
    if not path.is_file():
        return
    import os

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


# ---------------------------------------------------------------------------
# Fisher points chosen and the deterministic rules behind them.
#
# We pick three points whose evidence lives entirely in the database, so the
# verdict can be computed exactly in Python/SQL instead of being guessed by the
# model (the starter notes that model arithmetic is the most common cause of
# wrong verdicts):
#
#   Point 1  "market potential for sales growth":
#       PASS when the company's 2-year revenue growth (latest complete year vs
#       two years before) is at least the industry median growth in
#       industry_medians.revenue_growth_2y_pct.  Growing at/above the industry
#       pace means the product lines still have sizable sales headroom.
#
#   Point 5  "worthwhile profit margin":
#       PASS when the latest complete-year operating margin
#       ((revenue - cost_of_sales - selling_admin - R&D) / revenue) is at
#       least the industry median operating_margin_pct.  Fisher argues a
#       below-average margin cannot fund the R&D and marketing needed to stay
#       competitive.
#
#   Point 6  "maintaining or improving margins":
#       PASS when the latest complete-year operating margin is not below the
#       prior complete-year margin (margins held or expanded YoY).  A falling
#       margin signals cost discipline that is slipping.
#
# All sums, ratios and year differences are computed here in Python from rows
# returned by the sql_query tool; the model only writes the prose summary.
# ---------------------------------------------------------------------------

CHOSEN_POINTS: list[int] = [1, 5, 6]  ### YOUR CODE HERE


def _parse_sql_table(text: str) -> tuple[list[str], list[list[str]]]:
    """Parse the text table returned by the sql_query tool into (header, rows)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return [], []
    header = [h.strip() for h in lines[0].split("|")]
    rows: list[list[str]] = []
    for ln in lines[1:]:
        if ln.startswith("...") or ln.startswith("(no rows") or ln.lower().startswith("sql error"):
            continue
        rows.append([c.strip() for c in ln.split("|")])
    return header, rows


def _first_float(cell: str) -> float:
    return float(str(cell).replace(",", ""))


def evaluate_company_financials(sql_tool: Any) -> tuple[dict[str, float], dict[int, str]]:
    """Run the fixed SQL through the company's sql_query tool and score points 1,5,6.

    Returns (metrics, verdicts). Every number is computed here, never by the model.
    """
    def run(query: str) -> str:
        out = sql_tool.invoke({"query": query})
        return getattr(out, "content", out) if not isinstance(out, str) else out

    _, ind_rows = _parse_sql_table(run("SELECT industry FROM company"))
    industry = ind_rows[0][0]

    _, med_rows = _parse_sql_table(run(
        "SELECT revenue_growth_2y_pct, operating_margin_pct "
        f"FROM industry_medians WHERE industry = '{industry}'"
    ))
    med_growth = _first_float(med_rows[0][0])
    med_om = _first_float(med_rows[0][1])

    # Revenue by calendar year (orders.amount is in USD thousands; ratios are unit-free).
    _, rev_rows = _parse_sql_table(run(
        "SELECT substr(order_date,1,4) AS y, SUM(amount) FROM orders GROUP BY y ORDER BY y"
    ))
    revenue = {r[0]: _first_float(r[1]) for r in rev_rows}

    # Costs by calendar year.
    _, cost_rows = _parse_sql_table(run(
        "SELECT substr(month,1,4) AS y, SUM(cost_of_sales), SUM(selling_admin), "
        "SUM(research_development) FROM monthly_costs GROUP BY y ORDER BY y"
    ))
    costs: dict[str, tuple[float, float, float]] = {}
    for r in cost_rows:
        costs[r[0]] = (_first_float(r[1]), _first_float(r[2]), _first_float(r[3]))

    # Complete years = those with 12 months of cost data (drops the partial current year).
    _, month_rows = _parse_sql_table(run(
        "SELECT substr(month,1,4) AS y, COUNT(DISTINCT month) FROM monthly_costs GROUP BY y"
    ))
    full_years = sorted(r[0] for r in month_rows if _first_float(r[1]) >= 12)
    if not full_years:
        full_years = sorted(revenue)
    latest = full_years[-1]
    base = str(int(latest) - 2)   # two-year growth window
    prev = str(int(latest) - 1)   # year-over-year margin window

    def operating_margin(year: str) -> float:
        cogs, sga, rd = costs[year]
        rev = revenue[year]
        return (rev - cogs - sga - rd) / rev * 100.0

    growth_2y = (revenue[latest] / revenue[base] - 1.0) * 100.0
    om_latest = operating_margin(latest)
    om_prev = operating_margin(prev)

    verdicts = {
        1: "PASS" if growth_2y >= med_growth else "FAIL",
        5: "PASS" if om_latest >= med_om else "FAIL",
        6: "PASS" if om_latest >= om_prev else "FAIL",
    }
    metrics = {
        "industry": industry,
        "latest_year": float(latest),
        "base_year": float(base),
        "growth_2y_pct": growth_2y,
        "med_growth_pct": med_growth,
        "om_latest_pct": om_latest,
        "om_prev_pct": om_prev,
        "med_om_pct": med_om,
    }
    return metrics, verdicts


def build_agent() -> Any:
    """Create the DeepSeek chat model once.

    The model only writes the natural-language summary; the PASS/FAIL verdicts
    are computed deterministically in ``evaluate_company_financials`` so that
    model arithmetic never flips a verdict.
    """
    from langchain_deepseek import ChatDeepSeek

    return ChatDeepSeek(model=MODEL_NAME, temperature=0.0, timeout=60)


async def analyze_companies(agent: Any, companies: dict[str, list[Any]]) -> dict[str, dict[str, Any]]:
    """Score each company on points 1, 5, 6 and write a one-paragraph summary.

    For every company we ask its own sql_query tool for the industry, the
    industry medians, annual revenue and annual cost lines; all ratios are then
    computed in Python (see ``evaluate_company_financials``). The DeepSeek model
    is used only to turn the already-decided numbers into a readable summary.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    results: dict[str, dict[str, Any]] = {}

    def fallback_summary(m: dict[str, float], verdicts: dict[int, str]) -> str:
        direction = "held/improved" if m["om_latest_pct"] >= m["om_prev_pct"] else "slipped"
        return (
            f"Point 1 (market potential): revenue grew {m['growth_2y_pct']:.1f}% over two "
            f"years versus an industry median of {m['med_growth_pct']:.1f}% -> {verdicts[1]}. "
            f"Point 5 (profit margin): {m['latest_year']:.0f} operating margin was "
            f"{m['om_latest_pct']:.1f}% versus an industry median of {m['med_om_pct']:.1f}% -> "
            f"{verdicts[5]}. Point 6 (margin trend): margin {direction} from "
            f"{m['om_prev_pct']:.1f}% to {m['om_latest_pct']:.1f}% -> {verdicts[6]}."
        )

    for name, tools in companies.items():
        try:
            by_name = {getattr(t, "name", ""): t for t in tools}
            sql_tool = by_name.get("sql_query")
            if sql_tool is None:
                results[name] = {"points": {}, "summary": "sql_query tool unavailable."}
                continue

            metrics, verdicts = evaluate_company_financials(sql_tool)
            summary = fallback_summary(metrics, verdicts)
            try:
                system = SystemMessage(
                    "You are a buy-side analyst applying Philip Fisher's framework. "
                    "Given verified financial figures and already-decided PASS/FAIL verdicts "
                    "on Fisher points 1 (2-year revenue growth vs industry median), 5 "
                    "(operating margin vs industry median) and 6 (margin maintained/improved "
                    "year over year), write two or three concise English sentences that explain "
                    "the verdicts using the numbers. Do not invent figures, do not change the "
                    "verdicts, and do not add a heading."
                )
                user = HumanMessage(
                    f"Industry: {metrics['industry']}. "
                    f"2-year revenue growth {metrics['growth_2y_pct']:.1f}% "
                    f"(industry median {metrics['med_growth_pct']:.1f}%). "
                    f"Operating margin {metrics['om_latest_pct']:.1f}% in "
                    f"{metrics['latest_year']:.0f} vs industry median {metrics['med_om_pct']:.1f}% "
                    f"and prior year {metrics['om_prev_pct']:.1f}%. "
                    f"Verdicts: point1={verdicts[1]}, point5={verdicts[5]}, point6={verdicts[6]}."
                )
                resp = await agent.ainvoke([system, user])
                text = getattr(resp, "content", str(resp)).strip()
                if text:
                    summary = text
            except Exception:
                pass  # keep the deterministic fallback summary
            results[name] = {"points": verdicts, "summary": summary}
        except Exception as exc:  # one bad company must not sink the whole run
            results[name] = {"points": {}, "summary": f"Analysis failed: {exc}"}
    return results


# Everything below is provided runner/scoring code. No edits are needed.
# Your code must read company data only through these tools: do not open
# company.db or interviews.dat directly.

INTERVIEWS_USED: dict[str, int] = {}


def company_folders(folder: Path) -> list[Path]:
    """Return one sub-folder per company directly inside *folder*, sorted by name."""
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith("."))


def make_tools(company_folder: Path) -> list[Any]:
    """Build the four tools for one company."""
    from langchain_core.tools import tool

    name = company_folder.name
    db_uri = f"{(company_folder / 'company.db').resolve().as_uri()}?mode=ro"
    answers = json.loads(zlib.decompress((company_folder / "interviews.dat").read_bytes()))
    documents = {p.name: p for p in sorted(company_folder.glob("*.md"))}
    lock = threading.Lock()
    INTERVIEWS_USED[name] = 0

    @tool
    def list_documents() -> str:
        """List this company's documents (annual letter, earnings calls, news) with their dates."""
        lines = []
        for doc_name, path in documents.items():
            text = path.read_text(encoding="utf-8").splitlines()
            dated = next((line for line in text if line.startswith("Date:")), "")
            lines.append(f"{doc_name}: {text[0].lstrip('# ')} ({dated or 'undated'})")
        return "\n".join(lines)

    @tool
    def read_document(name: str) -> str:
        """Return the full text of one document named by list_documents, e.g. 'annual_letter_2025.md'."""
        path = documents.get(name.strip())
        if path is None:
            return f"No document named {name!r}. Available: {', '.join(documents)}"
        return path.read_text(encoding="utf-8")

    @tool
    def sql_query(query: str) -> str:
        """Run one read-only SQLite query on this company's database and return at most 50 rows.

        Amounts are in USD thousands. Dates are 'YYYY-MM-DD', months 'YYYY-MM', quarters like '2025Q3'.
        Tables:
          company(name, industry)
          industry_medians(industry, revenue_growth_2y_pct, new_product_share_pct, new_product_sales_per_rd, operating_margin_pct)
          orders(order_id, order_date, product, customer, amount, note)
          products(product, launch_date)
          monthly_costs(month, cost_of_sales, selling_admin, research_development)
          quarterly_cash(quarter, operating_cash_flow, capex, cash_end)
          capex_plan(year, planned_capex)
          returns(month, units_shipped, units_returned)
          insider_trades(trade_date, person, title, side, shares, price)
        Use SUM, GROUP BY and WHERE to compute totals rather than reading raw rows.
        """
        try:
            con = sqlite3.connect(db_uri, uri=True)
            try:
                cursor = con.execute(query)
                columns = [c[0] for c in cursor.description or []]
                rows = cursor.fetchmany(MAX_SQL_ROWS + 1)
            finally:
                con.close()
        except sqlite3.Error as exc:
            return f"SQL error: {exc}"
        if not columns:
            return "Query returned no columns."
        fmt = lambda v: f"{v:.2f}" if isinstance(v, float) else str(v)  # noqa: E731
        out = [" | ".join(columns)] + [" | ".join(fmt(v) for v in row) for row in rows[:MAX_SQL_ROWS]]
        if len(rows) > MAX_SQL_ROWS:
            out.append(f"... more rows not shown (limit {MAX_SQL_ROWS}); aggregate or add LIMIT/OFFSET.")
        if not rows:
            out.append("(no rows)")
        return "\n".join(out)

    @tool
    def interview(role: str, topic: str) -> str:
        """Interview one person about the company (at most 10 interviews per company).

        role: customer, current_employee, former_employee, competitor or supplier.
        topic: sales_team, working_conditions, top_management, decision_making or competitive_edge.
        People who would not know about a topic say so; the README lists who knows what.
        """
        role, topic = role.strip().lower(), topic.strip().lower()
        if role not in answers:
            return f"Unknown role {role!r}. Roles: {', '.join(answers)}. (Not counted.)"
        if topic not in answers[role]:
            return f"Unknown topic {topic!r}. Topics: {', '.join(answers[role])}. (Not counted.)"
        with lock:
            if INTERVIEWS_USED[name] >= INTERVIEW_LIMIT:
                return f"Interview limit reached: {INTERVIEW_LIMIT} interviews per company."
            INTERVIEWS_USED[name] += 1
        return answers[role][topic]

    return [list_documents, read_document, sql_query, interview]


def normalize_verdict(value: Any) -> str | None:
    """Accept PASS/FAIL (any case) or a boolean."""
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    text = str(getattr(value, "content", value)).strip().upper()
    return text if text in VERDICTS else None


def check_chosen_points(chosen: Any) -> list[int]:
    """CHOSEN_POINTS must name 3 different points between 1 and 15."""
    try:
        points = sorted({int(p) for p in chosen})
    except (TypeError, ValueError):
        points = []
    if len(points) != 3 or len(chosen) != 3 or not all(p in FISHER_POINTS for p in points):
        raise SystemExit("Set CHOSEN_POINTS at the top of hw3.py to 3 different point numbers "
                         f"between 1 and 15, e.g. [1, 7, 15] (now: {chosen!r}).")
    return points


def normalize_points(points: Any, chosen: list[int]) -> dict[int, str | None]:
    """Map each chosen point number to PASS/FAIL, or None when missing/invalid."""
    points = points if isinstance(points, dict) else {}
    by_number: dict[int, Any] = {}
    for key, value in points.items():
        try:
            by_number[int(key)] = value
        except (TypeError, ValueError):
            continue
    return {p: normalize_verdict(by_number.get(p)) for p in chosen}


def read_ground_truth(folder: Path) -> dict[str, dict[str, Any]]:
    """Read the expected 15 point verdicts per company."""
    path = folder / "ground_truth.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def point_errors(points: dict[int, str | None], expected: dict[str, Any] | None) -> tuple[int, str]:
    """Count correct point verdicts and describe the wrong ones."""
    if expected is None:
        return 0, ""
    wrong = []
    for p in points:
        truth = expected["points"][str(p)]
        if points[p] != truth:
            wrong.append(f"{p}: expected {truth}, predicted {points[p] or 'missing'}")
    if all(v is None for v in points.values()):
        return 0, "all point verdicts missing"
    return len(points) - len(wrong), "; ".join(wrong)


def balanced_point_accuracy(
    analyses: dict[str, Any], truth: dict[str, dict[str, Any]], names: list[str], chosen: list[int]
) -> float:
    """Mean of the accuracy on true-PASS points and on true-FAIL points.

    Most verdicts are PASS, so answering PASS everywhere gets a high plain
    accuracy but only 50% balanced accuracy. Grading uses the balanced number.
    """
    hits = {"PASS": [0, 0], "FAIL": [0, 0]}
    for name in names:
        if name not in truth:
            continue
        entry = analyses.get(name)
        points = normalize_points(entry.get("points") if isinstance(entry, dict) else None, chosen)
        for p in chosen:
            expected = truth[name]["points"][str(p)]
            hits[expected][0] += points[p] == expected
            hits[expected][1] += 1
    rates = [h / n for h, n in hits.values() if n]
    return sum(rates) / len(rates) if rates else 0.0


def write_results(
    names: list[str], analyses: dict[str, Any], truth: dict[str, dict[str, Any]], chosen: list[int]
) -> tuple[Path, int]:
    """Write results.csv and return the number of correct point verdicts."""
    output = Path("results.csv")
    correct_points = 0
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["company", "points", "points_correct", "point_errors", "interviews_used", "summary"])
        for name in names:
            entry = analyses.get(name)
            entry = entry if isinstance(entry, dict) else {}
            points = normalize_points(entry.get("points"), chosen)
            expected = truth.get(name)
            n_points, errors = point_errors(points, expected)
            correct_points += n_points
            writer.writerow([
                name,
                " ".join(f"{p}:{points[p] or 'missing'}" for p in chosen),
                f"{n_points}/{len(chosen)}" if expected else "",
                errors,
                INTERVIEWS_USED.get(name, 0),
                str(entry.get("summary", "")).strip(),
            ])
    return output, correct_points


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run FTEC5660 HW3 on company data folders")
    parser.add_argument(
        "--data-folder",
        required=True,
        type=Path,
        help="folder containing one sub-folder per company",
    )
    return parser.parse_args()


async def run(folder: Path) -> int:
    folders = company_folders(folder)
    if not folders:
        raise SystemExit(f"no company folders found in {folder}")

    chosen = check_chosen_points(CHOSEN_POINTS)
    load_env_file()
    companies = {path.name: make_tools(path) for path in folders}
    agent = build_agent()
    analyses = await analyze_companies(agent, companies)
    if not isinstance(analyses, dict):
        raise TypeError("analyze_companies() must return a dictionary")

    truth = read_ground_truth(folder)
    output, correct_points = write_results(list(companies), analyses, truth, chosen)
    summary = f" Your points: {', '.join(map(str, chosen))}."
    if truth:
        summary += (
            f" Point accuracy: {correct_points}/{len(companies) * len(chosen)}"
            f" (balanced: {balanced_point_accuracy(analyses, truth, list(companies), chosen):.1%})."
        )
    print(f"Processed {len(companies)} compan{'y' if len(companies) == 1 else 'ies'}. Wrote {output}.{summary}")
    return 0


def main() -> int:
    args = parse_args()
    if not args.data_folder.is_dir():
        raise SystemExit(f"not a folder: {args.data_folder}")
    return asyncio.run(run(args.data_folder))


if __name__ == "__main__":
    raise SystemExit(main())
