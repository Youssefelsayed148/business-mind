def test_celery_app_imports():
    from app.workers.celery_app import celery_app

    assert celery_app is not None
    assert celery_app.main == "instagram_automation"
