from celery.schedules import crontab


WHATSAPP_BEAT_SCHEDULE = {
    "whatsapp-health-poll": {
        "task": "app.workers.whatsapp_tasks.poll_whatsapp_account_health",
        "schedule": crontab(minute="*/15"),
    },
    "whatsapp-template-sync": {
        "task": "app.workers.whatsapp_tasks.sync_whatsapp_templates",
        "schedule": crontab(minute=0),
    },
    "whatsapp-stale-send-reaper": {
        "task": "app.workers.whatsapp_tasks.reap_whatsapp_sending_messages",
        "schedule": crontab(minute="*/5"),
    },
    "whatsapp-campaign-rollup": {
        "task": "app.workers.whatsapp_tasks.rollup_whatsapp_campaigns",
        "schedule": crontab(minute="*/5"),
    },
}
