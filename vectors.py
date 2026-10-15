"""
vectors.py — **낱말을 벡터로 바꾸는 곳은 여기 하나다.**

왜 한 곳에 모으나
  지금까지는 쓰는 데마다 따로 해시 임베딩을 불렀다. 그래서
  **무엇을 쓰고 있는지 알 수가 없었다.** 좋은 벡터로 바꾸려 해도
  고칠 데가 여기저기였고, 바꿨는지 안 바꿨는지도 안 보였다.

  여기 하나로 모으고, **지금 무엇을 쓰는지 로그에 찍는다.**
  그래야 "해시인 채로 돌고 있었다" 가 조용히 지나가지 않는다.

무엇을 쓰나
  1. vectors.npz 가 있으면 그것 (사전학습 word2vec 에서 뽑아 둔 것)
  2. 없으면 해시 임베딩 (지금까지 쓰던 것)

  섞어 쓴다. 파일에 있는 낱말은 그 벡터를, 없는 낱말(몰랑이·피우피우
  같은 이름)은 해시를 쓴다. **빈 자리를 0 으로 채우지 않는다** —
  그러면 모르는 낱말끼리 다 가까워 보여서 오히려 해롭다.

차원이 다른데 어떻게 섞나
  섞지 않는다. 파일이 있으면 **그 차원으로 통일**하고, 해시도
  같은 차원으로 뽑는다. 둘이 같은 공간에 있는 것은 아니지만,
  해시 쪽은 어차피 '글자가 비슷한가' 만 말한다. 섞여도
  파일에 있는 낱말끼리의 관계가 망가지지는 않는다.

겪은 것으로 옮겨가기
  받아온 벡터는 **처음 자리**일 뿐이다. 몰랑이가 살면서 쓰는 결이
  쌓이면 그쪽으로 조금씩 움직인다 (nudge). 바깥에서 가져온 뜻과
  겪어서 생긴 뜻이 섞이는 게 아니라 **이어진다.**
"""
from __future__ import annotations
import os
import threading

import numpy as np

VEC_FILE = os.environ.get("MOLANG_VECTORS", "vectors.npz")
NUDGE = 0.04              # 겪은 결로 움직이는 폭 (작게 — 뿌리가 흔들리지 않게)

_lock = threading.Lock()
_state = {"loaded": False, "words": None, "vecs": None,
          "index": None, "dim": 64, "source": "해시"}


def _load():
    if _state["loaded"]:
        return
    with _lock:
        if _state["loaded"]:
            return
        _state["loaded"] = True
        if not os.path.exists(VEC_FILE):
            return
        try:
            z = np.load(VEC_FILE, allow_pickle=True)
            words = [str(w) for w in z["words"]]
            _state.update(
                words=words, vecs=z["vecs"].astype("float32"),
                index={w: i for i, w in enumerate(words)},
                dim=int(z["dim"]),
                source=f"word2vec {len(words):,}낱말 {int(z['dim'])}차원")
        except Exception as e:
            _state["source"] = f"해시 (파일 읽기 실패: {str(e)[:40]})"


def source() -> str:
    """지금 무엇을 쓰고 있나 — 로그에 찍어 두면 조용히 지나가지 않는다."""
    _load()
    return _state["source"]


def dim() -> int:
    _load()
    return _state["dim"]


def has(word: str) -> bool:
    """사전학습 벡터에 이 낱말이 있나."""
    _load()
    return bool(_state["index"]) and word in _state["index"]


def _hashed(word: str, d: int) -> np.ndarray:
    from organism.embedder import hashed_embedding
    v = hashed_embedding(word or "", dim=d)
    v = np.asarray(v, dtype="float32")
    n = float(np.linalg.norm(v))
    return v / n if n else v


def of(word: str) -> np.ndarray:
    """한 낱말의 벡터. 길이는 1 이다."""
    _load()
    d = _state["dim"]
    idx = _state["index"]
    if idx is not None:
        i = idx.get(word)
        if i is not None:
            return _state["vecs"][i]
    return _hashed(word, d)


def of_text(text: str) -> np.ndarray:
    """여러 낱말이면 평균. 문장이나 단계 이름에 쓴다."""
    import re
    ws = re.findall(r"[가-힣A-Za-z]{2,}", text or "")
    if not ws:
        return np.zeros(dim(), dtype="float32")
    v = np.mean([of(w) for w in ws[:16]], axis=0)
    n = float(np.linalg.norm(v))
    return v / n if n else v


def near(word: str, k: int = 8, pool: list = None) -> list:
    """
    뜻이 가까운 낱말들. **지도에 간선이 없어도 찾는다.**
    이것이 해시로는 못 하던 일이다 ('살다' 와 '일광').
    """
    _load()
    v = of(word)
    if _state["vecs"] is None:
        return []
    if pool:
        idx = _state["index"] or {}
        rows = [(w, idx[w]) for w in pool if w in idx and w != word]
        if not rows:
            return []
        M = _state["vecs"][[i for _, i in rows]]
        sims = M @ v
        got = sorted(zip((w for w, _ in rows), sims),
                     key=lambda t: -t[1])
    else:
        sims = _state["vecs"] @ v
        order = np.argsort(-sims)[:k + 1]
        got = [(_state["words"][i], float(sims[i])) for i in order
               if _state["words"][i] != word]
    return [(w, round(float(s), 4)) for w, s in got[:k] if s > 0.25]


def similarity(a: str, b: str) -> float:
    return round(float(of(a) @ of(b)), 4)


# ── 겪은 결로 조금씩 옮기기 ────────────────────────────────
def nudge(pairs: list, rate: float = NUDGE) -> int:
    """
    **받아온 뜻을 몰랑이가 겪은 쪽으로 조금 움직인다.**

    pairs: [(낱말a, 낱말b, 세기)] — 함께 나온 것들.
    그 둘을 아주 조금 당긴다. 작게 움직이는 것이 중요하다.
    크게 움직이면 받아온 관계가 무너지고, 그러면 처음부터
    안 가져온 것과 같아진다.

    메모리 위에서만 바뀐다. 남기려면 save() 를 부른다.
    """
    _load()
    if _state["vecs"] is None or not pairs:
        return 0
    idx = _state["index"]
    n = 0
    for a, b, w in pairs:
        ia, ib = idx.get(a), idx.get(b)
        if ia is None or ib is None or ia == ib:
            continue
        va, vb = _state["vecs"][ia], _state["vecs"][ib]
        step = rate * min(1.0, float(w))
        na = va + step * (vb - va)
        nb = vb + step * (va - vb)
        for i, v in ((ia, na), (ib, nb)):
            ln = float(np.linalg.norm(v))
            _state["vecs"][i] = v / ln if ln else v
        n += 1
    return n


def save(path: str = None) -> bool:
    """옮겨간 벡터를 남긴다."""
    _load()
    if _state["vecs"] is None:
        return False
    try:
        np.savez_compressed(path or VEC_FILE,
                            words=np.array(_state["words"], dtype=object),
                            vecs=_state["vecs"], dim=_state["dim"])
        return True
    except Exception:
        return False
