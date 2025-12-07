"""
Payment Reconciliation - Sync payments with platforms and handle discrepancies
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select, and_

from src.core.database import db_manager
from src.core.events import Event, event_bus
from .models import (
    Transaction,
    TransactionType,
    TransactionStatus,
    Wallet,
)
from .wallet import wallet_manager

logger = structlog.get_logger(__name__)


class PaymentReconciler:
    """
    Reconciles payments between platform and internal records.

    Features:
    - Sync with platform payment APIs
    - Detect missing/duplicate transactions
    - Auto-release cleared payments
    - Handle refunds and chargebacks
    """

    async def reconcile_platform_payments(
        self,
        platform: str,
        platform_transactions: list[dict],
    ) -> dict:
        """
        Reconcile platform transactions with internal records.

        Args:
            platform: Platform name (upwork, fiverr, etc.)
            platform_transactions: List of transactions from platform API
                Expected format: {
                    "id": "platform_tx_id",
                    "amount": 100.00,
                    "type": "payment",
                    "status": "completed",
                    "job_id": "platform_job_id",
                    "timestamp": "2024-01-15T12:00:00Z"
                }

        Returns:
            Reconciliation summary
        """
        matched = 0
        created = 0
        discrepancies = []

        async with db_manager.session() as session:
            for ptx in platform_transactions:
                # Find matching internal transaction
                result = await session.execute(
                    select(Transaction).where(
                        and_(
                            Transaction.platform == platform,
                            Transaction.platform_transaction_id == ptx["id"],
                        )
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # Verify amounts match
                    platform_amount = Decimal(str(ptx["amount"]))
                    if abs(existing.amount - platform_amount) > Decimal("0.01"):
                        discrepancies.append({
                            "type": "amount_mismatch",
                            "platform_tx_id": ptx["id"],
                            "internal_amount": float(existing.amount),
                            "platform_amount": float(platform_amount),
                        })

                    # Update status if needed
                    if ptx.get("status") == "completed" and existing.status == TransactionStatus.PENDING:
                        existing.status = TransactionStatus.COMPLETED
                        existing.completed_at = datetime.utcnow()

                        # Release pending balance
                        wallet_result = await session.execute(
                            select(Wallet).where(Wallet.id == existing.wallet_id)
                        )
                        wallet = wallet_result.scalar_one()

                        if existing.type == TransactionType.EARNING:
                            wallet.pending_balance -= existing.net_amount
                            wallet.available_balance += existing.net_amount

                    matched += 1
                else:
                    # Transaction exists on platform but not internally
                    # This could be a missed transaction - log for review
                    discrepancies.append({
                        "type": "missing_internal",
                        "platform_tx_id": ptx["id"],
                        "platform_amount": ptx["amount"],
                        "platform_job_id": ptx.get("job_id"),
                    })

            await session.commit()

        summary = {
            "platform": platform,
            "processed": len(platform_transactions),
            "matched": matched,
            "created": created,
            "discrepancies": len(discrepancies),
            "discrepancy_details": discrepancies[:10],  # Limit details
        }

        if discrepancies:
            logger.warning(
                "Payment reconciliation found discrepancies",
                platform=platform,
                count=len(discrepancies),
            )

            # Emit event for alerting
            await event_bus.emit(Event(
                type="finance.reconciliation.discrepancies",
                data=summary,
            ))

        return summary

    async def release_cleared_payments(
        self,
        platform: str,
        clearance_days: int = 14,
    ) -> dict:
        """
        Release payments that have been pending for clearance period.

        Different platforms have different clearance periods:
        - Upwork: 5-10 days
        - Fiverr: 14 days
        - Freelancer: 15 days
        """
        cutoff_date = datetime.utcnow() - timedelta(days=clearance_days)
        released_count = 0
        released_amount = Decimal("0.00")

        async with db_manager.session() as session:
            # Find pending earnings past clearance date
            result = await session.execute(
                select(Transaction).where(
                    and_(
                        Transaction.type == TransactionType.EARNING,
                        Transaction.status == TransactionStatus.PENDING,
                        Transaction.platform == platform,
                        Transaction.created_at <= cutoff_date,
                    )
                )
            )
            pending_transactions = result.scalars().all()

            for tx in pending_transactions:
                # Get wallet
                wallet_result = await session.execute(
                    select(Wallet).where(Wallet.id == tx.wallet_id)
                )
                wallet = wallet_result.scalar_one()

                # Move from pending to available
                wallet.pending_balance -= tx.net_amount
                wallet.available_balance += tx.net_amount

                tx.status = TransactionStatus.COMPLETED
                tx.completed_at = datetime.utcnow()
                tx.notes = f"Auto-released after {clearance_days} day clearance"

                released_count += 1
                released_amount += tx.net_amount

            await session.commit()

        logger.info(
            "Released cleared payments",
            platform=platform,
            count=released_count,
            amount=float(released_amount),
        )

        return {
            "platform": platform,
            "clearance_days": clearance_days,
            "released_count": released_count,
            "released_amount": float(released_amount),
        }

    async def handle_refund(
        self,
        job_id: UUID,
        refund_amount: Decimal,
        reason: str,
        platform_refund_id: Optional[str] = None,
    ) -> Transaction:
        """
        Handle a refund/chargeback for a job.

        Deducts from agent's available or pending balance.
        """
        async with db_manager.session() as session:
            # Find original earning transaction
            result = await session.execute(
                select(Transaction).where(
                    and_(
                        Transaction.job_id == job_id,
                        Transaction.type == TransactionType.EARNING,
                    )
                ).order_by(Transaction.created_at.desc())
            )
            original_tx = result.scalar_one_or_none()

            if not original_tx:
                raise ValueError(f"No earning transaction found for job {job_id}")

            # Get wallet
            wallet_result = await session.execute(
                select(Wallet).where(Wallet.id == original_tx.wallet_id)
            )
            wallet = wallet_result.scalar_one()

            # Create refund transaction
            refund_tx = Transaction(
                wallet_id=wallet.id,
                type=TransactionType.REFUND,
                status=TransactionStatus.COMPLETED,
                amount=refund_amount,
                fee=Decimal("0.00"),
                net_amount=-refund_amount,  # Negative for deduction
                job_id=job_id,
                platform=original_tx.platform,
                platform_transaction_id=platform_refund_id,
                description=f"Refund: {reason}",
                completed_at=datetime.utcnow(),
            )
            session.add(refund_tx)

            # Deduct from balance
            if wallet.available_balance >= refund_amount:
                wallet.available_balance -= refund_amount
            elif wallet.pending_balance >= refund_amount:
                wallet.pending_balance -= refund_amount
            else:
                # Split between available and pending, or go negative
                deduct_available = min(wallet.available_balance, refund_amount)
                deduct_pending = refund_amount - deduct_available
                wallet.available_balance -= deduct_available
                wallet.pending_balance -= deduct_pending

            wallet.total_earned -= refund_amount

            await session.commit()

            logger.warning(
                "Processed refund",
                job_id=str(job_id),
                amount=float(refund_amount),
                reason=reason,
            )

            # Emit event
            await event_bus.emit(Event(
                type="finance.refund.processed",
                data={
                    "job_id": str(job_id),
                    "amount": float(refund_amount),
                    "reason": reason,
                },
            ))

            return refund_tx

    async def auto_withdraw(
        self,
        agent_id: UUID,
    ) -> Optional[Transaction]:
        """
        Process auto-withdrawal if threshold is met.
        """
        async with db_manager.session() as session:
            # Get wallet
            wallet_result = await session.execute(
                select(Wallet).where(Wallet.agent_id == agent_id)
            )
            wallet = wallet_result.scalar_one_or_none()

            if not wallet:
                return None

            if not wallet.auto_withdraw_enabled:
                return None

            if wallet.available_balance < wallet.auto_withdraw_threshold:
                return None

            if not wallet.preferred_withdrawal_method or not wallet.withdrawal_details:
                logger.warning(
                    "Auto-withdrawal enabled but no payment method configured",
                    agent_id=str(agent_id),
                )
                return None

        # Process withdrawal
        from .wallet import wallet_manager, WithdrawalMethod

        try:
            method = WithdrawalMethod(wallet.preferred_withdrawal_method)
            destination = wallet.withdrawal_details.get("destination", "")

            withdrawal = await wallet_manager.request_withdrawal(
                agent_id=agent_id,
                amount=wallet.available_balance,
                method=method,
                destination=destination,
                notes="Auto-withdrawal",
            )

            logger.info(
                "Auto-withdrawal requested",
                agent_id=str(agent_id),
                amount=float(wallet.available_balance),
            )

            return withdrawal

        except Exception as e:
            logger.error(
                "Auto-withdrawal failed",
                agent_id=str(agent_id),
                error=str(e),
            )
            return None

    async def get_reconciliation_status(self) -> dict:
        """Get overall reconciliation status"""
        async with db_manager.session() as session:
            # Pending transactions count
            pending_result = await session.execute(
                select(
                    Transaction.platform,
                    Transaction.type,
                    func.count(Transaction.id).label("count"),
                    func.sum(Transaction.net_amount).label("amount"),
                ).where(
                    Transaction.status == TransactionStatus.PENDING
                ).group_by(
                    Transaction.platform,
                    Transaction.type,
                )
            )

            from sqlalchemy import func

            pending_by_platform = {}
            for row in pending_result.all():
                platform = row.platform or "unknown"
                if platform not in pending_by_platform:
                    pending_by_platform[platform] = {}
                pending_by_platform[platform][row.type.value] = {
                    "count": row.count,
                    "amount": float(row.amount or 0),
                }

            # Old pending (potential issues)
            old_pending_cutoff = datetime.utcnow() - timedelta(days=30)
            old_pending_result = await session.execute(
                select(func.count(Transaction.id)).where(
                    and_(
                        Transaction.status == TransactionStatus.PENDING,
                        Transaction.created_at < old_pending_cutoff,
                    )
                )
            )
            old_pending_count = old_pending_result.scalar() or 0

            return {
                "pending_by_platform": pending_by_platform,
                "old_pending_count": old_pending_count,
                "requires_attention": old_pending_count > 0,
            }


# Singleton instance
payment_reconciler = PaymentReconciler()
