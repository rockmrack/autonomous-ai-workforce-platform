"""
Content Humanizer
Makes AI-generated content appear more human-written
"""

import random
import re
from typing import Optional

import structlog

from src.llm.client import llm_client

logger = structlog.get_logger(__name__)


class ContentHumanizer:
    """
    Transforms AI-generated content to appear more human-written.

    Features:
    - Natural language variations
    - Intentional minor imperfections
    - Personal voice injection
    - Structural variations
    - Regional/personality adaptations
    """

    # Filler words and phrases humans use
    FILLER_PHRASES = [
        "I think", "In my experience", "From what I've seen",
        "Actually", "To be honest", "Honestly",
        "You know", "I mean", "Basically",
    ]

    # Contractions to use
    CONTRACTIONS = {
        "I am": "I'm",
        "I have": "I've",
        "I will": "I'll",
        "I would": "I'd",
        "it is": "it's",
        "it will": "it'll",
        "that is": "that's",
        "there is": "there's",
        "what is": "what's",
        "do not": "don't",
        "does not": "doesn't",
        "cannot": "can't",
        "will not": "won't",
        "would not": "wouldn't",
        "could not": "couldn't",
        "should not": "shouldn't",
        "is not": "isn't",
        "are not": "aren't",
        "was not": "wasn't",
        "were not": "weren't",
        "have not": "haven't",
        "has not": "hasn't",
        "had not": "hadn't",
        "let us": "let's",
        "we will": "we'll",
        "they will": "they'll",
        "you will": "you'll",
    }

    # Common typos that humans make
    COMMON_TYPOS = {
        "the": ["teh", "hte"],
        "and": ["adn", "nad"],
        "that": ["taht", "tath"],
        "with": ["wiht", "wtih"],
        "have": ["ahve", "hvae"],
        "this": ["tihs", "htis"],
        "from": ["form", "fomr"],
    }

    async def humanize(
        self,
        content: str,
        style: str = "casual_professional",
        add_imperfections: bool = True,
        typo_rate: float = 0.01,
        personality_traits: Optional[list[str]] = None,
    ) -> str:
        """
        Transform content to appear more human-written.

        Args:
            content: The AI-generated content
            style: Writing style (casual, professional, casual_professional)
            add_imperfections: Whether to add minor typos/corrections
            typo_rate: Probability of typos (0.0-1.0)
            personality_traits: Personality traits to inject
        """
        # Step 1: Add contractions for natural flow
        content = self._add_contractions(content)

        # Step 2: Vary sentence structure
        content = await self._vary_structure(content, style)

        # Step 3: Add personal voice
        if personality_traits:
            content = await self._add_personality(content, personality_traits)

        # Step 4: Add fillers naturally
        content = self._add_fillers(content, style)

        # Step 5: Add intentional imperfections
        if add_imperfections:
            content = self._add_imperfections(content, typo_rate)

        # Step 6: Final natural polish
        content = await self._final_polish(content)

        return content

    def _add_contractions(self, text: str) -> str:
        """Add natural contractions"""
        result = text

        for full, contracted in self.CONTRACTIONS.items():
            # Randomly apply contractions (80% of the time for natural feel)
            if random.random() < 0.8:
                # Case-insensitive replacement
                pattern = re.compile(re.escape(full), re.IGNORECASE)
                result = pattern.sub(contracted, result)

        return result

    async def _vary_structure(self, text: str, style: str) -> str:
        """Vary sentence structure using LLM"""
        prompt = f"""Rewrite this text to sound more natural and human-written while keeping the same meaning.
Make subtle changes like:
- Vary sentence lengths
- Use more natural transitions
- Add personal touches appropriate for a {style} tone
- Keep the same key information

Original text:
{text}

Rewritten text:"""

        try:
            response = await llm_client.complete(
                prompt=prompt,
                max_tokens=len(text) + 200,
                temperature=0.6,
            )
            return response.content.strip()
        except Exception as e:
            logger.warning("Structure variation failed", error=str(e))
            return text

    async def _add_personality(
        self,
        text: str,
        traits: list[str],
    ) -> str:
        """Inject personality traits into writing"""
        traits_str = ", ".join(traits)

        prompt = f"""Add subtle personality to this text based on these traits: {traits_str}

The changes should be natural and not over-the-top. The writer should come across as having these qualities without explicitly stating them.

Original text:
{text}

Text with personality:"""

        try:
            response = await llm_client.complete(
                prompt=prompt,
                max_tokens=len(text) + 200,
                temperature=0.7,
            )
            return response.content.strip()
        except Exception as e:
            logger.warning("Personality injection failed", error=str(e))
            return text

    def _add_fillers(self, text: str, style: str) -> str:
        """Add natural filler words/phrases"""
        if style == "professional":
            # Less fillers for professional content
            filler_rate = 0.02
        elif style == "casual":
            filler_rate = 0.08
        else:
            filler_rate = 0.04

        sentences = text.split('. ')
        result = []

        for i, sentence in enumerate(sentences):
            # Randomly add filler at sentence start
            if random.random() < filler_rate and i > 0:
                filler = random.choice(self.FILLER_PHRASES)
                sentence = f"{filler}, {sentence.lower()}"

            result.append(sentence)

        return '. '.join(result)

    def _add_imperfections(self, text: str, typo_rate: float) -> str:
        """Add intentional minor imperfections"""
        words = text.split()
        result = []

        for word in words:
            # Add occasional typos
            word_lower = word.lower().strip('.,!?')
            if word_lower in self.COMMON_TYPOS and random.random() < typo_rate:
                # Add typo then "fix" it with strikethrough or correction
                typo = random.choice(self.COMMON_TYPOS[word_lower])
                # Keep the typo as-is (simulating unfixed typo)
                if random.random() < 0.3:
                    word = typo
            result.append(word)

        text = ' '.join(result)

        # Occasionally add double spaces (common human error)
        if random.random() < typo_rate * 2:
            words = text.split()
            if len(words) > 5:
                insert_pos = random.randint(2, len(words) - 2)
                words[insert_pos] = words[insert_pos] + " "
                text = ' '.join(words)

        return text

    async def _final_polish(self, text: str) -> str:
        """Final polish for natural flow"""
        # Remove any awkward patterns
        text = re.sub(r'\s+', ' ', text)  # Normalize spaces
        text = re.sub(r'\s+([.,!?])', r'\1', text)  # Fix punctuation spacing

        # Ensure proper capitalization after periods
        sentences = text.split('. ')
        result = []
        for sentence in sentences:
            if sentence:
                result.append(sentence[0].upper() + sentence[1:] if len(sentence) > 1 else sentence)
        text = '. '.join(result)

        return text.strip()

    async def humanize_typing_pattern(
        self,
        text: str,
    ) -> list[dict]:
        """
        Generate human-like typing patterns for text.
        Returns list of characters with timing delays.
        """
        result = []
        base_delay = 50  # Base delay in ms

        for i, char in enumerate(text):
            delay = base_delay

            # Vary typing speed
            delay *= random.uniform(0.5, 1.5)

            # Slower at start of words
            if i == 0 or text[i-1] == ' ':
                delay *= random.uniform(1.2, 1.8)

            # Pause at punctuation
            if char in '.,!?':
                delay *= random.uniform(1.5, 3.0)

            # Occasional longer pauses (thinking)
            if random.random() < 0.02:
                delay += random.randint(500, 2000)

            result.append({
                "char": char,
                "delay_ms": int(delay),
            })

        return result

    def add_natural_edits(self, text: str) -> list[dict]:
        """
        Generate a sequence of edits that simulate human writing process.
        Returns edit operations (type, position, content).
        """
        edits = []
        words = text.split()

        # Build text word by word with occasional corrections
        current_pos = 0

        for i, word in enumerate(words):
            # Sometimes type word, delete, retype (human behavior)
            if random.random() < 0.05:
                typo = self._make_typo(word)
                edits.append({
                    "type": "insert",
                    "position": current_pos,
                    "content": typo + " ",
                })
                edits.append({
                    "type": "delete",
                    "position": current_pos,
                    "length": len(typo) + 1,
                })
                edits.append({
                    "type": "insert",
                    "position": current_pos,
                    "content": word + " ",
                })
            else:
                edits.append({
                    "type": "insert",
                    "position": current_pos,
                    "content": word + " ",
                })

            current_pos += len(word) + 1

        return edits

    def _make_typo(self, word: str) -> str:
        """Create a realistic typo"""
        if len(word) < 3:
            return word

        typo_type = random.choice(['swap', 'double', 'miss'])

        if typo_type == 'swap':
            # Swap adjacent letters
            pos = random.randint(0, len(word) - 2)
            return word[:pos] + word[pos+1] + word[pos] + word[pos+2:]
        elif typo_type == 'double':
            # Double a letter
            pos = random.randint(0, len(word) - 1)
            return word[:pos] + word[pos] + word[pos:]
        else:
            # Miss a letter
            pos = random.randint(1, len(word) - 1)
            return word[:pos] + word[pos+1:]


# Singleton instance
content_humanizer = ContentHumanizer()
