from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from ..db import SessionLocal
from ..models import Source
from .runner import scan_source

scheduler = BackgroundScheduler()


def scan_now(source_id: int) -> str:
    with SessionLocal() as db:
        src = db.get(Source, source_id)
        return scan_source(db, src) if src else "not found"


def schedule_source(src: Source) -> None:
    job_id = f"source-{src.id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    if not src.enabled:
        return
    trigger = (CronTrigger.from_crontab(src.cron) if src.cron
               else IntervalTrigger(minutes=max(src.interval_minutes, 1), jitter=30))
    scheduler.add_job(scan_now, trigger, args=[src.id], id=job_id,
                      max_instances=1, coalesce=True)


def start() -> None:
    with SessionLocal() as db:
        for src in db.scalars(select(Source)):
            schedule_source(src)
    if not scheduler.running:
        scheduler.start()


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
