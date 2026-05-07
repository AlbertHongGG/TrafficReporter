from __future__ import annotations


class RuntimeFailure(RuntimeError):
    """Raised when the sidecar cannot complete a runtime operation."""
