from celery.schedules import crontab

from app.workers.celery_app import celery_app

celery_app.conf.beat_schedule = {
    "check-token-expiry": {
        "task": "app.workers.tasks.check_token_expiry",
        "schedule": crontab(hour=9, minute=0),
    },
    "refresh-expiring-tokens": {
        "task": "app.workers.tasks.refresh_expiring_tokens",
        "schedule": crontab(hour=10, minute=0),
    },
    "webhook-health-check": {
        "task": "app.workers.tasks.webhook_health_check",
        "schedule": crontab(minute=0),
    },
}
