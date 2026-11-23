from celery.schedules import crontab


SAAS_BEAT_SCHEDULE = {
    "saas-forward-sweep": {
        "task": "app.workers.saas_forward_tasks.sweep_saas_forwards",
        "schedule": crontab(minute="*"),
    },
    "saas-send-sweep": {
        "task": "app.workers.saas_send_tasks.sweep_saas_sends",
        "schedule": crontab(minute="*/2"),
    },
    "saas-health-sweep": {
        "task": "app.workers.saas_health_tasks.sweep_saas_health",
        "schedule": crontab(minute="*/2"),
    },
    "saas-retention-purge": {
        "task": "app.workers.saas_retention_tasks.purge_saas_data",
        "schedule": crontab(hour=3, minute=30),
    },
}
