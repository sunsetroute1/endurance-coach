"""Tests for dependency injection container."""

import pytest

from endurance_coach.di.container import Container, create_container
from endurance_coach.domain.enums import DataProviderType


def test_create_container() -> None:
    container = create_container()
    assert container.settings is not None
    assert container.session_factory is not None


def test_register_provider() -> None:
    from tests.test_provider_interfaces import StubGarminProvider

    container = Container()
    provider = StubGarminProvider()
    container.register_provider(provider)
    assert DataProviderType.GARMIN in container.providers


@pytest.mark.asyncio
async def test_container_shutdown() -> None:
    container = create_container()
    await container.shutdown()
