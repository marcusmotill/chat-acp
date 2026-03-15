from typing import Dict, Type, List
from core.ports.platform import ChatPlatform

class PlatformRegistry:
    """
    Registry for chat platform implementations.
    Allows decoupling generic CLI/Orchestrator from specific adapters.
    """
    _platforms: Dict[str, Type[ChatPlatform]] = {}

    @classmethod
    def register(cls, platform_cls: Type[ChatPlatform]):
        """Register a platform implementation."""
        instance = platform_cls()
        cls._platforms[instance.name] = platform_cls

    @classmethod
    def get_platform(cls, name: str) -> ChatPlatform:
        """Get an instance of a registered platform."""
        platform_cls = cls._platforms.get(name)
        if not platform_cls:
            raise ValueError(f"Platform '{name}' not found in registry.")
        return platform_cls()

    @classmethod
    def list_platforms(cls) -> List[str]:
        """List names of all registered platforms."""
        return list(cls._platforms.keys())

# Global registry instance
registry = PlatformRegistry()
