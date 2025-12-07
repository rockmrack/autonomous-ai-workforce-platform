"""
Transaction Management - Track and manage all financial transactions
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select, func, and_

from src.core.database import db_manager
from .models import Transaction, TransactionType, TransactionStatus, Wallet

logger = structlog.get_logger(__name__)


class TransactionManager:
    """
    Manages financial transactions across the platform.

    Features:
    - Transaction queries and aggregations
    - Batch processing
    - Transaction statistics
    """

    async def get_transaction(self, transaction_id: UUID) -> Optional[Transaction]:
        """Get transaction by ID"""
        async with db_manager.session() as session:
            result = await session.execute(
                select(Transaction).where(Transaction.id == transaction_id)
            )
            return result.scalar_one_or_none()

    async def get_pending_transactions(
        self,
        transaction_type: Optional[TransactionType] = None,
        older_than_hours: Optional[int] = None,
    ) -> list[Transaction]:
        """Get all pending transactions"""
        async with db_manager.session() as session:
            query = select(Transaction).where(
                Transaction.status == TransactionStatus.PENDING
            )

            if transaction_type:
                query = query.where(Transaction.type == transaction_type)

            if older_than_hours:
                cutoff = datetime.utcnow() - timedelta(hours=older_than_hours)
                query = query.where(Transaction.created_at < cutoff)

            query = query.order_by(Transaction.created_at.asc())

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_transactions_by_job(self, job_id: UUID) -> list[Transaction]:
        """Get all transactions for a job"""
        async with db_manager.session() as session:
            result = await session.execute(
                select(Transaction)
                .where(Transaction.job_id == job_id)
                .order_by(Transaction.created_at.desc())
            )
            return list(result.scalars().all())

    async def get_transactions_by_platform(
        self,
        platform: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Get transactions by platform"""
        async with db_manager.session() as session:
            query = select(Transaction).where(Transaction.platform == platform)

            if start_date:
                query = query.where(Transaction.created_at >= start_date)
            if end_date:
                query = query.where(Transaction.created_at <= end_date)

            query = query.order_by(Transaction.created_at.desc())

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_daily_summary(
        self,
        date: Optional[datetime] = None,
    ) -> dict:
        """Get daily transaction summary"""
        if date is None:
            date = datetime.utcnow()

        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        async with db_manager.session() as session:
            # Earnings
            earnings_result = await session.execute(
                select(
                    func.count(Transaction.id).label("count"),
                    func.sum(Transaction.amount).label("gross"),
                    func.sum(Transaction.net_amount).label("net"),
                    func.sum(Transaction.fee).label("fees"),
                ).where(
                    and_(
                        Transaction.type == TransactionType.EARNING,
                        Transaction.created_at >= start_of_day,
                        Transaction.created_at < end_of_day,
                    )
                )
            )
            earnings = earnings_result.one()

            # Withdrawals
            withdrawals_result = await session.execute(
                select(
                    func.count(Transaction.id).label("count"),
                    func.sum(Transaction.amount).label("amount"),
                ).where(
                    and_(
                        Transaction.type == TransactionType.WITHDRAWAL,
                        Transaction.status == TransactionStatus.COMPLETED,
                        Transaction.completed_at >= start_of_day,
                        Transaction.completed_at < end_of_day,
                    )
                )
            )
            withdrawals = withdrawals_result.one()

            return {
                "date": start_of_day.isoformat(),
                "earnings": {
                    "count": earnings.count or 0,
                    "gross": float(earnings.gross or 0),
                    "net": float(earnings.net or 0),
                    "fees": float(earnings.fees or 0),
                },
                "withdrawals": {
                    "count": withdrawals.count or 0,
                    "amount": float(withdrawals.amount or 0),
                },
            }

    async def get_platform_summary(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict:
        """Get summary by platform"""
        async with db_manager.session() as session:
            query = select(
                Transaction.platform,
                func.count(Transaction.id).label("transaction_count"),
                func.sum(Transaction.amount).label("gross_amount"),
                func.sum(Transaction.net_amount).label("net_amount"),
                func.sum(Transaction.fee).label("total_fees"),
            ).where(
                Transaction.type == TransactionType.EARNING
            ).group_by(Transaction.platform)

            if start_date:
                query = query.where(Transaction.created_at >= start_date)
            if end_date:
                query = query.where(Transaction.created_at <= end_date)

            result = await session.execute(query)
            rows = result.all()

            return {
                row.platform: {
                    "transaction_count": row.transaction_count,
                    "gross_amount": float(row.gross_amount or 0),
                    "net_amount": float(row.net_amount or 0),
                    "total_fees": float(row.total_fees or 0),
                }
                for row in rows
                if row.platform
            }

    async def get_agent_stats(
        self,
        agent_id: UUID,
        days: int = 30,
    ) -> dict:
        """Get transaction statistics for an agent"""
        start_date = datetime.utcnow() - timedelta(days=days)

        async with db_manager.session() as session:
            # Get wallet
            wallet_result = await session.execute(
                select(Wallet).where(Wallet.agent_id == agent_id)
            )
            wallet = wallet_result.scalar_one_or_none()

            if not wallet:
                return {"error": "Wallet not found"}

            # Get period stats
            stats_result = await session.execute(
                select(
                    Transaction.type,
                    func.count(Transaction.id).label("count"),
                    func.sum(Transaction.net_amount).label("total"),
                ).where(
                    and_(
                        Transaction.wallet_id == wallet.id,
                        Transaction.created_at >= start_date,
                        Transaction.status == TransactionStatus.COMPLETED,
                    )
                ).group_by(Transaction.type)
            )

            stats_by_type = {
                row.type.value: {
                    "count": row.count,
                    "total": float(row.total or 0),
                }
                for row in stats_result.all()
            }

            # Get daily trend
            daily_result = await session.execute(
                select(
                    func.date_trunc("day", Transaction.created_at).label("day"),
                    func.sum(Transaction.net_amount).label("amount"),
                ).where(
                    and_(
                        Transaction.wallet_id == wallet.id,
                        Transaction.type == TransactionType.EARNING,
                        Transaction.created_at >= start_date,
                    )
                ).group_by(
                    func.date_trunc("day", Transaction.created_at)
                ).order_by(
                    func.date_trunc("day", Transaction.created_at)
                )
            )

            daily_earnings = [
                {"date": row.day.isoformat(), "amount": float(row.amount or 0)}
                for row in daily_result.all()
            ]

            return {
                "period_days": days,
                "by_type": stats_by_type,
                "daily_earnings": daily_earnings,
                "wallet_balance": {
                    "available": float(wallet.available_balance),
                    "pending": float(wallet.pending_balance),
                },
            }

    async def void_transaction(
        self,
        transaction_id: UUID,
        reason: str,
    ) -> Transaction:
        """Void a pending transaction"""
        async with db_manager.session() as session:
            result = await session.execute(
                select(Transaction)
                .where(Transaction.id == transaction_id)
                .with_for_update()
            )
            transaction = result.scalar_one_or_none()

            if not transaction:
                from src.core.exceptions import RecordNotFoundError
                raise RecordNotFoundError("Transaction", str(transaction_id))

            if transaction.status != TransactionStatus.PENDING:
                from src.core.exceptions import ValidationException
                raise ValidationException(
                    f"Cannot void transaction with status: {transaction.status.value}"
                )

            # Get wallet to reverse any balance changes
            wallet_result = await session.execute(
                select(Wallet).where(Wallet.id == transaction.wallet_id)
            )
            wallet = wallet_result.scalar_one()

            # Reverse based on transaction type
            if transaction.type == TransactionType.EARNING:
                wallet.pending_balance -= transaction.net_amount
                wallet.total_earned -= transaction.net_amount
                wallet.total_fees -= transaction.fee
            elif transaction.type == TransactionType.WITHDRAWAL:
                wallet.available_balance += transaction.amount

            transaction.status = TransactionStatus.CANCELLED
            transaction.notes = f"Voided: {reason}"

            await session.commit()

            logger.info(
                "Transaction voided",
                transaction_id=str(transaction_id),
                reason=reason,
            )

            return transaction


# Singleton instance
transaction_manager = TransactionManager()
