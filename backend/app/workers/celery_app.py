from celery import Celery
from celery.signals import setup_logging as celery_setup_logging_signal

from app.core.config import settings
from app.workers.whatsapp_beat_schedule import WHATSAPP_BEAT_SCHEDULE

celery_app = Celery("instagram_automation", include=["app.workers.whatsapp_tasks"])
celery_app.conf.broker_url = settings.REDIS_URL
celery_app.conf.result_backend = settings.REDIS_URL
celery_app.conf.task_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.result_serializer = "json"
celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True
celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    **WHATSAPP_BEAT_SCHEDULE,
}

celery_app.autodiscover_tasks(["app.workers.tasks"])


@celery_setup_logging_signal.connect
def _use_app_json_logging(*args, **kwargs):
    """Replace Celery's default logging setup with the app's JSON formatter.

    Without this, worker/beat processes use Celery's plain-text logging,
    which drops every `extra={...}` field (error codes, message ids, raw
    Meta API responses) that the app's loggers attach — the exact detail
    needed to diagnose a failed send. Connecting to this signal fully
    replaces Celery's own logging config (its documented override point),
    matching what setup_logging() already does for the FastAPI process.
    """
    from app.core.logging import setup_logging

    setup_logging()
