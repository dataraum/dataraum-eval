"""DAT-742 Phase 0: environment sanity — torch/MPS, SDPA on Metal, engine imports."""

import torch

print(f"torch {torch.__version__}")
print(f"mps available: {torch.backends.mps.is_available()}  built: {torch.backends.mps.is_built()}")

# SDPA on MPS — the torch 2.13 Metal kernels (flash-attention path) in one forward pass
q = torch.randn(2, 4, 128, 64, device="mps", dtype=torch.float16)
out = torch.nn.functional.scaled_dot_product_attention(q, q, q)
print(f"SDPA on mps ok: {tuple(out.shape)} {out.dtype}")

import tabpfn

print(f"tabpfn {tabpfn.__version__}")

from importlib.metadata import version

print(f"tabicl {version('tabicl')}")

import tabfm  # noqa: F401

print(f"tabfm {version('tabfm')}")

import skrub

print(f"skrub {skrub.__version__}")
