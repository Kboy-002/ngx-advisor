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


def job_monthly_pick():
    today = datetime.now().strftime("%Y-%m-%d")
    log.info("monthly pick (%s): generating report — open dashboard to set cash amount", today)


def main():
    sched = BlockingScheduler(timezone="Africa/Lagos")
    sched.add_job(job_daily_eod, CronTrigger(hour=16, minute=30))
    sched.add_job(job_daily_news, CronTrigger(hour=17, minute=15))
    sched.add_job(job_saturday_nudge, CronTrigger(day_of_week="sat", hour=8, minute=0))
    sched.add_job(job_monthly_pick, CronTrigger(day_of_month=27, hour=8, minute=0))
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
