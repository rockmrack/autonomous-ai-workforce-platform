"""
Finance Database Models
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class TransactionType(str, Enum):
    """Types of financial transactions"""
    EARNING = "earning"           # Money earned from completed job
    WITHDRAWAL = "withdrawal"     # Withdrawal to external account
    PLATFORM_FEE = "platform_fee" # Platform fee deduction
    REFUND = "refund"            # Refund to client
    BONUS = "bonus"              # Bonus payment
    ADJUSTMENT = "adjustment"    # Manual adjustment
    TRANSFER = "transfer"        # Transfer between wallets


class TransactionStatus(str, Enum):
    """Transaction status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WithdrawalMethod(str, Enum):
    """Supported withdrawal methods"""
    BANK_TRANSFER = "bank_transfer"
    PAYPAL = "paypal"
    WISE = "wise"
    CRYPTO = "crypto"
    PLATFORM_BALANCE = "platform_balance"


class Wallet(Base):
    """Agent wallet for managing earnings"""
    __tablename__ = "wallets"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    agent_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # Balances
    available_balance: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00")
    )
    pending_balance: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00")
    )
    total_earned: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00")
    )
    total_withdrawn: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00")
    )
    total_fees: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00")
    )

    # Settings
    auto_withdraw_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_withdraw_threshold: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("100.00")
    )
    preferred_withdrawal_method: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    withdrawal_details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Metadata
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="wallet", lazy="dynamic"
    )

    __table_args__ = (
        Index("idx_wallet_agent", "agent_id"),
    )


class Transaction(Base):
    """Financial transaction record"""
    __tablename__ = "transactions"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    wallet_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Transaction details
    type: Mapped[TransactionType] = mapped_column(
        SQLEnum(TransactionType), nullable=False
    )
    status: Mapped[TransactionStatus] = mapped_column(
        SQLEnum(TransactionStatus), default=TransactionStatus.PENDING
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    net_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")

    # Reference information
    reference_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reference_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    job_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    platform: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    platform_transaction_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )

    # Withdrawal specific
    withdrawal_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    withdrawal_destination: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # Description and notes
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    wallet: Mapped["Wallet"] = relationship("Wallet", back_populates="transactions")

    __table_args__ = (
        Index("idx_transaction_wallet", "wallet_id"),
        Index("idx_transaction_type", "type"),
        Index("idx_transaction_status", "status"),
        Index("idx_transaction_created", "created_at"),
        Index("idx_transaction_job", "job_id"),
        Index("idx_transaction_platform", "platform", "platform_transaction_id"),
    )


class PaymentMethod(Base):
    """Saved payment methods for withdrawals"""
    __tablename__ = "payment_methods"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    wallet_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
    )

    method_type: Mapped[WithdrawalMethod] = mapped_column(
        SQLEnum(WithdrawalMethod), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Encrypted details (should use field-level encryption in production)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("idx_payment_method_wallet", "wallet_id"),
    )


class FinancialReport(Base):
    """Generated financial reports"""
    __tablename__ = "financial_reports"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    agent_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True  # Null for system-wide reports
    )

    report_type: Mapped[str] = mapped_column(String(50), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Summary data
    total_earnings: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    total_fees: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    total_withdrawals: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    net_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    jobs_completed: Mapped[int] = mapped_column(default=0)

    # Full report data
    report_data: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_report_agent", "agent_id"),
        Index("idx_report_period", "period_start", "period_end"),
        Index("idx_report_type", "report_type"),
    )
