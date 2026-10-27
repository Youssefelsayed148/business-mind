from celery.schedules import crontab


WEBHOOK_RECOVERY_BEAT_SCHEDULE = {
    "webhook-recovery-sweep": {
        "task": "app.workers.webhook_recovery_tasks.sweep_webhook_events",
        "schedule": crontab(minute="*/5"),
    },
}
