"""Tests for multi-provider LLM factory."""

from endurance_coach.coach.llm import (
    AnthropicChatModelFactory,
    OllamaChatModelFactory,
    OpenAIChatModelFactory,
    OpenAICompatibleChatModelFactory,
    create_chat_model_factory,
)
from endurance_coach.config import Settings


def test_openai_factory_requires_api_key() -> None:
    factory = OpenAIChatModelFactory(Settings(openai_api_key=None))
    assert factory.create() is None


def test_openai_factory_creates_model_with_key() -> None:
    factory = OpenAIChatModelFactory(Settings(openai_api_key="test-key"))
    assert factory.create() is not None


def test_anthropic_factory_requires_api_key() -> None:
    factory = AnthropicChatModelFactory(Settings(anthropic_api_key=None))
    assert factory.create() is None


def test_ollama_factory_always_creates_model() -> None:
    factory = OllamaChatModelFactory(Settings(coach_llm_model="llama3.1"))
    assert factory.create() is not None


def test_openai_compatible_requires_base_url() -> None:
    factory = OpenAICompatibleChatModelFactory(Settings(coach_llm_base_url=None))
    assert factory.create() is None


def test_create_chat_model_factory_selects_provider() -> None:
    assert isinstance(
        create_chat_model_factory(Settings(coach_llm_provider="openai")),
        OpenAIChatModelFactory,
    )
    assert isinstance(
        create_chat_model_factory(Settings(coach_llm_provider="anthropic")),
        AnthropicChatModelFactory,
    )
    assert isinstance(
        create_chat_model_factory(Settings(coach_llm_provider="ollama")),
        OllamaChatModelFactory,
    )
    assert isinstance(
        create_chat_model_factory(Settings(coach_llm_provider="openai_compatible")),
        OpenAICompatibleChatModelFactory,
    )
