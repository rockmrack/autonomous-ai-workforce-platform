"""
Celery Tasks - Background job processing
"""

from .discovery import scan_all_platforms, scan_platform, score_jobs
from .execution import execute_job, submit_deliverable
from .communication import check_all_messages, send_message, respond_to_message
from .finance import reconcile_all_payments, release_cleared_payments, process_withdrawal
from .maintenance import check_agent_health, cleanup_old_data

__all__ = [
    # Discovery
    "scan_all_platforms",
    "scan_platform",
    "score_jobs",
    # Execution
    "execute_job",
    "submit_deliverable",
    # Communication
    "check_all_messages",
    "send_message",
    "respond_to_message",
    # Finance
    "reconcile_all_payments",
    "release_cleared_payments",
    "process_withdrawal",
    # Maintenance
    "check_agent_health",
    "cleanup_old_data",
]
