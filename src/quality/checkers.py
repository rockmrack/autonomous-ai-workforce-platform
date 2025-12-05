"""
Quality Checkers
Individual quality checking implementations
"""

import asyncio
import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

import structlog

from src.llm.client import llm_client
from src.quality.models import QualityCheckType, QualityStatus

logger = structlog.get_logger(__name__)


@dataclass
class CheckResult:
    """Result from a quality check"""
    check_type: QualityCheckType
    check_name: str
    status: QualityStatus
    score: float  # 0-100
    passed: bool
    message: str
    issues: list[dict]
    metadata: dict
    duration_ms: int


class BaseChecker(ABC):
    """Base class for all quality checkers"""

    check_type: QualityCheckType
    check_name: str
    default_threshold: float = 70.0

    @abstractmethod
    async def check(
        self,
        content: str,
        threshold: float = None,
        **kwargs: Any,
    ) -> CheckResult:
        """Perform quality check on content"""
        pass


class GrammarChecker(BaseChecker):
    """Check grammar quality"""

    check_type = QualityCheckType.GRAMMAR
    check_name = "Grammar Check"
    default_threshold = 90.0

    async def check(
        self,
        content: str,
        threshold: float = None,
        **kwargs: Any,
    ) -> CheckResult:
        import time
        start = time.time()
        threshold = threshold or self.default_threshold

        prompt = f"""Analyze this text for grammar errors. For each error found, provide:
1. The error
2. The correction
3. The rule violated

Text:
{content[:3000]}

Respond in this format:
SCORE: [0-100 based on grammar quality]
ERRORS:
- ERROR: [error] | CORRECTION: [fix] | RULE: [grammar rule]

If no errors, respond with SCORE: 100 and ERRORS: none"""

        try:
            response = await llm_client.complete(
                prompt=prompt,
                max_tokens=800,
                temperature=0.1,
            )

            score, issues = self._parse_response(response.content)
            passed = score >= threshold

            return CheckResult(
                check_type=self.check_type,
                check_name=self.check_name,
                status=QualityStatus.PASSED if passed else QualityStatus.FAILED,
                score=score,
                passed=passed,
                message=f"Grammar score: {score:.1f}/100",
                issues=issues,
                metadata={"error_count": len(issues)},
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            logger.error("Grammar check failed", error=str(e))
            return CheckResult(
                check_type=self.check_type,
                check_name=self.check_name,
                status=QualityStatus.FAILED,
                score=0,
                passed=False,
                message=f"Check failed: {str(e)}",
                issues=[],
                metadata={"error": str(e)},
                duration_ms=int((time.time() - start) * 1000),
            )

    def _parse_response(self, response: str) -> tuple[float, list[dict]]:
        """Parse LLM response into score and issues"""
        score = 100.0
        issues = []

        for line in response.split('\n'):
            if line.startswith('SCORE:'):
                try:
                    score = float(line.split(':')[1].strip())
                except ValueError:
                    pass
            elif '|' in line and 'ERROR:' in line:
                parts = line.split('|')
                if len(parts) >= 2:
                    issues.append({
                        "error": parts[0].replace('- ERROR:', '').strip(),
                        "correction": parts[1].replace('CORRECTION:', '').strip() if len(parts) > 1 else "",
                        "rule": parts[2].replace('RULE:', '').strip() if len(parts) > 2 else "",
                    })

        return score, issues


class SpellingChecker(BaseChecker):
    """Check spelling quality"""

    check_type = QualityCheckType.SPELLING
    check_name = "Spelling Check"
    default_threshold = 95.0

    async def check(
        self,
        content: str,
        threshold: float = None,
        **kwargs: Any,
    ) -> CheckResult:
        import time
        start = time.time()
        threshold = threshold or self.default_threshold

        prompt = f"""Check this text for spelling errors. List any misspelled words with corrections.

Text:
{content[:3000]}

Respond in this format:
SCORE: [0-100 based on spelling accuracy]
MISSPELLINGS:
- [misspelled] -> [correct]

If no errors, respond with SCORE: 100 and MISSPELLINGS: none"""

        try:
            response = await llm_client.complete(
                prompt=prompt,
                max_tokens=500,
                temperature=0.1,
            )

            score, issues = self._parse_response(response.content)
            passed = score >= threshold

            return CheckResult(
                check_type=self.check_type,
                check_name=self.check_name,
                status=QualityStatus.PASSED if passed else QualityStatus.FAILED,
                score=score,
                passed=passed,
                message=f"Spelling score: {score:.1f}/100",
                issues=issues,
                metadata={"misspelling_count": len(issues)},
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            logger.error("Spelling check failed", error=str(e))
            return CheckResult(
                check_type=self.check_type,
                check_name=self.check_name,
                status=QualityStatus.FAILED,
                score=0,
                passed=False,
                message=f"Check failed: {str(e)}",
                issues=[],
                metadata={"error": str(e)},
                duration_ms=int((time.time() - start) * 1000),
            )

    def _parse_response(self, response: str) -> tuple[float, list[dict]]:
        """Parse response"""
        score = 100.0
        issues = []

        for line in response.split('\n'):
            if line.startswith('SCORE:'):
                try:
                    score = float(line.split(':')[1].strip())
                except ValueError:
                    pass
            elif '->' in line and line.strip().startswith('-'):
                parts = line.strip('- ').split('->')
                if len(parts) == 2:
                    issues.append({
                        "misspelled": parts[0].strip(),
                        "correction": parts[1].strip(),
                    })

        return score, issues


class ReadabilityChecker(BaseChecker):
    """Check text readability"""

    check_type = QualityCheckType.READABILITY
    check_name = "Readability Analysis"
    default_threshold = 70.0

    async def check(
        self,
        content: str,
        threshold: float = None,
        target_grade_level: int = 10,
        **kwargs: Any,
    ) -> CheckResult:
        import time
        start = time.time()
        threshold = threshold or self.default_threshold

        # Calculate basic readability metrics
        metrics = self._calculate_metrics(content)

        # Flesch-Kincaid Grade Level
        fk_grade = self._flesch_kincaid_grade(metrics)

        # Flesch Reading Ease
        fre_score = self._flesch_reading_ease(metrics)

        # Score based on target grade level match
        grade_diff = abs(fk_grade - target_grade_level)
        grade_score = max(0, 100 - (grade_diff * 10))

        # Combined score
        score = (fre_score * 0.6 + grade_score * 0.4)

        passed = score >= threshold

        return CheckResult(
            check_type=self.check_type,
            check_name=self.check_name,
            status=QualityStatus.PASSED if passed else QualityStatus.WARNING,
            score=score,
            passed=passed,
            message=f"Readability: Grade {fk_grade:.1f}, Ease {fre_score:.1f}",
            issues=[],
            metadata={
                "flesch_kincaid_grade": fk_grade,
                "flesch_reading_ease": fre_score,
                "word_count": metrics["words"],
                "sentence_count": metrics["sentences"],
                "avg_sentence_length": metrics["avg_sentence_length"],
                "avg_syllables_per_word": metrics["avg_syllables"],
            },
            duration_ms=int((time.time() - start) * 1000),
        )

    def _calculate_metrics(self, text: str) -> dict:
        """Calculate text metrics"""
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        words = re.findall(r'\b\w+\b', text)
        word_count = len(words)
        sentence_count = max(len(sentences), 1)

        # Estimate syllables (simplified)
        syllable_count = sum(self._count_syllables(word) for word in words)

        return {
            "words": word_count,
            "sentences": sentence_count,
            "syllables": syllable_count,
            "avg_sentence_length": word_count / sentence_count,
            "avg_syllables": syllable_count / max(word_count, 1),
        }

    def _count_syllables(self, word: str) -> int:
        """Estimate syllable count for a word"""
        word = word.lower()
        vowels = "aeiou"
        count = 0
        prev_was_vowel = False

        for char in word:
            is_vowel = char in vowels
            if is_vowel and not prev_was_vowel:
                count += 1
            prev_was_vowel = is_vowel

        # Handle silent e
        if word.endswith('e'):
            count -= 1

        return max(count, 1)

    def _flesch_kincaid_grade(self, metrics: dict) -> float:
        """Calculate Flesch-Kincaid Grade Level"""
        return (
            0.39 * metrics["avg_sentence_length"] +
            11.8 * metrics["avg_syllables"] -
            15.59
        )

    def _flesch_reading_ease(self, metrics: dict) -> float:
        """Calculate Flesch Reading Ease score"""
        score = (
            206.835 -
            1.015 * metrics["avg_sentence_length"] -
            84.6 * metrics["avg_syllables"]
        )
        return max(0, min(100, score))


class ContentQualityChecker(BaseChecker):
    """Comprehensive content quality analysis"""

    check_type = QualityCheckType.TONE
    check_name = "Content Quality Analysis"
    default_threshold = 75.0

    def __init__(self):
        self.grammar = GrammarChecker()
        self.spelling = SpellingChecker()
        self.readability = ReadabilityChecker()

    async def check(
        self,
        content: str,
        threshold: float = None,
        target_tone: str = "professional",
        **kwargs: Any,
    ) -> CheckResult:
        import time
        start = time.time()
        threshold = threshold or self.default_threshold

        # Run all content checks in parallel
        results = await asyncio.gather(
            self.grammar.check(content),
            self.spelling.check(content),
            self.readability.check(content),
            self._check_tone(content, target_tone),
        )

        grammar_result, spelling_result, readability_result, tone_result = results

        # Calculate overall score
        scores = [
            grammar_result.score * 0.3,
            spelling_result.score * 0.2,
            readability_result.score * 0.25,
            tone_result["score"] * 0.25,
        ]
        overall_score = sum(scores)

        # Collect all issues
        all_issues = (
            grammar_result.issues +
            spelling_result.issues +
            [{"tone": tone_result.get("issues", [])}]
        )

        passed = overall_score >= threshold
        status = QualityStatus.PASSED if passed else (
            QualityStatus.WARNING if overall_score >= threshold * 0.8 else QualityStatus.FAILED
        )

        return CheckResult(
            check_type=self.check_type,
            check_name=self.check_name,
            status=status,
            score=overall_score,
            passed=passed,
            message=f"Content quality: {overall_score:.1f}/100",
            issues=all_issues,
            metadata={
                "grammar_score": grammar_result.score,
                "spelling_score": spelling_result.score,
                "readability_score": readability_result.score,
                "tone_score": tone_result["score"],
                "tone_match": tone_result.get("match", "unknown"),
            },
            duration_ms=int((time.time() - start) * 1000),
        )

    async def _check_tone(self, content: str, target_tone: str) -> dict:
        """Analyze if content matches target tone"""
        prompt = f"""Analyze the tone of this text and rate how well it matches the target tone.

Text:
{content[:2000]}

Target tone: {target_tone}

Respond with:
DETECTED_TONE: [the actual tone of the text]
MATCH_SCORE: [0-100 how well it matches target]
ISSUES: [any tone issues found, or "none"]"""

        try:
            response = await llm_client.complete(
                prompt=prompt,
                max_tokens=200,
                temperature=0.2,
            )

            result = {"score": 75.0, "match": "unknown", "issues": []}

            for line in response.content.split('\n'):
                if 'DETECTED_TONE:' in line:
                    result["match"] = line.split(':')[1].strip()
                elif 'MATCH_SCORE:' in line:
                    try:
                        result["score"] = float(line.split(':')[1].strip())
                    except ValueError:
                        pass
                elif 'ISSUES:' in line:
                    issues = line.split(':')[1].strip()
                    if issues.lower() != "none":
                        result["issues"] = [issues]

            return result
        except Exception as e:
            logger.warning("Tone check failed", error=str(e))
            return {"score": 70.0, "match": "unknown", "issues": [str(e)]}


class PlagiarismChecker(BaseChecker):
    """Check for plagiarism and AI-generated content detection"""

    check_type = QualityCheckType.PLAGIARISM
    check_name = "Originality Check"
    default_threshold = 85.0

    async def check(
        self,
        content: str,
        threshold: float = None,
        check_ai_detection: bool = True,
        **kwargs: Any,
    ) -> CheckResult:
        import time
        start = time.time()
        threshold = threshold or self.default_threshold

        # Generate content fingerprint
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        # Check for common patterns that suggest AI generation
        ai_score = await self._check_ai_patterns(content)

        # Simulated originality score (in production, would use API)
        originality_score = 100 - (100 - ai_score) * 0.3

        overall_score = (originality_score * 0.6 + ai_score * 0.4)
        passed = overall_score >= threshold

        issues = []
        if ai_score < 60:
            issues.append({
                "type": "ai_detection",
                "message": "Content may appear AI-generated",
                "score": ai_score,
            })

        return CheckResult(
            check_type=self.check_type,
            check_name=self.check_name,
            status=QualityStatus.PASSED if passed else QualityStatus.WARNING,
            score=overall_score,
            passed=passed,
            message=f"Originality: {originality_score:.1f}%, Human-like: {ai_score:.1f}%",
            issues=issues,
            metadata={
                "originality_score": originality_score,
                "ai_human_score": ai_score,
                "content_hash": content_hash,
            },
            duration_ms=int((time.time() - start) * 1000),
        )

    async def _check_ai_patterns(self, content: str) -> float:
        """Check for patterns that suggest AI-generated content"""
        prompt = """Analyze this text for patterns typical of AI-generated content.
Consider:
1. Repetitive phrasing patterns
2. Overly formal or generic language
3. Lack of personal voice or unique perspective
4. Predictable sentence structures
5. Missing specific details or anecdotes

Text:
{content}

Rate the human-likeness from 0-100 (100 = definitely human-written):
SCORE: [number]
INDICATORS: [brief explanation]"""

        try:
            response = await llm_client.complete(
                prompt=prompt.format(content=content[:2500]),
                max_tokens=150,
                temperature=0.2,
            )

            for line in response.content.split('\n'):
                if 'SCORE:' in line:
                    try:
                        return float(line.split(':')[1].strip())
                    except ValueError:
                        pass

            return 75.0  # Default score
        except Exception as e:
            logger.warning("AI pattern check failed", error=str(e))
            return 70.0


class CodeQualityChecker(BaseChecker):
    """Check code quality"""

    check_type = QualityCheckType.CODE_SYNTAX
    check_name = "Code Quality Analysis"
    default_threshold = 80.0

    async def check(
        self,
        content: str,
        threshold: float = None,
        language: str = "python",
        **kwargs: Any,
    ) -> CheckResult:
        import time
        start = time.time()
        threshold = threshold or self.default_threshold

        # Run various code checks
        results = await asyncio.gather(
            self._check_syntax(content, language),
            self._check_style(content, language),
            self._check_security(content, language),
        )

        syntax_result, style_result, security_result = results

        # Calculate overall score
        overall_score = (
            syntax_result["score"] * 0.4 +
            style_result["score"] * 0.3 +
            security_result["score"] * 0.3
        )

        all_issues = (
            syntax_result.get("issues", []) +
            style_result.get("issues", []) +
            security_result.get("issues", [])
        )

        passed = overall_score >= threshold
        status = QualityStatus.PASSED if passed else QualityStatus.FAILED

        return CheckResult(
            check_type=self.check_type,
            check_name=self.check_name,
            status=status,
            score=overall_score,
            passed=passed,
            message=f"Code quality: {overall_score:.1f}/100",
            issues=all_issues,
            metadata={
                "syntax_score": syntax_result["score"],
                "style_score": style_result["score"],
                "security_score": security_result["score"],
                "language": language,
            },
            duration_ms=int((time.time() - start) * 1000),
        )

    async def _check_syntax(self, code: str, language: str) -> dict:
        """Check code syntax"""
        prompt = f"""Analyze this {language} code for syntax errors.

Code:
```{language}
{code[:3000]}
```

Report any syntax errors found:
SCORE: [0-100]
ERRORS:
- [line number]: [error description]

If no errors, respond with SCORE: 100 and ERRORS: none"""

        try:
            response = await llm_client.complete(
                prompt=prompt,
                max_tokens=400,
                temperature=0.1,
            )
            return self._parse_code_response(response.content)
        except Exception as e:
            return {"score": 50.0, "issues": [str(e)]}

    async def _check_style(self, code: str, language: str) -> dict:
        """Check code style and best practices"""
        prompt = f"""Analyze this {language} code for style issues and best practices.

Code:
```{language}
{code[:3000]}
```

Check for:
- Naming conventions
- Code organization
- Documentation/comments
- DRY violations

SCORE: [0-100]
ISSUES:
- [issue description]"""

        try:
            response = await llm_client.complete(
                prompt=prompt,
                max_tokens=400,
                temperature=0.2,
            )
            return self._parse_code_response(response.content)
        except Exception as e:
            return {"score": 70.0, "issues": [str(e)]}

    async def _check_security(self, code: str, language: str) -> dict:
        """Check for security vulnerabilities"""
        prompt = f"""Analyze this {language} code for security vulnerabilities.

Code:
```{language}
{code[:3000]}
```

Check for:
- Injection vulnerabilities
- Hardcoded secrets
- Insecure practices
- Input validation issues

SCORE: [0-100]
VULNERABILITIES:
- [severity]: [description]"""

        try:
            response = await llm_client.complete(
                prompt=prompt,
                max_tokens=400,
                temperature=0.1,
            )
            return self._parse_code_response(response.content)
        except Exception as e:
            return {"score": 80.0, "issues": [str(e)]}

    def _parse_code_response(self, response: str) -> dict:
        """Parse code check response"""
        result = {"score": 80.0, "issues": []}

        for line in response.split('\n'):
            if 'SCORE:' in line:
                try:
                    result["score"] = float(line.split(':')[1].strip())
                except ValueError:
                    pass
            elif line.strip().startswith('-') and ':' in line:
                result["issues"].append(line.strip('- '))

        return result
