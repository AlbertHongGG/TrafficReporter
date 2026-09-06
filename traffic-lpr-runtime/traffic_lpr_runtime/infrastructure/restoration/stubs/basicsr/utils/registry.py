from __future__ import annotations

from typing import Any, Callable


class Registry:
    def __init__(self, name: str) -> None:
        self._name = name
        self._items: dict[str, Any] = {}

    def register(self, name: str | None = None) -> Callable[[Any], Any]:
        def decorator(item: Any) -> Any:
            key = name or getattr(item, '__name__', repr(item))
            self._items[key] = item
            return item

        return decorator

    def get(self, name: str) -> Any:
        return self._items[name]


ARCH_REGISTRY = Registry('arch')
