from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery("ai_visibility")

celery_app.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,

    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,
    worker_pool='threads',

    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_TIME_LIMIT - 60,

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

    task_reject_on_worker_lost=True,
)

# Периодические задачи
celery_app.conf.beat_schedule = {
    "cleanup-unverified-reports": {
        "task": "app.tasks.generate_report.cleanup_unverified_reports",
        "schedule": crontab(hour=3, minute=0),
    },
    "cleanup-expired-cache": {
        "task": "app.tasks.generate_report.cleanup_expired_cache",
        "schedule": crontab(hour=4, minute=0),
    },
    # Этап 4.2 ТЗ: новая follow-up цепочка через таблицу email_followups.
    # Сканируем каждые 15 минут pending записи, отправляем то, что просрочено.
    "scan-pending-followups": {
        "task": "app.tasks.send_emails.scan_pending_followups",
        "schedule": crontab(minute="*/15"),
    },
}

# Регистрируем таски (отложенно, чтобы избежать кругового импорта)
celery_app.autodiscover_tasks(["app.tasks"])

def register_tasks():
    from app.tasks.generate_report import (
        generate_report_task,
        auto_send_report_after_timeout,
        cleanup_unverified_reports,
        cleanup_expired_cache,
    )
    from app.tasks.send_emails import send_followup_emails

    celery_app.register_task(generate_report_task)
    celery_app.register_task(auto_send_report_after_timeout)
    celery_app.register_task(cleanup_unverified_reports)
    celery_app.register_task(cleanup_expired_cache)
    celery_app.register_task(send_followup_emails)

register_tasks()
