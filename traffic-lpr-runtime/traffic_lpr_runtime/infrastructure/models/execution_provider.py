from __future__ import annotations

from traffic_lpr_runtime.infrastructure.dependencies import DependencyRegistry


class OnnxExecutionProviderPolicy:
    """Manages execution providers and devices for ONNX Runtime inference."""

    def __init__(self, dependencies: DependencyRegistry) -> None:
        self._dependencies = dependencies

    def device(self) -> str:
        return 'cuda' if self._dependencies.torch_cuda_available() else 'cpu'

    def providers(self) -> list[str]:
        if self._dependencies.torch_cuda_available():
            return ['CUDAExecutionProvider', 'CPUExecutionProvider']
        return ['CPUExecutionProvider']
