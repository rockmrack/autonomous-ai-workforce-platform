"""
Wallet Management - Handle agent earnings and balances
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import db_manager
from src.core.exceptions import (
    RecordNotFoundError,
    InvalidInputError,
    ValidationException,
)
from .models import (
    Wallet,
    Transaction,
    TransactionType,
    TransactionStatus,
    PaymentMethod,
    WithdrawalMethod,
)

logger = structlog.get_logger(__name__)


class WalletManager:
    """
    Manages agent wallets and balance operations.

    Features:
    - Balance tracking (available, pending, total)
    - Automatic wallet creation for agents
    - Thread-safe balance updates
    - Withdrawal management
    """

    async def get_or_create_wallet(
        self,
        agent_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Wallet:
        """Get existing wallet or create new one for agent"""
        async def _operation(s: AsyncSession) -> Wallet:
            result = await s.execute(
                select(Wallet).where(Wallet.agent_id == agent_id)
            )
            wallet = result.scalar_one_or_none()

            if not wallet:
                wallet = Wallet(agent_id=agent_id)
                s.add(wallet)
                await s.flush()
                logger.info("Created wallet for agent", agent_id=str(agent_id))

            return wallet

        if session:
            return await _operation(session)

        async with db_manager.session() as s:
            result = await _operation(s)
            await s.commit()
            return result

    async def get_wallet(self, agent_id: UUID) -> Wallet:
        """Get wallet for agent, raises if not found"""
        async with db_manager.session() as session:
            result = await session.execute(
                select(Wallet).where(Wallet.agent_id == agent_id)
            )
            wallet = result.scalar_one_or_none()

            if not wallet:
                raise RecordNotFoundError("Wallet", str(agent_id))

            return wallet

    async def get_balance(self, agent_id: UUID) -> dict:
        """Get wallet balance summary"""
        wallet = await self.get_wallet(agent_id)

        return {
            "available": float(wallet.available_balance),
            "pending": float(wallet.pending_balance),
            "total_earned": float(wallet.total_earned),
            "total_withdrawn": float(wallet.total_withdrawn),
            "total_fees": float(wallet.total_fees),
            "currency": wallet.currency,
        }

    async def add_earnings(
        self,
        agent_id: UUID,
        amount: Decimal,
        job_id: UUID,
        platform: str,
        platform_transaction_id: Optional[str] = None,
        description: Optional[str] = None,
        pending: bool = True,
    ) -> Transaction:
        """
        Add earnings to wallet.

        Args:
            agent_id: Agent's ID
            amount: Gross earnings amount
            job_id: Associated job ID
            platform: Platform where job was completed
            platform_transaction_id: Platform's transaction reference
            description: Transaction description
            pending: If True, add to pending balance (awaiting clearance)
        """
        if amount <= 0:
            raise InvalidInputError("amount", "Must be positive", amount)

        async with db_manager.session() as session:
            wallet = await self.get_or_create_wallet(agent_id, session)

            # Calculate platform fee (typically 5-20% depending on platform)
            fee_rate = self._get_platform_fee_rate(platform)
            fee = (amount * Decimal(str(fee_rate))).quantize(Decimal("0.01"))
            net_amount = amount - fee

            # Create transaction
            transaction = Transaction(
                wallet_id=wallet.id,
                type=TransactionType.EARNING,
                status=TransactionStatus.PENDING if pending else TransactionStatus.COMPLETED,
                amount=amount,
                fee=fee,
                net_amount=net_amount,
                job_id=job_id,
                platform=platform,
                platform_transaction_id=platform_transaction_id,
                description=description or f"Earnings from {platform} job",
            )
            session.add(transaction)

            # Update wallet balance
            if pending:
                wallet.pending_balance += net_amount
            else:
                wallet.available_balance += net_amount
                transaction.completed_at = datetime.utcnow()

            wallet.total_earned += net_amount
            wallet.total_fees += fee

            await session.commit()

            logger.info(
                "Added earnings",
                agent_id=str(agent_id),
                amount=float(amount),
                fee=float(fee),
                net=float(net_amount),
                pending=pending,
            )

            return transaction

    async def release_pending(
        self,
        agent_id: UUID,
        transaction_id: UUID,
    ) -> Transaction:
        """Release pending earnings to available balance"""
        async with db_manager.session() as session:
            # Get transaction
            result = await session.execute(
                select(Transaction).where(Transaction.id == transaction_id)
            )
            transaction = result.scalar_one_or_none()

            if not transaction:
                raise RecordNotFoundError("Transaction", str(transaction_id))

            if transaction.status != TransactionStatus.PENDING:
                raise ValidationException(
                    f"Transaction is not pending: {transaction.status.value}"
                )

            # Get wallet
            wallet = await self.get_or_create_wallet(agent_id, session)

            if wallet.id != transaction.wallet_id:
                raise ValidationException("Transaction does not belong to this wallet")

            # Move from pending to available
            wallet.pending_balance -= transaction.net_amount
            wallet.available_balance += transaction.net_amount

            transaction.status = TransactionStatus.COMPLETED
            transaction.completed_at = datetime.utcnow()

            await session.commit()

            logger.info(
                "Released pending earnings",
                agent_id=str(agent_id),
                transaction_id=str(transaction_id),
                amount=float(transaction.net_amount),
            )

            return transaction

    async def request_withdrawal(
        self,
        agent_id: UUID,
        amount: Decimal,
        method: WithdrawalMethod,
        destination: str,
        notes: Optional[str] = None,
    ) -> Transaction:
        """
        Request withdrawal from available balance.

        Args:
            agent_id: Agent's ID
            amount: Amount to withdraw
            method: Withdrawal method
            destination: Destination account/address
            notes: Optional notes
        """
        if amount <= 0:
            raise InvalidInputError("amount", "Must be positive", amount)

        async with db_manager.session() as session:
            wallet = await self.get_or_create_wallet(agent_id, session)

            if amount > wallet.available_balance:
                raise ValidationException(
                    f"Insufficient balance. Available: {wallet.available_balance}, "
                    f"Requested: {amount}"
                )

            # Calculate withdrawal fee
            fee = self._calculate_withdrawal_fee(method, amount)
            net_amount = amount - fee

            # Create withdrawal transaction
            transaction = Transaction(
                wallet_id=wallet.id,
                type=TransactionType.WITHDRAWAL,
                status=TransactionStatus.PENDING,
                amount=amount,
                fee=fee,
                net_amount=net_amount,
                withdrawal_method=method.value,
                withdrawal_destination=destination,
                description=f"Withdrawal via {method.value}",
                notes=notes,
            )
            session.add(transaction)

            # Deduct from available (held until processed)
            wallet.available_balance -= amount

            await session.commit()

            logger.info(
                "Withdrawal requested",
                agent_id=str(agent_id),
                amount=float(amount),
                method=method.value,
                fee=float(fee),
            )

            return transaction

    async def process_withdrawal(
        self,
        transaction_id: UUID,
        success: bool,
        platform_transaction_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Transaction:
        """Process a pending withdrawal"""
        async with db_manager.session() as session:
            result = await session.execute(
                select(Transaction)
                .where(Transaction.id == transaction_id)
                .with_for_update()
            )
            transaction = result.scalar_one_or_none()

            if not transaction:
                raise RecordNotFoundError("Transaction", str(transaction_id))

            if transaction.type != TransactionType.WITHDRAWAL:
                raise ValidationException("Transaction is not a withdrawal")

            if transaction.status != TransactionStatus.PENDING:
                raise ValidationException(
                    f"Withdrawal already processed: {transaction.status.value}"
                )

            # Get wallet
            result = await session.execute(
                select(Wallet).where(Wallet.id == transaction.wallet_id)
            )
            wallet = result.scalar_one()

            if success:
                transaction.status = TransactionStatus.COMPLETED
                transaction.platform_transaction_id = platform_transaction_id
                transaction.completed_at = datetime.utcnow()
                wallet.total_withdrawn += transaction.net_amount
                wallet.total_fees += transaction.fee

                logger.info(
                    "Withdrawal completed",
                    transaction_id=str(transaction_id),
                    amount=float(transaction.net_amount),
                )
            else:
                # Refund the amount back to available
                transaction.status = TransactionStatus.FAILED
                transaction.notes = error_message
                wallet.available_balance += transaction.amount

                logger.warning(
                    "Withdrawal failed",
                    transaction_id=str(transaction_id),
                    error=error_message,
                )

            await session.commit()
            return transaction

    async def get_transactions(
        self,
        agent_id: UUID,
        transaction_type: Optional[TransactionType] = None,
        status: Optional[TransactionStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Transaction]:
        """Get transactions for an agent's wallet"""
        wallet = await self.get_wallet(agent_id)

        async with db_manager.session() as session:
            query = (
                select(Transaction)
                .where(Transaction.wallet_id == wallet.id)
                .order_by(Transaction.created_at.desc())
            )

            if transaction_type:
                query = query.where(Transaction.type == transaction_type)
            if status:
                query = query.where(Transaction.status == status)

            query = query.limit(limit).offset(offset)

            result = await session.execute(query)
            return list(result.scalars().all())

    def _get_platform_fee_rate(self, platform: str) -> float:
        """Get platform fee rate"""
        rates = {
            "upwork": 0.10,  # 10%
            "fiverr": 0.20,  # 20%
            "freelancer": 0.10,
            "reddit": 0.0,  # Direct deals
        }
        return rates.get(platform.lower(), 0.10)

    def _calculate_withdrawal_fee(
        self,
        method: WithdrawalMethod,
        amount: Decimal,
    ) -> Decimal:
        """Calculate withdrawal fee based on method"""
        fees = {
            WithdrawalMethod.BANK_TRANSFER: Decimal("5.00"),
            WithdrawalMethod.PAYPAL: amount * Decimal("0.025"),  # 2.5%
            WithdrawalMethod.WISE: amount * Decimal("0.01"),  # 1%
            WithdrawalMethod.CRYPTO: Decimal("2.00"),
            WithdrawalMethod.PLATFORM_BALANCE: Decimal("0.00"),
        }
        fee = fees.get(method, Decimal("5.00"))
        return fee.quantize(Decimal("0.01"))


# Singleton instance
wallet_manager = WalletManager()
