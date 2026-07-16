"""LLM factory for coach response generation."""

from __future__ import annotations

from typing import Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from endurance_coach.config import Settings


class ChatModelFactory(Protocol):
    def create(self) -> BaseChatModel | None: ...


class OpenAIChatModelFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self) -> BaseChatModel | None:
        if not self._settings.openai_api_key:
            return None
        kwargs: dict[str, object] = {
            "model": self._settings.coach_llm_model,
            "api_key": self._settings.openai_api_key,
            "temperature": 0.3,
        }
        if self._settings.coach_llm_base_url:
            kwargs["base_url"] = self._settings.coach_llm_base_url
        return ChatOpenAI(**kwargs)  # type: ignore[arg-type]


class AnthropicChatModelFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self) -> BaseChatModel | None:
        if not self._settings.anthropic_api_key:
            return None
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            return None
        return ChatAnthropic(
            model=self._settings.coach_llm_model,
            api_key=self._settings.anthropic_api_key,
            temperature=0.3,
        )


class OllamaChatModelFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self) -> BaseChatModel | None:
        base_url = self._settings.coach_llm_base_url or "http://localhost:11434/v1"
        return ChatOpenAI(
            model=self._settings.coach_llm_model,
            api_key="ollama",
            base_url=base_url,
            temperature=0.3,
        )


class OpenAICompatibleChatModelFactory:
    """LM Studio, vLLM, LocalAI, and other OpenAI-compatible servers."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self) -> BaseChatModel | None:
        if not self._settings.coach_llm_base_url:
            return None
        return ChatOpenAI(
            model=self._settings.coach_llm_model,
            api_key=self._settings.openai_api_key or "local",
            base_url=self._settings.coach_llm_base_url,
            temperature=0.3,
        )


def create_chat_model_factory(settings: Settings) -> ChatModelFactory:
    provider = settings.coach_llm_provider.lower()
    if provider == "anthropic":
        return AnthropicChatModelFactory(settings)
    if provider == "ollama":
        return OllamaChatModelFactory(settings)
    if provider in {"openai_compatible", "compatible", "local"}:
        return OpenAICompatibleChatModelFactory(settings)
    return OpenAIChatModelFactory(settings)
