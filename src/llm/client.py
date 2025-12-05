"""
LLM Client - Multi-provider AI integration
Supports Anthropic Claude, OpenAI GPT, and local models
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Optional, Union

import anthropic
import openai
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import settings
from src.core.events import Event, event_bus
from src.core.circuit_breaker import circuit_breaker, CircuitBreakerError

logger = structlog.get_logger(__name__)


class LLMProvider(str, Enum):
    """Supported LLM providers"""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"


class ModelTier(str, Enum):
    """Model capability tiers"""

    FAST = "fast"  # Quick responses, lower cost
    DEFAULT = "default"  # Balanced
    POWERFUL = "powerful"  # Best quality, higher cost


@dataclass
class LLMResponse:
    """Standardized LLM response"""

    content: str
    model: str
    provider: LLMProvider
    tokens_input: int
    tokens_output: int
    latency_ms: int
    cost_estimate: float
    finish_reason: str
    metadata: dict


@dataclass
class Message:
    """Chat message"""

    role: str  # "user", "assistant", "system"
    content: str


class BaseLLMClient(ABC):
    """Base class for LLM clients"""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        stop_sequences: Optional[list[str]] = None,
    ) -> str:
        """Generate completion for a prompt"""
        pass

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Chat completion with message history"""
        pass

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream completion tokens"""
        pass


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude client"""

    # Cost per 1M tokens (approximate, varies by model)
    COSTS = {
        "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
        "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    }

    def __init__(self, api_key: Optional[str] = None):
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key or settings.anthropic.api_key.get_secret_value()
        )
        self.default_model = settings.anthropic.default_model

    def get_model(self, tier: ModelTier = ModelTier.DEFAULT) -> str:
        """Get model name for tier"""
        models = {
            ModelTier.FAST: settings.anthropic.fast_model,
            ModelTier.DEFAULT: settings.anthropic.default_model,
            ModelTier.POWERFUL: settings.anthropic.powerful_model,
        }
        return models.get(tier, self.default_model)

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for request"""
        costs = self.COSTS.get(model, {"input": 3.0, "output": 15.0})
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        return input_cost + output_cost

    @circuit_breaker("anthropic_api", failure_threshold=3, timeout=60.0)
    @retry(
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIConnectionError)),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(3),
    )
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        stop_sequences: Optional[list[str]] = None,
        model_tier: ModelTier = ModelTier.DEFAULT,
    ) -> str:
        """Generate completion"""
        model = self.get_model(model_tier)
        start_time = datetime.now()

        try:
            response = await self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt or "You are a helpful assistant.",
                messages=[{"role": "user", "content": prompt}],
                stop_sequences=stop_sequences,
            )

            latency = (datetime.now() - start_time).total_seconds() * 1000
            content = response.content[0].text

            # Log usage
            logger.debug(
                "LLM generation complete",
                provider="anthropic",
                model=model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                latency_ms=latency,
            )

            return content

        except anthropic.APIError as e:
            logger.error("Anthropic API error", error=str(e))
            raise

    async def chat(
        self,
        messages: list[Message],
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        model_tier: ModelTier = ModelTier.DEFAULT,
    ) -> LLMResponse:
        """Chat completion with full response"""
        model = self.get_model(model_tier)
        start_time = datetime.now()

        api_messages = [{"role": m.role, "content": m.content} for m in messages]

        response = await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or "You are a helpful assistant.",
            messages=api_messages,
        )

        latency = int((datetime.now() - start_time).total_seconds() * 1000)

        return LLMResponse(
            content=response.content[0].text,
            model=model,
            provider=LLMProvider.ANTHROPIC,
            tokens_input=response.usage.input_tokens,
            tokens_output=response.usage.output_tokens,
            latency_ms=latency,
            cost_estimate=self._estimate_cost(
                model,
                response.usage.input_tokens,
                response.usage.output_tokens,
            ),
            finish_reason=response.stop_reason,
            metadata={"id": response.id},
        )

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        model_tier: ModelTier = ModelTier.DEFAULT,
    ) -> AsyncIterator[str]:
        """Stream completion"""
        model = self.get_model(model_tier)

        async with self.client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or "You are a helpful assistant.",
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield text


class OpenAIClient(BaseLLMClient):
    """OpenAI GPT client"""

    COSTS = {
        "gpt-4o": {"input": 2.5, "output": 10.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
        "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    }

    def __init__(self, api_key: Optional[str] = None):
        self.client = openai.AsyncOpenAI(
            api_key=api_key or settings.openai.api_key.get_secret_value()
        )
        self.default_model = settings.openai.default_model

    def get_model(self, tier: ModelTier = ModelTier.DEFAULT) -> str:
        models = {
            ModelTier.FAST: settings.openai.fast_model,
            ModelTier.DEFAULT: settings.openai.default_model,
            ModelTier.POWERFUL: settings.openai.default_model,
        }
        return models.get(tier, self.default_model)

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        costs = self.COSTS.get(model, {"input": 2.5, "output": 10.0})
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        return input_cost + output_cost

    @retry(
        retry=retry_if_exception_type((openai.RateLimitError, openai.APIConnectionError)),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(3),
    )
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        stop_sequences: Optional[list[str]] = None,
        model_tier: ModelTier = ModelTier.DEFAULT,
    ) -> str:
        model = self.get_model(model_tier)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop_sequences,
        )

        return response.choices[0].message.content

    async def chat(
        self,
        messages: list[Message],
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        model_tier: ModelTier = ModelTier.DEFAULT,
    ) -> LLMResponse:
        model = self.get_model(model_tier)
        start_time = datetime.now()

        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend([{"role": m.role, "content": m.content} for m in messages])

        response = await self.client.chat.completions.create(
            model=model,
            messages=api_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        latency = int((datetime.now() - start_time).total_seconds() * 1000)
        usage = response.usage

        return LLMResponse(
            content=response.choices[0].message.content,
            model=model,
            provider=LLMProvider.OPENAI,
            tokens_input=usage.prompt_tokens,
            tokens_output=usage.completion_tokens,
            latency_ms=latency,
            cost_estimate=self._estimate_cost(
                model, usage.prompt_tokens, usage.completion_tokens
            ),
            finish_reason=response.choices[0].finish_reason,
            metadata={"id": response.id},
        )

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        model_tier: ModelTier = ModelTier.DEFAULT,
    ) -> AsyncIterator[str]:
        model = self.get_model(model_tier)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def get_embedding(self, text: str) -> list[float]:
        """Get text embedding"""
        response = await self.client.embeddings.create(
            model=settings.openai.embedding_model,
            input=text,
        )
        return response.data[0].embedding


class LLMClient:
    """
    Unified LLM client with automatic provider selection and fallback.

    Features:
    - Multi-provider support (Anthropic, OpenAI, Ollama)
    - Automatic fallback on failures
    - Cost tracking
    - Response caching
    - Rate limit handling
    """

    def __init__(
        self,
        primary_provider: LLMProvider = LLMProvider.ANTHROPIC,
        fallback_provider: Optional[LLMProvider] = LLMProvider.OPENAI,
    ):
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider

        # Initialize clients
        self._clients: dict[LLMProvider, BaseLLMClient] = {}

        if settings.anthropic.api_key.get_secret_value():
            self._clients[LLMProvider.ANTHROPIC] = AnthropicClient()

        if settings.openai.api_key.get_secret_value():
            self._clients[LLMProvider.OPENAI] = OpenAIClient()

    def _get_client(self, provider: LLMProvider) -> BaseLLMClient:
        """Get client for provider"""
        client = self._clients.get(provider)
        if not client:
            raise ValueError(f"No client configured for {provider}")
        return client

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        stop_sequences: Optional[list[str]] = None,
        model_tier: ModelTier = ModelTier.DEFAULT,
        provider: Optional[LLMProvider] = None,
    ) -> str:
        """
        Generate completion with automatic fallback.

        Args:
            prompt: The prompt to complete
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            stop_sequences: Sequences that stop generation
            model_tier: Model tier to use
            provider: Specific provider to use (overrides default)

        Returns:
            Generated text
        """
        providers_to_try = []

        if provider:
            providers_to_try.append(provider)
        else:
            providers_to_try.append(self.primary_provider)
            if self.fallback_provider:
                providers_to_try.append(self.fallback_provider)

        last_error = None

        for p in providers_to_try:
            try:
                client = self._get_client(p)
                return await client.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stop_sequences=stop_sequences,
                    model_tier=model_tier,
                )
            except Exception as e:
                logger.warning(
                    "LLM generation failed, trying fallback",
                    provider=p.value,
                    error=str(e),
                )
                last_error = e
                continue

        raise last_error or RuntimeError("No LLM providers available")

    async def chat(
        self,
        messages: list[Message],
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        model_tier: ModelTier = ModelTier.DEFAULT,
        provider: Optional[LLMProvider] = None,
    ) -> LLMResponse:
        """Chat completion with automatic fallback"""
        p = provider or self.primary_provider
        client = self._get_client(p)

        try:
            return await client.chat(
                messages=messages,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                model_tier=model_tier,
            )
        except Exception as e:
            if self.fallback_provider and not provider:
                logger.warning(
                    "Primary chat failed, using fallback",
                    error=str(e),
                )
                fallback_client = self._get_client(self.fallback_provider)
                return await fallback_client.chat(
                    messages=messages,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    model_tier=model_tier,
                )
            raise

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        model_tier: ModelTier = ModelTier.DEFAULT,
        provider: Optional[LLMProvider] = None,
    ) -> AsyncIterator[str]:
        """Stream completion"""
        p = provider or self.primary_provider
        client = self._get_client(p)

        async for chunk in client.stream(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            model_tier=model_tier,
        ):
            yield chunk

    async def get_embedding(self, text: str) -> list[float]:
        """Get text embedding (OpenAI only for now)"""
        if LLMProvider.OPENAI not in self._clients:
            raise ValueError("Embeddings require OpenAI client")

        client: OpenAIClient = self._clients[LLMProvider.OPENAI]
        return await client.get_embedding(text)


# Singleton instance
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get the global LLM client instance"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
