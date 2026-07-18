"""
Forecast job.

Runs the full 13-agent pipeline for every active position in the positions table.
Pass --symbol TICKER to run for a single position, or --symbols "TICKER1,TICKER2"
to run for a comma-separated list of positions. Tickers may contain spaces (e.g.
foreign-listing notation like "PANR LSE") -- only the comma is treated as a
separator.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forecaster.config import SecretsNotFoundError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_symbols(raw: str) -> list[str]:
    """Split a comma-separated symbol list, preserving spaces within each entry
    (e.g. "PANR LSE" foreign-listing notation stays intact as one symbol).
    Strips surrounding quote characters some users add around spaced tickers
    (e.g. "PANR LSE", MOH), since those aren't part of the symbol itself."""
    return [s.strip().strip("'\"") for s in raw.split(",") if s.strip().strip("'\"")]


def get_active_symbols() -> list[str]:
    from forecaster.db import portfolio_db_cursor
    with portfolio_db_cursor() as cur:
        cur.execute(
            "SELECT symbol FROM positions WHERE LOWER(status) = 'active' ORDER BY symbol"
        )
        return [row[0] for row in cur.fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run forecast pipeline")
    parser.add_argument("--symbol", help="Run for a single symbol only")
    parser.add_argument(
        "--symbols", help="Run for a comma-separated list of symbols, "
                          "e.g. \"PANR LSE, AAPL, MSI LSE\" (spaces within a symbol are kept)"
    )
    parser.add_argument("--horizon", type=int, default=90, help="Forecast horizon in days")
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass the triage gate (manual re-runs, model comparisons). "
             "Requires --symbol/--symbols -- refused for full-portfolio batch runs.",
    )
    args = parser.parse_args()

    if args.symbol and args.symbols:
        parser.error("--symbol and --symbols are mutually exclusive")

    if args.force and not args.symbol and not args.symbols:
        parser.error("--force requires --symbol/--symbols (refusing to bypass triage for a full batch run)")

    from forecaster.pipeline import ForecastPipeline

    if args.symbols:
        symbols = parse_symbols(args.symbols)
    elif args.symbol:
        symbols = [args.symbol]
    else:
        symbols = get_active_symbols()
    if not symbols:
        logger.warning("No active symbols found")
        return

    pipeline = ForecastPipeline()
    errors = []
    for symbol in symbols:
        try:
            logger.info("Running pipeline for %s", symbol)
            forecast_id = pipeline.run(symbol, question_horizon_days=args.horizon, force=args.force)
            if forecast_id is None:
                logger.info("%s skipped by triage gate", symbol)
            else:
                logger.info("%s complete (forecast_id=%d)", symbol, forecast_id)
        except Exception as exc:
            logger.error("%s failed: %s", symbol, exc)
            errors.append(symbol)

    if errors:
        logger.error("Failed symbols: %s", ", ".join(errors))
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SecretsNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(1)
