"""
Sentiment Analysis Engine
Uses ML and LLM for accurate sentiment detection and tracking
"""

import re
from dataclasses import dataclass
from typing import Optional

import structlog

from src.llm.client import llm_client
from src.communication.models import SentimentType

logger = structlog.get_logger(__name__)


@dataclass
class SentimentResult:
    """Result of sentiment analysis"""
    sentiment: SentimentType
    score: float  # -1.0 to 1.0
    confidence: float  # 0.0 to 1.0
    detected_emotions: list[str]
    urgency_level: float  # 0.0 to 1.0
    intent: Optional[str] = None
    entities: Optional[dict] = None
    key_phrases: Optional[list[str]] = None


class SentimentAnalyzer:
    """
    Advanced sentiment analyzer combining rule-based and LLM approaches.

    Features:
    - Multi-layer sentiment detection
    - Urgency detection
    - Intent classification
    - Entity extraction
    - Emotion detection
    """

    # Sentiment keywords for quick classification
    POSITIVE_KEYWORDS = {
        "thank", "thanks", "great", "excellent", "amazing", "wonderful",
        "perfect", "love", "appreciate", "happy", "pleased", "satisfied",
        "awesome", "fantastic", "brilliant", "outstanding", "impressed",
    }

    NEGATIVE_KEYWORDS = {
        "disappointed", "frustrated", "angry", "upset", "unhappy", "terrible",
        "awful", "horrible", "poor", "bad", "wrong", "issue", "problem",
        "complaint", "refund", "cancel", "unacceptable", "worst",
    }

    URGENT_KEYWORDS = {
        "urgent", "asap", "immediately", "emergency", "critical", "deadline",
        "today", "now", "hurry", "rush", "priority", "time-sensitive",
    }

    CONFUSION_KEYWORDS = {
        "confused", "unclear", "don't understand", "what do you mean",
        "clarify", "explain", "lost", "help me understand",
    }

    def __init__(self):
        self.use_llm = True

    async def analyze(
        self,
        text: str,
        context: Optional[str] = None,
        use_llm: bool = True,
    ) -> SentimentResult:
        """
        Perform comprehensive sentiment analysis on text.

        Args:
            text: The message to analyze
            context: Optional conversation context
            use_llm: Whether to use LLM for deeper analysis
        """
        # Quick rule-based analysis
        rule_result = self._rule_based_analysis(text)

        # If LLM analysis is enabled and text is complex enough
        if use_llm and len(text) > 20:
            try:
                llm_result = await self._llm_analysis(text, context)
                # Combine results, favoring LLM for nuanced cases
                return self._combine_results(rule_result, llm_result)
            except Exception as e:
                logger.warning("LLM sentiment analysis failed, using rule-based", error=str(e))

        return rule_result

    def _rule_based_analysis(self, text: str) -> SentimentResult:
        """Fast rule-based sentiment analysis"""
        text_lower = text.lower()
        words = set(re.findall(r'\b\w+\b', text_lower))

        # Count sentiment indicators
        positive_count = len(words & self.POSITIVE_KEYWORDS)
        negative_count = len(words & self.NEGATIVE_KEYWORDS)
        urgent_count = len(words & self.URGENT_KEYWORDS)
        confusion_count = len([kw for kw in self.CONFUSION_KEYWORDS if kw in text_lower])

        # Calculate scores
        total_sentiment_words = positive_count + negative_count
        if total_sentiment_words == 0:
            score = 0.0
            sentiment = SentimentType.NEUTRAL
        else:
            score = (positive_count - negative_count) / max(total_sentiment_words, 1)
            score = max(-1.0, min(1.0, score))

            if score > 0.5:
                sentiment = SentimentType.VERY_POSITIVE
            elif score > 0.1:
                sentiment = SentimentType.POSITIVE
            elif score < -0.5:
                sentiment = SentimentType.VERY_NEGATIVE
            elif score < -0.1:
                sentiment = SentimentType.NEGATIVE
            else:
                sentiment = SentimentType.NEUTRAL

        # Check for confusion override
        if confusion_count >= 2:
            sentiment = SentimentType.CONFUSED

        # Calculate urgency
        urgency = min(1.0, urgent_count * 0.3)

        # Check for urgency override
        if urgency > 0.5:
            sentiment = SentimentType.URGENT

        # Detect emotions
        emotions = []
        if positive_count > 0:
            emotions.append("positive")
        if negative_count > 0:
            emotions.append("negative")
        if urgent_count > 0:
            emotions.append("urgency")
        if confusion_count > 0:
            emotions.append("confusion")

        # Confidence based on how many indicators we found
        confidence = min(1.0, (positive_count + negative_count + urgent_count) * 0.2 + 0.3)

        return SentimentResult(
            sentiment=sentiment,
            score=score,
            confidence=confidence,
            detected_emotions=emotions,
            urgency_level=urgency,
        )

    async def _llm_analysis(
        self,
        text: str,
        context: Optional[str] = None,
    ) -> SentimentResult:
        """Deep LLM-based sentiment analysis"""
        context_section = f"\nConversation context:\n{context}" if context else ""

        prompt = f"""Analyze the sentiment and intent of this message from a client.

Message: "{text}"
{context_section}

Provide analysis in the following format:
SENTIMENT: [very_positive/positive/neutral/negative/very_negative/urgent/confused]
SCORE: [number from -1.0 to 1.0]
CONFIDENCE: [number from 0.0 to 1.0]
URGENCY: [number from 0.0 to 1.0]
EMOTIONS: [comma-separated list of emotions detected]
INTENT: [brief description of what the client wants]
KEY_PHRASES: [important phrases that indicate their state]

Be precise and consider context carefully."""

        response = await llm_client.complete(
            prompt=prompt,
            max_tokens=300,
            temperature=0.1,
        )

        return self._parse_llm_response(response.content)

    def _parse_llm_response(self, response: str) -> SentimentResult:
        """Parse LLM response into SentimentResult"""
        lines = response.strip().split('\n')
        result = {
            "sentiment": SentimentType.NEUTRAL,
            "score": 0.0,
            "confidence": 0.5,
            "urgency": 0.0,
            "emotions": [],
            "intent": None,
            "key_phrases": [],
        }

        for line in lines:
            if ':' not in line:
                continue
            key, value = line.split(':', 1)
            key = key.strip().upper()
            value = value.strip()

            try:
                if key == "SENTIMENT":
                    result["sentiment"] = SentimentType(value.lower())
                elif key == "SCORE":
                    result["score"] = float(value)
                elif key == "CONFIDENCE":
                    result["confidence"] = float(value)
                elif key == "URGENCY":
                    result["urgency"] = float(value)
                elif key == "EMOTIONS":
                    result["emotions"] = [e.strip() for e in value.split(',')]
                elif key == "INTENT":
                    result["intent"] = value
                elif key == "KEY_PHRASES":
                    result["key_phrases"] = [p.strip() for p in value.split(',')]
            except (ValueError, KeyError):
                continue

        return SentimentResult(
            sentiment=result["sentiment"],
            score=result["score"],
            confidence=result["confidence"],
            detected_emotions=result["emotions"],
            urgency_level=result["urgency"],
            intent=result["intent"],
            key_phrases=result["key_phrases"],
        )

    def _combine_results(
        self,
        rule_result: SentimentResult,
        llm_result: SentimentResult,
    ) -> SentimentResult:
        """Combine rule-based and LLM results intelligently"""
        # Weight LLM results more heavily for nuanced analysis
        if llm_result.confidence > 0.7:
            return llm_result

        # If LLM is uncertain, blend with rule-based
        combined_score = (rule_result.score * 0.3 + llm_result.score * 0.7)
        combined_confidence = max(rule_result.confidence, llm_result.confidence)

        # Use LLM sentiment if confident enough
        sentiment = llm_result.sentiment if llm_result.confidence > 0.5 else rule_result.sentiment

        # Merge emotions
        all_emotions = list(set(rule_result.detected_emotions + llm_result.detected_emotions))

        return SentimentResult(
            sentiment=sentiment,
            score=combined_score,
            confidence=combined_confidence,
            detected_emotions=all_emotions,
            urgency_level=max(rule_result.urgency_level, llm_result.urgency_level),
            intent=llm_result.intent,
            entities=llm_result.entities,
            key_phrases=llm_result.key_phrases,
        )

    def calculate_sentiment_trend(
        self,
        sentiment_history: list[float],
    ) -> str:
        """
        Calculate sentiment trend from history of scores.

        Returns: "improving", "stable", or "declining"
        """
        if len(sentiment_history) < 3:
            return "stable"

        # Use last 5 data points
        recent = sentiment_history[-5:]

        # Calculate simple linear trend
        n = len(recent)
        x_mean = (n - 1) / 2
        y_mean = sum(recent) / n

        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(recent))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return "stable"

        slope = numerator / denominator

        if slope > 0.1:
            return "improving"
        elif slope < -0.1:
            return "declining"
        return "stable"


# Singleton instance
sentiment_analyzer = SentimentAnalyzer()
