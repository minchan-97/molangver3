from __future__ import annotations
import re, hashlib, numpy as np

TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9_]{2,}")

def tokens(text):
    return [x.lower() for x in TOKEN_RE.findall(text or "")]

def hashed_embedding(text, dim=64):
    """Dependency-free, stable semantic-ish vector for long-running topology experiments.
    Replace with a real frozen embedding model later without changing worker APIs."""
    v = np.zeros(dim, dtype=float)
    ts = tokens(text)
    if not ts: return v
    for t in ts:
        h = hashlib.sha256(t.encode()).digest()
        for i in range(4):
            idx = int.from_bytes(h[i*2:i*2+2], 'big') % dim
            sign = 1.0 if h[8+i] & 1 else -1.0
            v[idx] += sign
    n = np.linalg.norm(v)
    return v/n if n > 1e-9 else v
