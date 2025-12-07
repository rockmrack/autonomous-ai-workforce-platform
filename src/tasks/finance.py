"""
Finance Tasks - Payment processing and reconciliation
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from celery import shared_task
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


def run_async(coro):
    """Helper to run async code in sync Celery tasks"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(
    bind=True,
    name="src.tasks.finance.reconcile_all_payments",
    max_retries=2,
    default_retry_delay=300,
)
def reconcile_all_payments(self):
    """
    Reconcile payments across all platforms.

    Runs hourly via Celery Beat.
    """
    async def _reconcile():
        from src.finance.reconciliation import payment_reconciler
        from config import settings

        results = {}
        platforms = settings.platforms.enabled

        for platform in platforms:
            try:
                # In production, this would fetch from platform API
                platform_transactions = await _fetch_platform_transactions(platform)

                result = await payment_reconciler.reconcile_platform_payments(
                    platform=platform,
                    platform_transactions=platform_transactions,
                )
                results[platform] = result

            except Exception as e:
                logger.error(f"Failed to reconcile {platform}: {e}")
                results[platform] = {"status": "error", "error": str(e)}

        return results

    try:
        return run_async(_reconcile())
    except Exception as exc:
        logger.error(f"reconcile_all_payments failed: {exc}")
        self.retry(exc=exc)


async def _fetch_platform_transactions(platform: str) -> list[dict]:
    """Fetch transactions from platform API"""
    # This would integrate with actual platform APIs
    # For now, return empty list
    return []


@shared_task(
    bind=True,
    name="src.tasks.finance.release_cleared_payments",
    max_retries=2,
    default_retry_delay=600,
)
def release_cleared_payments(self):
    """
    Release payments that have passed clearance period.

    Runs daily via Celery Beat.
    """
    async def _release():
        from src.finance.reconciliation import payment_reconciler

        # Platform clearance periods
        clearance_days = {
            "upwork": 10,
            "fiverr": 14,
            "freelancer": 15,
            "reddit": 0,  # Direct deals, no clearance
        }

        results = {}
        for platform, days in clearance_days.items():
            try:
                result = await payment_reconciler.release_cleared_payments(
                    platform=platform,
                    clearance_days=days,
                )
                results[platform] = result
            except Exception as e:
                logger.error(f"Failed to release payments for {platform}: {e}")
                results[platform] = {"status": "error", "error": str(e)}

        return results

    try:
        return run_async(_release())
    except Exception as exc:
        logger.error(f"release_cleared_payments failed: {exc}")
        self.retry(exc=exc)


@shared_task(
    bind=True,
    name="src.tasks.finance.process_withdrawal",
    max_retries=3,
    default_retry_delay=120,
)
def process_withdrawal(self, transaction_id: str):
    """
    Process a pending withdrawal.

    Args:
        transaction_id: The withdrawal transaction ID
    """
    async def _process():
        from uuid import UUID
        from src.finance.wallet import wallet_manager
        from src.finance.models import Transaction, WithdrawalMethod
        from src.core.database import db_manager
        from sqlalchemy import select

        async with db_manager.session() as session:
            result = await session.execute(
                select(Transaction).where(Transaction.id == UUID(transaction_id))
            )
            transaction = result.scalar_one_or_none()

            if not transaction:
                return {"status": "error", "error": "Transaction not found"}

            method = WithdrawalMethod(transaction.withdrawal_method)

        # Process based on method
        try:
            if method == WithdrawalMethod.PAYPAL:
                result = await _process_paypal_withdrawal(transaction)
            elif method == WithdrawalMethod.WISE:
                result = await _process_wise_withdrawal(transaction)
            elif method == WithdrawalMethod.BANK_TRANSFER:
                result = await _process_bank_withdrawal(transaction)
            elif method == WithdrawalMethod.CRYPTO:
                result = await _process_crypto_withdrawal(transaction)
            else:
                result = {"success": False, "error": "Unsupported method"}

            # Update transaction status
            await wallet_manager.process_withdrawal(
                transaction_id=UUID(transaction_id),
                success=result["success"],
                platform_transaction_id=result.get("reference"),
                error_message=result.get("error"),
            )

            return {
                "transaction_id": transaction_id,
                "status": "completed" if result["success"] else "failed",
                **result,
            }

        except Exception as e:
            await wallet_manager.process_withdrawal(
                transaction_id=UUID(transaction_id),
                success=False,
                error_message=str(e),
            )
            raise

    try:
        return run_async(_process())
    except Exception as exc:
        logger.error(f"process_withdrawal failed: {exc}")
        self.retry(exc=exc)


async def _process_paypal_withdrawal(transaction) -> dict:
    """Process PayPal withdrawal"""
    # Integration with PayPal Payouts API
    # This is a placeholder - implement actual PayPal integration
    logger.info(f"Processing PayPal withdrawal: {transaction.id}")
    return {
        "success": True,
        "reference": f"PP-{transaction.id}",
        "method": "paypal",
    }


async def _process_wise_withdrawal(transaction) -> dict:
    """Process Wise withdrawal"""
    # Integration with Wise API
    logger.info(f"Processing Wise withdrawal: {transaction.id}")
    return {
        "success": True,
        "reference": f"WISE-{transaction.id}",
        "method": "wise",
    }


async def _process_bank_withdrawal(transaction) -> dict:
    """Process bank transfer withdrawal"""
    # Integration with banking API (Stripe, etc.)
    logger.info(f"Processing bank withdrawal: {transaction.id}")
    return {
        "success": True,
        "reference": f"BANK-{transaction.id}",
        "method": "bank_transfer",
    }


async def _process_crypto_withdrawal(transaction) -> dict:
    """Process cryptocurrency withdrawal"""
    # Integration with crypto payment processor
    logger.info(f"Processing crypto withdrawal: {transaction.id}")
    return {
        "success": True,
        "reference": f"CRYPTO-{transaction.id}",
        "method": "crypto",
    }


@shared_task(
    name="src.tasks.finance.generate_daily_reports",
)
def generate_daily_reports():
    """
    Generate daily financial reports.

    Runs daily via Celery Beat.
    """
    async def _generate():
        from src.finance.reports import financial_reporter

        yesterday = datetime.utcnow() - timedelta(days=1)
        start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        # Generate system-wide report
        system_report = await financial_reporter.generate_system_report(
            start_date=start,
            end_date=end,
        )

        return {
            "date": start.isoformat(),
            "system_report": system_report,
        }

    return run_async(_generate())


@shared_task(
    name="src.tasks.finance.process_auto_withdrawals",
)
def process_auto_withdrawals():
    """
    Process auto-withdrawals for eligible agents.
    """
    async def _process():
        from src.finance.reconciliation import payment_reconciler
        from src.agents.manager import agent_manager

        agents = await agent_manager.get_active_agents()
        results = []

        for agent in agents:
            withdrawal = await payment_reconciler.auto_withdraw(agent.id)
            if withdrawal:
                # Queue for processing
                process_withdrawal.delay(str(withdrawal.id))
                results.append({
                    "agent_id": str(agent.id),
                    "withdrawal_id": str(withdrawal.id),
                    "amount": float(withdrawal.amount),
                })

        return {
            "processed": len(results),
            "withdrawals": results,
        }

    return run_async(_process())


@shared_task(
    name="src.tasks.finance.check_pending_payments",
)
def check_pending_payments():
    """
    Check for stuck pending payments.
    """
    async def _check():
        from src.finance.transactions import transaction_manager
        from src.finance.models import TransactionType

        # Find payments pending for too long
        pending = await transaction_manager.get_pending_transactions(
            transaction_type=TransactionType.EARNING,
            older_than_hours=720,  # 30 days
        )

        if pending:
            logger.warning(f"Found {len(pending)} stuck pending payments")

            # Emit alert
            from src.core.events import Event, event_bus
            await event_bus.emit(Event(
                type="finance.alert.stuck_payments",
                data={
                    "count": len(pending),
                    "transaction_ids": [str(t.id) for t in pending[:10]],
                },
            ))

        return {
            "stuck_count": len(pending),
            "transaction_ids": [str(t.id) for t in pending],
        }

    return run_async(_check())
