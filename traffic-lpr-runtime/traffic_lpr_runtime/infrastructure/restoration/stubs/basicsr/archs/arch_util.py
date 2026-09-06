from __future__ import annotations

from torch.nn.init import trunc_normal_


def to_2tuple(value):
    if isinstance(value, tuple):
        return value
    return (value, value)


__all__ = ['to_2tuple', 'trunc_normal_']