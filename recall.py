"""
recall.py — 기억이 늘어날수록 잘리는 구조를, 필요한 것만 떠올리는 구조로.

무엇이 문제였나
  프롬프트에 사실을 강도순으로 N개만 넣었다. 사실이 30개를 넘자
  "찬기는 대구FC를 좋아한다"(강도 0.55)가 잘려서, 축구를 물어도
  "처음 듣는 것 같아"라고 답했다. 알고 있는데 떠올릴 자리가 없었다.

  개수를 늘리는 건 답이 아니다. 수백 개가 되면 프롬프트가 터지고,
  그 전에 이미 '다 넣었는데 못 찾는' 상태가 된다.
  사람도 아는 것을 매 순간 전부 떠올리지 않는다.

어떻게 바꾸나
  사실마다 벡터를 만들어 SOM(자기조직화지도)에 얹는다.
  질문이 오면 질문 벡터와 **가까운 노드의 사실들만** 꺼낸다.
  기억이 천 개가 돼도 프롬프트 크기는 그대로다.

세 갈래를 섞어서 뽑는다
  가까움  질문과 의미가 가까운 것 (지도에서 이웃)
  강함    자주 확인돼 굳은 것 (확신)
  최근    최근에 들어온 것
  — 하나만 쓰면 편향된다. 가까운 것만 보면 늘 같은 기억에 갇히고,
    강한 것만 보면 새 기억이 영영 안 불려 나온다.

SOM 은 사실 수가 적을 땐 의미가 없다(MIN_FOR_SOM). 그때는 그냥 전부 쓴다.
"""
from __future__ import annotations
import numpy as np

MIN_FOR_SOM = 40        # 이보다 적으면 지도를 쓰지 않고 전부 넣는다
DIM = 64


def _vec(text: str):
    from organism.embedder import hashed_embedding
    return hashed_embedding(text or "", dim=DIM)


def _grid_for(n: int) -> tuple:
    """사실 수에 맞는 격자. 노드가 자료보다 많으면 지도가 의미를 잃는다."""
    import math
    side = max(3, min(12, int(round(math.sqrt(max(5 * math.sqrt(n), 9))))))
    return (side, side)


class FactRecall:
    """사실 목록을 지도에 얹고, 질문에 맞는 것만 꺼낸다."""

    def __init__(self, facts: list[dict], seed: int = 42):
        self.facts = [f for f in (facts or []) if (f.get("text") or "").strip()]
        self.som = None
        self.assign = {}          # node -> [fact index]
        if len(self.facts) < MIN_FOR_SOM:
            return
        try:
            from organism.som import SOM
            X = np.array([_vec(f["text"]) for f in self.facts])
            self.som = SOM(grid=_grid_for(len(self.facts)), dim=DIM, seed=seed)
            self.som.train(X, iters=min(3000, 40 * len(self.facts)), seed=seed)
            for i, x in enumerate(X):
                self.assign.setdefault(self.som.bmu_of(x), []).append(i)
        except Exception:
            self.som = None       # 실패하면 조용히 예전 방식으로 (기억은 지킨다)

    # ── 꺼내기 ────────────────────────────────────────────────
    def recall(self, question: str, k: int = 40) -> list[dict]:
        if not self.facts:
            return []
        if self.som is None or not question:
            return self._by_strength(k)

        near = self._near(question, k)
        strong = self._by_strength(max(6, k // 4))
        recent = self.facts[-max(4, k // 6):]

        out, seen = [], set()
        for f in near + strong + recent:      # 가까움 → 강함 → 최근 순
            key = f.get("text")
            if key and key not in seen:
                seen.add(key)
                out.append(f)
            if len(out) >= k:
                break
        return out

    def _near(self, question: str, k: int) -> list[dict]:
        """질문 벡터의 최적 노드와 그 이웃 노드에 얹힌 사실들."""
        q = _vec(question)
        b = self.som.bmu_of(q)
        by, bx = divmod(b, self.som.gw)
        ranked = []
        for node, idxs in self.assign.items():
            ny, nx = divmod(node, self.som.gw)
            d = abs(ny - by) + abs(nx - bx)        # 격자 위 거리
            for i in idxs:
                sim = float(q @ _vec(self.facts[i]["text"]))
                ranked.append((d - sim, i))        # 가까운 노드 + 비슷한 문장
        ranked.sort(key=lambda t: t[0])
        return [self.facts[i] for _, i in ranked[:k]]

    def _by_strength(self, k: int) -> list[dict]:
        return sorted(self.facts, key=lambda f: -(f.get("strength") or 0))[:k]

    # ── 상태 ─────────────────────────────────────────────────
    def info(self) -> dict:
        return {"facts": len(self.facts),
                "som": None if self.som is None
                else f"{self.som.gh}x{self.som.gw}",
                "nodes_used": len(self.assign)}
