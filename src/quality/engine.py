"""
Quality Engine
Central orchestrator for all quality assurance processes
"""

import asyncio
import hashlib
import uuid
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import select

from src.core.database import db_manager
from src.core.events import event_bus
from src.core.cache import cache_manager
from src.quality.models import (
    QualityReport,
    QualityCheck,
    QualityThreshold,
    QualityCheckType,
    QualityStatus,
)
from src.quality.checkers import (
    CheckResult,
    GrammarChecker,
    SpellingChecker,
    ReadabilityChecker,
    ContentQualityChecker,
    CodeQualityChecker,
    PlagiarismChecker,
)

logger = structlog.get_logger(__name__)


class QualityEngine:
    """
    Central quality assurance engine.

    Features:
    - Multi-check orchestration
    - Configurable thresholds per client/content type
    - Automatic approval for high-quality content
    - Detailed reporting and suggestions
    - Caching for repeated checks
    """

    def __init__(self):
        self.checkers = {
            "writing": [
                GrammarChecker(),
                SpellingChecker(),
                ReadabilityChecker(),
                ContentQualityChecker(),
                PlagiarismChecker(),
            ],
            "code": [
                CodeQualityChecker(),
            ],
            "data": [],  # Data-specific checkers
        }

        # Default thresholds
        self.default_thresholds = {
            "min_overall_score": 80.0,
            "min_grammar_score": 90.0,
            "min_spelling_score": 95.0,
            "min_readability_score": 70.0,
            "min_originality_score": 85.0,
            "min_ai_human_score": 60.0,
            "min_code_syntax_score": 100.0,
            "min_code_style_score": 80.0,
            "min_code_security_score": 90.0,
        }

    async def run_quality_check(
        self,
        content: str,
        content_type: str,
        job_id: uuid.UUID,
        agent_id: uuid.UUID,
        client_id: Optional[str] = None,
        extra_checks: Optional[list[str]] = None,
    ) -> QualityReport:
        """
        Run comprehensive quality check on content.

        Args:
            content: The content to check
            content_type: Type of content (writing, code, data)
            job_id: Associated job ID
            agent_id: Agent who created the content
            client_id: Optional client ID for custom thresholds
            extra_checks: Additional checks to run
        """
        logger.info(
            "Starting quality check",
            content_type=content_type,
            job_id=str(job_id),
            content_length=len(content),
        )

        # Get thresholds
        thresholds = await self._get_thresholds(client_id, content_type)

        # Create report
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        async with db_manager.session() as session:
            report = QualityReport(
                job_id=job_id,
                agent_id=agent_id,
                content_hash=content_hash,
                content_type=content_type,
                content_length=len(content),
                status=QualityStatus.RUNNING,
                started_at=datetime.utcnow(),
            )
            session.add(report)
            await session.flush()

            # Get checkers for content type
            checkers = self.checkers.get(content_type, [])

            # Run all checks in parallel
            check_results = await asyncio.gather(
                *[checker.check(content) for checker in checkers],
                return_exceptions=True,
            )

            # Process results
            checks_passed = 0
            checks_failed = 0
            checks_warnings = 0
            all_issues = []
            all_suggestions = []
            checks_run = []

            for i, result in enumerate(check_results):
                if isinstance(result, Exception):
                    logger.error("Check failed", error=str(result))
                    checks_failed += 1
                    continue

                if not isinstance(result, CheckResult):
                    continue

                # Create check record
                check = QualityCheck(
                    report_id=report.id,
                    check_type=result.check_type,
                    check_name=result.check_name,
                    status=result.status,
                    score=result.score,
                    threshold=checkers[i].default_threshold,
                    passed=result.passed,
                    message=result.message,
                    issues=result.issues,
                    metadata=result.metadata,
                    duration_ms=result.duration_ms,
                )
                session.add(check)

                checks_run.append(result.check_name)

                if result.status == QualityStatus.PASSED:
                    checks_passed += 1
                elif result.status == QualityStatus.FAILED:
                    checks_failed += 1
                else:
                    checks_warnings += 1

                # Collect issues
                all_issues.extend(result.issues)

                # Update specific scores on report
                self._update_report_scores(report, result)

            # Calculate overall score
            report.overall_score = self._calculate_overall_score(report, content_type)
            report.checks_run = checks_run
            report.checks_passed = checks_passed
            report.checks_failed = checks_failed
            report.checks_warnings = checks_warnings
            report.issues_found = all_issues
            report.completed_at = datetime.utcnow()
            report.duration_seconds = (
                report.completed_at - report.started_at
            ).total_seconds()

            # Determine final status
            if checks_failed > 0:
                report.status = QualityStatus.FAILED
            elif checks_warnings > 0:
                report.status = QualityStatus.WARNING
            else:
                report.status = QualityStatus.PASSED

            # Check for auto-approval
            report.auto_approved = await self._check_auto_approval(
                report, thresholds
            )
            report.manual_review_required = not report.auto_approved

            # Generate suggestions
            report.suggestions = await self._generate_suggestions(
                content, content_type, all_issues
            )

            await session.commit()

            logger.info(
                "Quality check complete",
                report_id=str(report.id),
                status=report.status.value,
                score=report.overall_score,
                auto_approved=report.auto_approved,
            )

            # Emit event
            await event_bus.emit(
                "quality.check_complete",
                {
                    "report_id": str(report.id),
                    "job_id": str(job_id),
                    "status": report.status.value,
                    "score": report.overall_score,
                    "auto_approved": report.auto_approved,
                },
            )

            return report

    async def quick_check(
        self,
        content: str,
        content_type: str = "writing",
    ) -> dict:
        """
        Run a quick quality check without database storage.
        Useful for preview/editing workflow.
        """
        checkers = self.checkers.get(content_type, [])[:3]  # First 3 checkers only

        results = await asyncio.gather(
            *[checker.check(content) for checker in checkers],
            return_exceptions=True,
        )

        scores = []
        issues = []

        for result in results:
            if isinstance(result, CheckResult):
                scores.append(result.score)
                issues.extend(result.issues)

        overall_score = sum(scores) / max(len(scores), 1)

        return {
            "score": overall_score,
            "passed": overall_score >= 70,
            "issue_count": len(issues),
            "top_issues": issues[:5],
        }

    async def get_improvement_suggestions(
        self,
        content: str,
        content_type: str,
        issues: list[dict],
    ) -> list[str]:
        """
        Generate actionable improvement suggestions based on issues.
        """
        return await self._generate_suggestions(content, content_type, issues)

    async def _get_thresholds(
        self,
        client_id: Optional[str],
        content_type: str,
    ) -> dict:
        """Get quality thresholds for client/content type"""
        if client_id:
            # Check for client-specific thresholds
            cache_key = f"thresholds:{client_id}:{content_type}"
            cached = await cache_manager.get(cache_key)
            if cached:
                return cached

            async with db_manager.session() as session:
                result = await session.execute(
                    select(QualityThreshold)
                    .where(
                        QualityThreshold.client_id == client_id,
                        QualityThreshold.content_type == content_type,
                        QualityThreshold.is_active == True,
                    )
                    .limit(1)
                )
                threshold = result.scalar_one_or_none()

                if threshold:
                    thresholds = {
                        "min_overall_score": threshold.min_overall_score,
                        "min_grammar_score": threshold.min_grammar_score,
                        "min_spelling_score": threshold.min_spelling_score,
                        "min_readability_score": threshold.min_readability_score,
                        "min_originality_score": threshold.min_originality_score,
                        "min_ai_human_score": threshold.min_ai_human_score,
                        "require_manual_review": threshold.require_manual_review,
                    }
                    await cache_manager.set(cache_key, thresholds, ttl=3600)
                    return thresholds

        return self.default_thresholds

    def _update_report_scores(
        self,
        report: QualityReport,
        result: CheckResult,
    ) -> None:
        """Update report with individual check scores"""
        if result.check_type == QualityCheckType.GRAMMAR:
            report.grammar_score = result.score
        elif result.check_type == QualityCheckType.SPELLING:
            report.spelling_score = result.score
        elif result.check_type == QualityCheckType.READABILITY:
            report.readability_score = result.score
        elif result.check_type == QualityCheckType.PLAGIARISM:
            report.originality_score = result.metadata.get("originality_score", result.score)
            report.ai_human_score = result.metadata.get("ai_human_score", 70)
        elif result.check_type == QualityCheckType.TONE:
            report.tone_match_score = result.metadata.get("tone_score", result.score)
        elif result.check_type == QualityCheckType.CODE_SYNTAX:
            report.code_syntax_score = result.metadata.get("syntax_score", result.score)
            report.code_style_score = result.metadata.get("style_score", 80)
            report.code_security_score = result.metadata.get("security_score", 80)

    def _calculate_overall_score(
        self,
        report: QualityReport,
        content_type: str,
    ) -> float:
        """Calculate weighted overall score"""
        if content_type == "writing":
            scores = [
                (report.grammar_score or 0, 0.25),
                (report.spelling_score or 0, 0.15),
                (report.readability_score or 0, 0.20),
                (report.originality_score or 0, 0.20),
                (report.ai_human_score or 0, 0.10),
                (report.tone_match_score or 0, 0.10),
            ]
        elif content_type == "code":
            scores = [
                (report.code_syntax_score or 0, 0.40),
                (report.code_style_score or 0, 0.30),
                (report.code_security_score or 0, 0.30),
            ]
        else:
            return 80.0  # Default for other content types

        total = sum(score * weight for score, weight in scores)
        total_weight = sum(weight for _, weight in scores if _ > 0)

        return total / max(total_weight, 0.01)

    async def _check_auto_approval(
        self,
        report: QualityReport,
        thresholds: dict,
    ) -> bool:
        """Determine if content can be auto-approved"""
        if thresholds.get("require_manual_review"):
            return False

        if report.status == QualityStatus.FAILED:
            return False

        if report.overall_score < thresholds.get("min_overall_score", 80):
            return False

        # Check individual thresholds
        if report.grammar_score and report.grammar_score < thresholds.get("min_grammar_score", 90):
            return False

        if report.originality_score and report.originality_score < thresholds.get("min_originality_score", 85):
            return False

        if report.ai_human_score and report.ai_human_score < thresholds.get("min_ai_human_score", 60):
            return False

        return True

    async def _generate_suggestions(
        self,
        content: str,
        content_type: str,
        issues: list[dict],
    ) -> list[str]:
        """Generate improvement suggestions based on issues"""
        if not issues:
            return ["Content meets quality standards. Consider final review before submission."]

        from src.llm.client import llm_client

        # Summarize issues
        issue_summary = "\n".join([
            f"- {issue.get('error', issue.get('message', str(issue)))}"
            for issue in issues[:10]
        ])

        prompt = f"""Based on these quality issues found in {content_type} content, provide 3-5 specific, actionable suggestions for improvement.

Issues found:
{issue_summary}

Content excerpt:
{content[:1000]}

Provide suggestions in a numbered list:"""

        try:
            response = await llm_client.complete(
                prompt=prompt,
                max_tokens=400,
                temperature=0.3,
            )

            suggestions = []
            for line in response.content.split('\n'):
                line = line.strip()
                if line and (line[0].isdigit() or line.startswith('-')):
                    # Clean up numbering
                    cleaned = line.lstrip('0123456789.-) ').strip()
                    if cleaned:
                        suggestions.append(cleaned)

            return suggestions[:5]
        except Exception as e:
            logger.warning("Failed to generate suggestions", error=str(e))
            return ["Review the identified issues and make corrections."]


# Singleton instance
quality_engine = QualityEngine()
