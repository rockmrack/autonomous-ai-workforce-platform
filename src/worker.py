"""
Celery Worker Configuration

Distributed task processing for background jobs.
"""

from celery import Celery
from kombu import Queue, Exchange

from config import settings

# Create Celery app
celery_app = Celery(
    "ai_workforce",
    broker=settings.redis.broker_url,
    backend=settings.redis.result_backend,
    include=[
        "src.tasks.discovery",
        "src.tasks.execution",
        "src.tasks.communication",
        "src.tasks.finance",
        "src.tasks.maintenance",
    ],
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=3600,  # 1 hour max
    task_soft_time_limit=3300,  # 55 min soft limit

    # Worker settings
    worker_prefetch_multiplier=1,
    worker_concurrency=4,
    worker_max_tasks_per_child=100,

    # Result backend
    result_expires=86400,  # 24 hours
    result_extended=True,

    # Task routing
    task_default_queue="default",
    task_queues=(
        Queue("default", Exchange("default"), routing_key="default"),
        Queue("discovery", Exchange("discovery"), routing_key="discovery.#"),
        Queue("execution", Exchange("execution"), routing_key="execution.#"),
        Queue("communication", Exchange("communication"), routing_key="communication.#"),
        Queue("finance", Exchange("finance"), routing_key="finance.#"),
        Queue("priority", Exchange("priority"), routing_key="priority.#"),
    ),
    task_routes={
        "src.tasks.discovery.*": {"queue": "discovery"},
        "src.tasks.execution.*": {"queue": "execution"},
        "src.tasks.communication.*": {"queue": "communication"},
        "src.tasks.finance.*": {"queue": "finance"},
    },

    # Beat schedule (periodic tasks)
    beat_schedule={
        "discover-jobs-every-5-minutes": {
            "task": "src.tasks.discovery.scan_all_platforms",
            "schedule": 300.0,  # 5 minutes
        },
        "check-messages-every-2-minutes": {
            "task": "src.tasks.communication.check_all_messages",
            "schedule": 120.0,  # 2 minutes
        },
        "reconcile-payments-hourly": {
            "task": "src.tasks.finance.reconcile_all_payments",
            "schedule": 3600.0,  # 1 hour
        },
        "release-cleared-payments-daily": {
            "task": "src.tasks.finance.release_cleared_payments",
            "schedule": 86400.0,  # 24 hours
        },
        "agent-health-check-hourly": {
            "task": "src.tasks.maintenance.check_agent_health",
            "schedule": 3600.0,  # 1 hour
        },
        "cleanup-old-data-daily": {
            "task": "src.tasks.maintenance.cleanup_old_data",
            "schedule": 86400.0,  # 24 hours
        },
        "generate-daily-reports": {
            "task": "src.tasks.finance.generate_daily_reports",
            "schedule": 86400.0,  # 24 hours
            "options": {"queue": "finance"},
        },
    },

    # Error handling
    task_annotations={
        "*": {
            "rate_limit": "100/m",
        },
        "src.tasks.discovery.*": {
            "rate_limit": "30/m",
        },
        "src.tasks.execution.*": {
            "rate_limit": "10/m",
        },
    },
)


# Celery signals
@celery_app.task(bind=True)
def debug_task(self):
    """Debug task for testing"""
    print(f"Request: {self.request!r}")
    return {"status": "ok"}


if __name__ == "__main__":
    celery_app.start()
