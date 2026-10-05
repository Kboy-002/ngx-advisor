"""APScheduler jobs: daily EOD 16:30 WAT, Sat 08:00 upload nudge log,
27th 08:00 monthly-pick log. Lightweight: jobs log intent + refresh what
they can; heavy lifting stays in explicit API calls / dashboard buttons
so a PC that was off simply catches up on next boot."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("ngx-scheduler")


def job_daily_eod():
    log.info("daily EOD: pulling NGX price list + ASI into Postgres")
    try:
        from ingest import run_and_store
        res = run_and_store()
        log.info("daily EOD done: %s", res)
    except Exception as exc:  # never crash the scheduler
        log.warning("daily EOD failed: %s", exc)


def job_daily_news():
    log.info("daily news: collecting disclosures + RSS signals")
    try:
        from collector import run_all
        res = run_all()
        log.info("daily news done: %s", res)
    except Exception as exc:
        log.warning("daily news failed: %s", exc)


def job_saturday_nudge():
    log.info("Saturday: nudge — upload this week's Afrinvest PDF in the dashboard")


def job_saturday_earnings():
    log.info("saturday earnings: extracting quality factors from results coverage")
    try:
        from earnings import run_earnings
        log.info("earnings done: %s", run_earnings())
    except Exception as exc:
        log.warning("earnings failed: %s", exc)


def job_saturday_digest():
    log.info("Saturday digest: Afrinvest weekly + AI weekly brief")
    try:
        from research import fetch_weekly
        log.info("research weekly: %s", fetch_weekly())
    except Exception as exc:
        log.warning("research weekly failed: %s", exc)
    try:
        import llm
        if not llm.is_configured():
            log.info("weekly digest skipped: LLM_API_KEY not set")
            return
        from analyst import weekly_digest
        d = weekly_digest()
        log.info("weekly digest done: %s", d.get("week"))
    except Exception as exc:
        log.warning("weekly digest failed: %s", exc)


def job_friday_fundamentals():
    log.info("friday fundamentals: NGX P/E PDFs + topchor pages")
    try:
        from fundamentals import run_fundamentals
        log.info("fundamentals done: %s", run_fundamentals())
    except Exception as exc:
        log.warning("fundamentals failed: %s", exc)


def job_monthly_analysis():
    from datetime import date as _date
    log.info("monthly analysis: AI deep-dive for %s", _date.today().strftime("%Y-%m"))
    try:
        import llm
        if not llm.is_configured():
            log.info("monthly analysis skipped: LLM_API_KEY not set")
            return
        import store as _store
        from analyst import monthly_analysis
        with _store.conn() as c:
            cur = c.execute("SELECT amount FROM cash_inputs ORDER BY month DESC LIMIT 1")
            row = cur.fetchone()
        cash = float(row[0]) if row else 100000.0
        a = monthly_analysis(cash)
        log.info("monthly analysis done: %d names", len((a.get("analyses") or [])))
    except Exception as exc:
        log.warning("monthly analysis failed: %s", exc)


def job_monthly_pick():
    today = datetime.now().strftime("%Y-%m-%d")
    log.info("monthly pick (%s): generating report — open dashboard to set cash amount", today)


def main():
    sched = BlockingScheduler(timezone="Africa/Lagos")
    sched.add_job(job_daily_eod, CronTrigger(hour=16, minute=30))
    sched.add_job(job_daily_news, CronTrigger(hour=17, minute=15))
    sched.add_job(job_friday_fundamentals, CronTrigger(day_of_week="fri", hour=18, minute=30))
    sched.add_job(job_saturday_nudge, CronTrigger(day_of_week="sat", hour=8, minute=0))
    sched.add_job(job_saturday_digest, CronTrigger(day_of_week="sat", hour=9, minute=30))
    sched.add_job(job_saturday_earnings, CronTrigger(day_of_week="sat", hour=10, minute=0))
    sched.add_job(job_monthly_pick, CronTrigger(day=27, hour=8, minute=0))
    sched.add_job(job_monthly_analysis, CronTrigger(day=27, hour=7, minute=0))
    log.info("scheduler started (Africa/Lagos). Next: %s", sched.get_jobs() and "jobs armed")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    if os.getenv("RUN_SCHEDULER") == "1":
        main()
    else:
        time.sleep(1)
        print("Set RUN_SCHEDULER=1 to run (docker compose handles this).")
