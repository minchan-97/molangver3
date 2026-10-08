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
    def recall(self, question: str, k: int = 40, markov: dict = None) -> list[dict]:
        """
        네 가지를 **한 점수로 묶어** 꺼낸다.

        예전에는 '가까움 → 강함 → 최근' 을 그냥 이어붙였다. 그러면
        가까운 것이 k 개를 다 채워 **최근 것이 들어갈 자리가 없다.**
        그래서 몇 달 전 사실이 계속 올라오고 어제 한 말은 안 나왔다.

        이제는 곱해서 하나로 본다.
          가까움   질문과 얼마나 비슷한가 (SOM 격자 + 문장 유사도)
          강함     얼마나 확신하는가
          새로움   얼마나 최근에 들어왔거나 쓰였는가
          이어짐   질문의 낱말에서 **이어지는 낱말**이 들어 있는가 (마르코프)

        마지막이 새로 더한 것이다. '바다' 를 물으면 바다 다음에 오는
        '파도·소리' 가 든 사실까지 끌어온다. 글자가 안 겹쳐도 이어지면 잡힌다.
        """
        if not self.facts:
            return []
        if self.som is None or not question:
            return self._by_strength(k)

        import time as _t
        now = _t.time()

        # 질문에서 이어지는 낱말들 (마르코프)
        chain = set()
        if markov:
            try:
                import re as _re
                import markov_mass as _mk
                for w in _re.findall(r"[가-힣A-Za-z]{2,}", question)[:4]:
                    for nxt, _p in _mk.next_of(markov, w, 4):
                        chain.add(nxt)
            except Exception:
                pass

        import re as _re2
        qw = {w for w in _re2.findall(r"[가-힣A-Za-z]{2,}", question)}
        qstem = {w[:2] for w in qw}

        q = _vec(question)
        b = self.som.bmu_of(q)
        by, bx = divmod(b, self.som.gw)
        node_of = {}
        for node, idxs in self.assign.items():
            for i in idxs:
                node_of[i] = node

        scored = []
        for i, f in enumerate(self.facts):
            txt = f.get("text") or ""
            # 가까움 — **낱말이 겹치는 것이 가장 세다.**
            # 해시 임베딩은 뜻을 모른다. 그래서 벡터만 쓰면 '바다' 를 물어도
            # 바다 사실이 안 올라오고 최근 것만 남는다.
            fw = set(_re2.findall(r"[가-힣A-Za-z]{2,}", txt))
            hit = len(qw & fw)
            stem = len(qstem & {w[:2] for w in fw})
            word = 1.0 + 2.0 * hit + 0.6 * stem

            sim = float(q @ _vec(txt))
            node = node_of.get(i)
            if node is not None:
                ny, nx = divmod(node, self.som.gw)
                d = abs(ny - by) + abs(nx - bx)
                near = word * (sim + 1.0 / (1.0 + d))
            else:
                near = word * sim
            # 강함
            strong = float(f.get("strength") or 0.5)
            # 새로움 — 최근일수록 1에 가깝다 (30일 반감)
            age = self._age_days(f, now)
            fresh = 0.5 + 0.5 * (0.5 ** (age / 30.0))
            # 이어짐
            link = 1.3 if (chain and any(c in txt for c in chain)) else 1.0

            scored.append((near * strong * fresh * link, i))

        scored.sort(key=lambda t: -t[0])
        out, seen = [], set()
        for _, i in scored:
            f = self.facts[i]
            key = f.get("text")
            if key and key not in seen:
                seen.add(key)
                out.append(f)
            if len(out) >= k:
                break
        return mark_conflicts(out)

    @staticmethod
    def _age_days(f: dict, now: float) -> float:
        """얼마나 묵었나. 모르면 중간값으로 둔다."""
        for key in ("updated_at", "created_at"):
            v = f.get(key)
            if not v:
                continue
            try:
                from datetime import datetime, timezone
                t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                return max(0.0, (now - t.timestamp()) / 86400)
            except Exception:
                pass
        return 30.0

    def _near(self, question: str, k: int) -> list[dict]:
        """질문 벡터의 최적 노드와 그 이웃 노드에 얹힌 사실들."""
        import re as _re2
        qw = {w for w in _re2.findall(r"[가-힣A-Za-z]{2,}", question)}
        qstem = {w[:2] for w in qw}

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


# ── 어긋난 것은 숨기지 않는다 ──────────────────────────────
def mark_conflicts(facts: list) -> list:
    """
    꺼낸 것들 중 **서로 어긋나는 짝**에 표시를 남긴다.

    왜 하나를 고르지 않나
      확신이 0.6 과 0.55 로 비슷할 때 높은 쪽만 넣으면, 그 차이가
      의미 있는지 아무도 모르는 채 **조용히 한쪽이 버려진다.**
      그리고 왜 그렇게 답했는지 기록에도 안 남는다.

      모르는 것은 모른다고 하는 편이 낫다. 둘 다 넣되 어긋났다고
      적어두면, 몰랑이가 "어느 쪽이더라?" 하고 물을 수 있다.
      스스로 못 푸는 것을 사람에게 가져오는 것이 이 구조의 방식이다.
    """
    try:
        import belief_decay as _bd
    except Exception:
        return facts
    seen = set()
    for i, a in enumerate(facts):
        ta = a.get("text") or ""
        for b in facts[i + 1:]:
            tb = b.get("text") or ""
            if (ta, tb) in seen:
                continue
            try:
                if not _bd._opposed(ta, tb):
                    continue
            except Exception:
                continue
            seen.add((ta, tb))
            a["conflict_with"] = tb[:60]
            b["conflict_with"] = ta[:60]
    return facts


def conflict_note(facts: list) -> str:
    """프롬프트에 붙일 한 줄 — 어긋난 것이 있으면 알린다."""
    pairs, done = [], set()
    for f in facts or []:
        c = f.get("conflict_with")
        if not c:
            continue
        key = tuple(sorted([f.get("text", "")[:60], c]))
        if key in done:
            continue
        done.add(key)
        pairs.append(key)
    if not pairs:
        return ""
    body = "\n".join(f"  · \"{a}\" ↔ \"{b}\"" for a, b in pairs[:3])
    return ("[어긋나는 기억]\n" + body +
            "\n(둘 다 알고 있지만 어느 쪽이 맞는지 모른다. "
            "이야기 중에 자연스럽게 물어봐도 된다. 아는 척 고르지 마라.)\n")
