from celery.schedules import crontab


INSTAGRAM_TOKEN_BEAT_SCHEDULE = {
    "instagram-token-refresh": {
        "task": "app.workers.instagram_token_tasks.refresh_expiring_instagram_tokens",
        "schedule": crontab(hour=3, minute=30),
    },
}
