from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol

from traffic_lpr_runtime.domain.errors import RuntimeFailure


class RuntimeUseCase(Protocol):
    name: str

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True, slots=True)
class CallableRuntimeUseCase:
    name: str
    handler: Callable[[dict[str, Any]], dict[str, Any]]

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.handler(payload)


class RuntimeUseCaseRegistry:
    def __init__(self, use_cases: Iterable[RuntimeUseCase] = ()) -> None:
        self._use_cases: dict[str, RuntimeUseCase] = {}
        for use_case in use_cases:
            self.register(use_case)

    def register(self, use_case: RuntimeUseCase) -> None:
        if use_case.name in self._use_cases:
            raise RuntimeFailure(f'Duplicate runtime use case registration: {use_case.name}')
        self._use_cases[use_case.name] = use_case

    def run(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        use_case = self._use_cases.get(name)
        if use_case is None:
            raise RuntimeFailure(f'Unsupported LPR runtime subcommand: {name}')
        return use_case.run(payload)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._use_cases)