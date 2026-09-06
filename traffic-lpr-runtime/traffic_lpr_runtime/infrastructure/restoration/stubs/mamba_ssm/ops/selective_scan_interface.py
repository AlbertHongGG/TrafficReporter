from __future__ import annotations

import torch
import torch.nn.functional as F
from einops import rearrange, repeat


def selective_scan_ref(
    u: torch.Tensor,
    delta: torch.Tensor,
    A: torch.Tensor,
    B: torch.Tensor,
    C: torch.Tensor,
    D: torch.Tensor | None = None,
    z: torch.Tensor | None = None,
    delta_bias: torch.Tensor | None = None,
    delta_softplus: bool = False,
    return_last_state: bool = False,
):
    """Pure PyTorch reference selective scan used as a Windows-safe fallback."""
    dtype_in = u.dtype
    u = u.float()
    delta = delta.float()
    if delta_bias is not None:
        delta = delta + delta_bias[..., None].float()
    if delta_softplus:
        delta = F.softplus(delta)

    batch, dim, dstate = u.shape[0], A.shape[0], A.shape[1]
    is_variable_b = B.dim() >= 3
    is_variable_c = C.dim() >= 3
    B = B.float()
    C = C.float()

    state = A.new_zeros((batch, dim, dstate))
    delta_a = torch.exp(torch.einsum('bdl,dn->bdln', delta, A))
    if not is_variable_b:
        delta_b_u = torch.einsum('bdl,dn,bdl->bdln', delta, B, u)
    else:
        if B.dim() == 3:
            delta_b_u = torch.einsum('bdl,bnl,bdl->bdln', delta, B, u)
        else:
            B = repeat(B, 'b g n l -> b (g h) n l', h=dim // B.shape[1])
            delta_b_u = torch.einsum('bdl,bdnl,bdl->bdln', delta, B, u)
    if is_variable_c and C.dim() == 4:
        C = repeat(C, 'b g n l -> b (g h) n l', h=dim // C.shape[1])

    outputs: list[torch.Tensor] = []
    last_state: torch.Tensor | None = None
    for index in range(u.shape[2]):
        state = delta_a[:, :, index] * state + delta_b_u[:, :, index]
        if not is_variable_c:
            current = torch.einsum('bdn,dn->bd', state, C)
        else:
            if C.dim() == 3:
                current = torch.einsum('bdn,bn->bd', state, C[:, :, index])
            else:
                current = torch.einsum('bdn,bdn->bd', state, C[:, :, :, index])
        if index == u.shape[2] - 1:
            last_state = state
        outputs.append(current)

    output = torch.stack(outputs, dim=2)
    if D is not None:
        output = output + u * rearrange(D.float(), 'd -> d 1')
    if z is not None:
        output = output * F.silu(z.float())
    output = output.to(dtype=dtype_in)
    if not return_last_state:
        return output
    return output, last_state


def selective_scan_fn(*args, **kwargs):
    return selective_scan_ref(*args, **kwargs)