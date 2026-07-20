"""
Forecast job.

Runs the full 13-agent pipeline for every active position in the positions table.
Pass --symbol TICKER to run for a single position, or --symbols "TICKER1,TICKER2"
to run for a comma-separated list of positions. Tickers may contain spaces (e.g.
foreign-listing notation like "PANR LSE") -- only the comma is treated as a
separator.

--resume / --resume-forecast-id pick an existing incomplete forecast back up
where it left off (see ForecastPipeline.resume()) instead of starting fresh --
useful after a network failure mid-batch, since it skips every stage that
already completed rather than re-paying for the whole pipeline.
"""
import argparse
import logging
import sys
from datetime import date
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
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume incomplete forecast(s) (recommendation IS NULL) instead of starting "
             "fresh runs -- skips every stage that already completed. Combine with "
             "--symbol/--symbols to resume the latest incomplete row for those symbols; "
             "omit both to auto-discover ALL of --date's incomplete rows. Never triages "
             "(a resume is a continuation of an already-approved run, not a new triage "
             "decision), so combining with --force is refused as a likely mistake.",
    )
    parser.add_argument(
        "--resume-forecast-id", type=int,
        help="Resume one specific forecast_id directly, bypassing symbol/date lookup.",
    )
    parser.add_argument(
        "--date", help="Date (YYYY-MM-DD) to scope --resume auto-discovery to. Defaults to today.",
    )
    args = parser.parse_args()

    if args.symbol and args.symbols:
        parser.error("--symbol and --symbols are mutually exclusive")

    if args.resume_forecast_id:
        if args.symbol or args.symbols or args.force or args.resume:
            parser.error("--resume-forecast-id is exclusive of --symbol/--symbols/--force/--resume")
    elif args.resume:
        if args.force:
            parser.error(
                "--resume and --force are exclusive -- resume never triages, so "
                "there's no triage gate for --force to bypass"
            )
    elif args.date:
        parser.error("--date only applies to --resume")

    if args.force and not args.resume_forecast_id and not args.symbol and not args.symbols:
        parser.error("--force requires --symbol/--symbols (refusing to bypass triage for a full batch run)")

    from forecaster.pipeline import ForecastPipeline

    pipeline = ForecastPipeline()

    if args.resume_forecast_id:
        try:
            forecast_id = pipeline.resume(args.resume_forecast_id)
            logger.info("forecast_id=%d resume complete", forecast_id)
        except Exception as exc:
            logger.error("resume forecast_id=%d failed: %s", args.resume_forecast_id, exc)
            sys.exit(1)
        return

    if args.resume:
        from forecaster.db import find_incomplete_forecasts

        target_date = date.fromisoformat(args.date) if args.date else date.today()
        if args.symbols:
            resume_symbols = parse_symbols(args.symbols)
        elif args.symbol:
            resume_symbols = [args.symbol]
        else:
            resume_symbols = None

        rows = find_incomplete_forecasts(forecast_date=target_date, symbols=resume_symbols)
        if not rows:
            logger.info(
                "No incomplete forecasts found for %s%s",
                target_date, f" (symbols={resume_symbols})" if resume_symbols else "",
            )
            return

        errors = []
        for row in rows:
            try:
                logger.info("Resuming forecast_id=%d (%s)", row["id"], row["symbol"])
                pipeline.resume(row["id"])
            except Exception as exc:
                logger.error("resume forecast_id=%d (%s) failed: %s", row["id"], row["symbol"], exc)
                errors.append(row["symbol"])

        if errors:
            logger.error("Failed resumes: %s", ", ".join(errors))
            sys.exit(1)
        return

    if args.symbols:
        symbols = parse_symbols(args.symbols)
    elif args.symbol:
        symbols = [args.symbol]
    else:
        symbols = get_active_symbols()
    if not symbols:
        logger.warning("No active symbols found")
        return

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
