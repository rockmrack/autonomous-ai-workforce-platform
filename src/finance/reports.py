"""
Financial Reporting - Generate reports and analytics
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select, func, and_

from src.core.database import db_manager
from .models import (
    Transaction,
    TransactionType,
    TransactionStatus,
    Wallet,
    FinancialReport,
)

logger = structlog.get_logger(__name__)


class FinancialReporter:
    """
    Generates financial reports and analytics.

    Features:
    - Period-based reports (daily, weekly, monthly)
    - Agent performance reports
    - Platform comparison reports
    - Revenue forecasting
    """

    async def generate_agent_report(
        self,
        agent_id: UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> dict:
        """Generate comprehensive financial report for an agent"""
        async with db_manager.session() as session:
            # Get wallet
            wallet_result = await session.execute(
                select(Wallet).where(Wallet.agent_id == agent_id)
            )
            wallet = wallet_result.scalar_one_or_none()

            if not wallet:
                return {"error": "Wallet not found", "agent_id": str(agent_id)}

            # Get earnings summary
            earnings_result = await session.execute(
                select(
                    func.count(Transaction.id).label("count"),
                    func.sum(Transaction.amount).label("gross"),
                    func.sum(Transaction.net_amount).label("net"),
                    func.sum(Transaction.fee).label("fees"),
                ).where(
                    and_(
                        Transaction.wallet_id == wallet.id,
                        Transaction.type == TransactionType.EARNING,
                        Transaction.created_at >= start_date,
                        Transaction.created_at <= end_date,
                    )
                )
            )
            earnings = earnings_result.one()

            # Get withdrawals summary
            withdrawals_result = await session.execute(
                select(
                    func.count(Transaction.id).label("count"),
                    func.sum(Transaction.amount).label("amount"),
                    func.sum(Transaction.fee).label("fees"),
                ).where(
                    and_(
                        Transaction.wallet_id == wallet.id,
                        Transaction.type == TransactionType.WITHDRAWAL,
                        Transaction.status == TransactionStatus.COMPLETED,
                        Transaction.completed_at >= start_date,
                        Transaction.completed_at <= end_date,
                    )
                )
            )
            withdrawals = withdrawals_result.one()

            # Get earnings by platform
            platform_result = await session.execute(
                select(
                    Transaction.platform,
                    func.count(Transaction.id).label("jobs"),
                    func.sum(Transaction.net_amount).label("earnings"),
                ).where(
                    and_(
                        Transaction.wallet_id == wallet.id,
                        Transaction.type == TransactionType.EARNING,
                        Transaction.created_at >= start_date,
                        Transaction.created_at <= end_date,
                    )
                ).group_by(Transaction.platform)
            )
            by_platform = {
                row.platform: {
                    "jobs": row.jobs,
                    "earnings": float(row.earnings or 0),
                }
                for row in platform_result.all()
                if row.platform
            }

            # Get daily breakdown
            daily_result = await session.execute(
                select(
                    func.date_trunc("day", Transaction.created_at).label("day"),
                    func.count(Transaction.id).label("count"),
                    func.sum(Transaction.net_amount).label("amount"),
                ).where(
                    and_(
                        Transaction.wallet_id == wallet.id,
                        Transaction.type == TransactionType.EARNING,
                        Transaction.created_at >= start_date,
                        Transaction.created_at <= end_date,
                    )
                ).group_by(
                    func.date_trunc("day", Transaction.created_at)
                ).order_by(
                    func.date_trunc("day", Transaction.created_at)
                )
            )
            daily_breakdown = [
                {
                    "date": row.day.isoformat() if row.day else None,
                    "jobs": row.count,
                    "earnings": float(row.amount or 0),
                }
                for row in daily_result.all()
            ]

            report_data = {
                "agent_id": str(agent_id),
                "period": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                },
                "summary": {
                    "total_jobs": earnings.count or 0,
                    "gross_earnings": float(earnings.gross or 0),
                    "net_earnings": float(earnings.net or 0),
                    "platform_fees": float(earnings.fees or 0),
                    "withdrawals": float(withdrawals.amount or 0),
                    "withdrawal_fees": float(withdrawals.fees or 0),
                },
                "by_platform": by_platform,
                "daily_breakdown": daily_breakdown,
                "current_balance": {
                    "available": float(wallet.available_balance),
                    "pending": float(wallet.pending_balance),
                },
            }

            # Save report
            report = FinancialReport(
                agent_id=agent_id,
                report_type="agent_financial",
                period_start=start_date,
                period_end=end_date,
                total_earnings=Decimal(str(earnings.net or 0)),
                total_fees=Decimal(str(earnings.fees or 0)),
                total_withdrawals=Decimal(str(withdrawals.amount or 0)),
                net_revenue=Decimal(str((earnings.net or 0) - (withdrawals.amount or 0))),
                jobs_completed=earnings.count or 0,
                report_data=report_data,
            )
            session.add(report)
            await session.commit()

            logger.info(
                "Generated agent financial report",
                agent_id=str(agent_id),
                period_days=(end_date - start_date).days,
            )

            return report_data

    async def generate_system_report(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> dict:
        """Generate system-wide financial report"""
        async with db_manager.session() as session:
            # Overall earnings
            earnings_result = await session.execute(
                select(
                    func.count(Transaction.id).label("count"),
                    func.sum(Transaction.amount).label("gross"),
                    func.sum(Transaction.net_amount).label("net"),
                    func.sum(Transaction.fee).label("fees"),
                ).where(
                    and_(
                        Transaction.type == TransactionType.EARNING,
                        Transaction.created_at >= start_date,
                        Transaction.created_at <= end_date,
                    )
                )
            )
            earnings = earnings_result.one()

            # By platform
            platform_result = await session.execute(
                select(
                    Transaction.platform,
                    func.count(Transaction.id).label("jobs"),
                    func.sum(Transaction.amount).label("gross"),
                    func.sum(Transaction.net_amount).label("net"),
                ).where(
                    and_(
                        Transaction.type == TransactionType.EARNING,
                        Transaction.created_at >= start_date,
                        Transaction.created_at <= end_date,
                    )
                ).group_by(Transaction.platform)
            )
            by_platform = {
                row.platform: {
                    "jobs": row.jobs,
                    "gross": float(row.gross or 0),
                    "net": float(row.net or 0),
                }
                for row in platform_result.all()
                if row.platform
            }

            # Top agents
            top_agents_result = await session.execute(
                select(
                    Wallet.agent_id,
                    func.sum(Transaction.net_amount).label("earnings"),
                    func.count(Transaction.id).label("jobs"),
                ).join(
                    Wallet, Transaction.wallet_id == Wallet.id
                ).where(
                    and_(
                        Transaction.type == TransactionType.EARNING,
                        Transaction.created_at >= start_date,
                        Transaction.created_at <= end_date,
                    )
                ).group_by(
                    Wallet.agent_id
                ).order_by(
                    func.sum(Transaction.net_amount).desc()
                ).limit(10)
            )
            top_agents = [
                {
                    "agent_id": str(row.agent_id),
                    "earnings": float(row.earnings or 0),
                    "jobs": row.jobs,
                }
                for row in top_agents_result.all()
            ]

            # Daily trend
            daily_result = await session.execute(
                select(
                    func.date_trunc("day", Transaction.created_at).label("day"),
                    func.sum(Transaction.net_amount).label("amount"),
                    func.count(Transaction.id).label("count"),
                ).where(
                    and_(
                        Transaction.type == TransactionType.EARNING,
                        Transaction.created_at >= start_date,
                        Transaction.created_at <= end_date,
                    )
                ).group_by(
                    func.date_trunc("day", Transaction.created_at)
                ).order_by(
                    func.date_trunc("day", Transaction.created_at)
                )
            )
            daily_trend = [
                {
                    "date": row.day.isoformat() if row.day else None,
                    "earnings": float(row.amount or 0),
                    "jobs": row.count,
                }
                for row in daily_result.all()
            ]

            report_data = {
                "period": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                },
                "summary": {
                    "total_jobs": earnings.count or 0,
                    "gross_earnings": float(earnings.gross or 0),
                    "net_earnings": float(earnings.net or 0),
                    "platform_fees": float(earnings.fees or 0),
                },
                "by_platform": by_platform,
                "top_agents": top_agents,
                "daily_trend": daily_trend,
            }

            # Calculate averages
            days = (end_date - start_date).days or 1
            report_data["averages"] = {
                "daily_earnings": float((earnings.net or 0) / days),
                "jobs_per_day": (earnings.count or 0) / days,
                "avg_job_value": float((earnings.net or 0) / (earnings.count or 1)),
            }

            # Save report
            report = FinancialReport(
                report_type="system_financial",
                period_start=start_date,
                period_end=end_date,
                total_earnings=Decimal(str(earnings.net or 0)),
                total_fees=Decimal(str(earnings.fees or 0)),
                jobs_completed=earnings.count or 0,
                report_data=report_data,
            )
            session.add(report)
            await session.commit()

            logger.info(
                "Generated system financial report",
                period_days=days,
                total_earnings=float(earnings.net or 0),
            )

            return report_data

    async def get_revenue_forecast(
        self,
        days_ahead: int = 30,
        agent_id: Optional[UUID] = None,
    ) -> dict:
        """
        Forecast revenue based on historical data.

        Uses simple moving average with trend adjustment.
        """
        # Get last 90 days of data for forecasting
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=90)

        async with db_manager.session() as session:
            query = select(
                func.date_trunc("day", Transaction.created_at).label("day"),
                func.sum(Transaction.net_amount).label("amount"),
            ).where(
                and_(
                    Transaction.type == TransactionType.EARNING,
                    Transaction.created_at >= start_date,
                    Transaction.created_at <= end_date,
                )
            )

            if agent_id:
                wallet_result = await session.execute(
                    select(Wallet.id).where(Wallet.agent_id == agent_id)
                )
                wallet_id = wallet_result.scalar_one_or_none()
                if wallet_id:
                    query = query.where(Transaction.wallet_id == wallet_id)

            query = query.group_by(
                func.date_trunc("day", Transaction.created_at)
            ).order_by(
                func.date_trunc("day", Transaction.created_at)
            )

            result = await session.execute(query)
            daily_data = [
                {"date": row.day, "amount": float(row.amount or 0)}
                for row in result.all()
            ]

        if not daily_data:
            return {
                "forecast": [],
                "confidence": "low",
                "message": "Insufficient historical data",
            }

        # Calculate moving averages
        amounts = [d["amount"] for d in daily_data]

        # 7-day and 30-day moving averages
        ma_7 = sum(amounts[-7:]) / min(7, len(amounts)) if amounts else 0
        ma_30 = sum(amounts[-30:]) / min(30, len(amounts)) if amounts else 0

        # Calculate trend (comparing recent to older period)
        if len(amounts) >= 14:
            recent_avg = sum(amounts[-7:]) / 7
            older_avg = sum(amounts[-14:-7]) / 7
            trend = (recent_avg - older_avg) / older_avg if older_avg else 0
        else:
            trend = 0

        # Generate forecast
        forecast = []
        base_value = ma_7  # Use 7-day MA as base
        daily_trend = trend / 7  # Daily trend rate

        for i in range(1, days_ahead + 1):
            forecast_date = end_date + timedelta(days=i)
            # Apply dampened trend
            trend_factor = 1 + (daily_trend * (1 - i / (days_ahead * 2)))
            forecasted_value = base_value * trend_factor

            # Add some bounds
            forecasted_value = max(0, min(forecasted_value, ma_30 * 3))

            forecast.append({
                "date": forecast_date.isoformat(),
                "predicted_earnings": round(forecasted_value, 2),
            })

        total_forecast = sum(f["predicted_earnings"] for f in forecast)

        return {
            "forecast": forecast,
            "summary": {
                "total_predicted": round(total_forecast, 2),
                "daily_average": round(total_forecast / days_ahead, 2),
                "trend": "up" if trend > 0.05 else "down" if trend < -0.05 else "stable",
                "trend_percentage": round(trend * 100, 1),
            },
            "confidence": "high" if len(amounts) >= 60 else "medium" if len(amounts) >= 30 else "low",
            "based_on_days": len(amounts),
        }

    async def get_saved_reports(
        self,
        report_type: Optional[str] = None,
        agent_id: Optional[UUID] = None,
        limit: int = 10,
    ) -> list[FinancialReport]:
        """Get previously generated reports"""
        async with db_manager.session() as session:
            query = select(FinancialReport).order_by(
                FinancialReport.created_at.desc()
            )

            if report_type:
                query = query.where(FinancialReport.report_type == report_type)
            if agent_id:
                query = query.where(FinancialReport.agent_id == agent_id)

            query = query.limit(limit)

            result = await session.execute(query)
            return list(result.scalars().all())


# Singleton instance
financial_reporter = FinancialReporter()
