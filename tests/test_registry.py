import pytest
from adapters.chat.registry import PlatformRegistry
from core.ports.platform import ChatPlatform
from core.ports.config import ConfigProtocol


class MockPlatform(ChatPlatform):
    @property
    def name(self) -> str:
        return "mock_platform"

    async def start(self, config: ConfigProtocol) -> None:
        pass

    def get_config_schema(self) -> dict:
        return {"test": "schema"}


def test_registry_registration():
    registry = PlatformRegistry()
    registry.register(MockPlatform)

    platform = registry.get_platform("mock_platform")
    assert isinstance(platform, MockPlatform)
    assert platform.name == "mock_platform"


def test_registry_duplicate_registration():
    registry = PlatformRegistry()
    registry.register(MockPlatform)
    registry.register(MockPlatform)
    assert isinstance(registry.get_platform("mock_platform"), MockPlatform)


def test_registry_missing_platform():
    registry = PlatformRegistry()
    with pytest.raises(ValueError, match="Platform 'unknown' not found"):
        registry.get_platform("unknown")


def test_registry_list_platforms():
    registry = PlatformRegistry()
    registry.register(MockPlatform)

    platforms = registry.list_platforms()
    assert "mock_platform" in platforms
