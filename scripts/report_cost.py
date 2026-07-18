"""
Cost report.

Sums logged LLM call costs (llm_call_log.call_cost_usd) per profile run,
newest run first. Pass --forecast-id for one exact run, --symbol for the
latest run of a symbol (add --all for every run of that symbol), or nothing
for every forecast in the DB. Always writes cost_report.csv to the repo root.
"""
import argparse
import csv
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forecaster.config import SecretsNotFoundError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).resolve().parent.parent / "cost_report.csv"

CSV_COLUMNS = [
    "forecast_id", "symbol", "forecast_date", "agent_id", "executing_model",
    "calls", "tokens_in", "tokens_out", "tokens_cached", "cost_usd", "had_errors",
]


def fetch_rows(forecast_id: int | None, symbol: str | None, show_all: bool) -> list[tuple]:
    from forecaster.db import db_cursor

    where = []
    params: list = []
    if forecast_id is not None:
        where.append("f.id = %s")
        params.append(forecast_id)
    elif symbol is not None:
        where.append("f.symbol = %s")
        params.append(symbol)

    query = (
        "SELECT f.id, f.symbol, f.forecast_date, l.agent_id, l.executing_model, "
        "       COUNT(*), SUM(l.tokens_in), SUM(l.tokens_out), SUM(l.tokens_cached), "
        "       SUM(l.call_cost_usd), BOOL_OR(l.error IS NOT NULL) "
        "FROM llm_call_log l "
        "JOIN forecasts f ON f.id = l.forecast_id "
    )
    if where:
        query += "WHERE " + " AND ".join(where) + " "
    query += (
        "GROUP BY f.id, f.symbol, f.forecast_date, l.agent_id, l.executing_model "
        "ORDER BY f.forecast_date DESC, f.id DESC, SUM(l.call_cost_usd) DESC"
    )

    with db_cursor() as cur:
        cur.execute(query, tuple(params))
        rows = cur.fetchall()

    if symbol is not None and not show_all and rows:
        latest_id = rows[0][0]
        rows = [r for r in rows if r[0] == latest_id]

    return rows


def print_report(rows: list[tuple]) -> None:
    grand_total = 0.0
    current_forecast_id = None
    run_total = 0.0
    run_errors = False

    def flush_run():
        if current_forecast_id is not None:
            err_note = " (had errors)" if run_errors else ""
            print(f"  RUN TOTAL: ${run_total:.4f}{err_note}\n")

    for (fid, symbol, fdate, agent_id, model, calls, tin, tout, tcached, cost, had_errors) in rows:
        if fid != current_forecast_id:
            flush_run()
            print(f"forecast_id={fid}  symbol={symbol}  date={fdate}")
            current_forecast_id = fid
            run_total = 0.0
            run_errors = False
        err_flag = "  [errors]" if had_errors else ""
        print(
            f"  {agent_id:<20} {model:<28} calls={calls:<3} "
            f"in={tin:<8} out={tout:<8} cost=${cost:.4f}{err_flag}"
        )
        run_total += float(cost)
        grand_total += float(cost)
        run_errors = run_errors or had_errors

    flush_run()
    print(f"GRAND TOTAL: ${grand_total:.4f}")


def write_csv(rows: list[tuple]) -> None:
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for (fid, symbol, fdate, agent_id, model, calls, tin, tout, tcached, cost, had_errors) in rows:
            writer.writerow([fid, symbol, fdate, agent_id, model, calls, tin, tout, tcached, f"{cost:.6f}", had_errors])
    logger.info("Wrote %s", CSV_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description="Report actual LLM cost per profile run")
    parser.add_argument("--forecast-id", type=int, help="Report on one exact forecast run")
    parser.add_argument("--symbol", help="Report on the latest run for this symbol")
    parser.add_argument(
        "--all", action="store_true",
        help="With --symbol, report every run for that symbol instead of just the latest",
    )
    args = parser.parse_args()

    if args.forecast_id and args.symbol:
        parser.error("--forecast-id and --symbol are mutually exclusive")
    if args.all and not args.symbol:
        parser.error("--all requires --symbol")

    rows = fetch_rows(args.forecast_id, args.symbol, args.all)
    if not rows:
        logger.warning("No llm_call_log rows matched")
        return

    print_report(rows)
    write_csv(rows)


if __name__ == "__main__":
    try:
        main()
    except SecretsNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(1)
