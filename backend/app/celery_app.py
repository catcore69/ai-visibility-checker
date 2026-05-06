from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery("ai_visibility")

celery_app.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,

    # Ограничиваем параллелизм — только 2 отчёта одновременно
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,

    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_TIME_LIMIT - 60,

    # При падении воркера — не теряем задачу
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    task_default_queue="reports",
    task_queues={
        "reports": {"exchange": "reports", "routing_key": "reports"},
        "emails": {"exchange": "emails", "routing_key": "emails"},
    },

    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Moscow",
    enable_utc=True,

    # Авто-откат через 10 минут
    task_reject_on_worker_lost=True,
)

# Периодические задачи
celery_app.conf.beat_schedule = {
    # Удалять неверифицированные заявки старше 24 часов
    "cleanup-unverified-reports": {
        "task": "app.tasks.generate_report.cleanup_unverified_reports",
        "schedule": crontab(hour=3, minute=0),
    },
    # Удалять истёкшие кэши
    "cleanup-expired-cache": {
        "task": "app.tasks.generate_report.cleanup_expired_cache",
        "schedule": crontab(hour=4, minute=0),
    },
    # Follow-up email через 2 дня
    "send-followup-day-2": {
        "task": "app.tasks.send_emails.send_followup_emails",
        "schedule": crontab(hour=10, minute=0),
        "args": [2],
    },
    # Follow-up email через 7 дней
    "send-followup-day-7": {
        "task": "app.tasks.send_emails.send_followup_emails",
        "schedule": crontab(hour=10, minute=30),
        "args": [7],
    },
}

# Регистрируем таски
celery_app.autodiscover_tasks(["app.tasks"])
