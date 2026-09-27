"""
logic_check.py — 새 사고 구조가 정합적인지 **로컬에서** 판정한다.

왜 LLM 이 아닌가
  LLM 에게 "이 설계가 논리적인가"를 물으면 매번 기준이 달라지고, 그 기준이
  어디에도 남지 않는다. 판단 틀은 바깥에 두고 검사 가능해야 한다는 원칙이
  여기서도 같다. nm_guard 가 출처를 재듯, 이 파일은 **구조를 잰다.**

두 겹
  1) 규칙 (즉시, 공짜)
     명백히 어긋난 것을 쳐낸다. 아래 여섯 가지.
  2) 작은 신경망 (배운다)
     규칙을 통과한 설계의 특징 벡터를 보고 점수를 매긴다.
     정답은 나중에 온다 — 만들어진 유형이 실제로 쓰였으면 좋은 설계,
     쓰이지 않고 시들었으면 나쁜 설계. 그 결과로 다시 배운다.
     (처음에는 데이터가 없으니 규칙만으로 통과시킨다)

재는 것 (전부 임베딩 위에서)
  갈래 배타성   갈래끼리 너무 비슷하면 그건 갈림길이 아니다
  갈래 연결성   갈래가 앞 단계와 아무 상관 없으면 맥락 이탈
  단계 전진성   단계끼리 너무 비슷하면 같은 일을 반복하는 것
  중복도        기존 유형과 겹치는 정도
  꼴            단계 수, 갈래 수
"""
from __future__ import annotations
import numpy as np

DIM = 64

# 규칙 문턱
MAX_BRANCH_SIM = 0.80      # 갈래끼리 이보다 비슷하면 같은 말
MIN_BRANCH_LINK = 0.05     # 갈래가 앞 단계와 이만큼도 안 이어지면 이탈
MAX_STEP_SIM = 0.88        # 단계끼리 이보다 비슷하면 같은 일 반복
PASS_SCORE = 0.35          # 신경망 점수 문턱


def _vec(text: str):
    from organism.embedder import hashed_embedding
    return hashed_embedding(text or "", dim=DIM)


def _text(d: dict) -> str:
    return f"{d.get('name','')} {d.get('directive','')}".strip()


def _sim(a, b) -> float:
    return float(np.dot(a, b))


# ── 1겹: 규칙 ────────────────────────────────────────────────
def rule_check(design: dict, registry=None) -> dict:
    steps = design.get("steps") or []
    branches = design.get("branches") or []

    if not (2 <= len(steps) <= 4):
        return {"ok": False, "why": f"단계가 {len(steps)}개 (2~4 이어야)"}
    if not (2 <= len(branches) <= 3):
        return {"ok": False, "why": f"갈래가 {len(branches)}개 (2~3 이어야)"}

    sv = [_vec(_text(s)) for s in steps]
    bv = [_vec(_text(b)) for b in branches]

    # 갈래끼리 너무 비슷하면 갈림길이 아니다
    bsim = max((_sim(bv[i], bv[j]) for i in range(len(bv))
                for j in range(i + 1, len(bv))), default=0.0)
    if bsim > MAX_BRANCH_SIM:
        return {"ok": False, "why": f"갈래가 서로 너무 비슷함({bsim:.2f})"}

    # 갈래 이름이 같거나 한쪽이 다른쪽에 들어가면 같은 말
    names = [str(b.get("name", "")).strip() for b in branches]
    if len(set(names)) < len(names):
        return {"ok": False, "why": "갈래 이름이 겹침"}

    # 갈래가 앞 단계와 이어지는가
    link = max(_sim(bvv, sv[-1]) for bvv in bv)
    if link < MIN_BRANCH_LINK:
        return {"ok": False, "why": f"갈래가 앞 단계와 안 이어짐({link:.2f})"}

    # 단계끼리 같은 일을 반복하는가
    ssim = max((_sim(sv[i], sv[i + 1]) for i in range(len(sv) - 1)), default=0.0)
    if ssim > MAX_STEP_SIM:
        return {"ok": False, "why": f"단계가 같은 일을 반복함({ssim:.2f})"}

    # 기존 유형과의 중복은 registry 쪽 검사에 맡긴다 (여기선 특징으로만)
    return {"ok": True, "bsim": bsim, "link": link, "ssim": ssim}


# ── 특징 ────────────────────────────────────────────────────
def features(design: dict, registry=None) -> np.ndarray:
    steps = design.get("steps") or []
    branches = design.get("branches") or []
    sv = [_vec(_text(s)) for s in steps] or [np.zeros(DIM)]
    bv = [_vec(_text(b)) for b in branches] or [np.zeros(DIM)]

    bsim = max((_sim(bv[i], bv[j]) for i in range(len(bv))
                for j in range(i + 1, len(bv))), default=0.0)
    link = float(np.mean([_sim(b, sv[-1]) for b in bv]))
    ssim = float(np.mean([_sim(sv[i], sv[i + 1])
                          for i in range(len(sv) - 1)])) if len(sv) > 1 else 0.0
    spread = float(np.std([_sim(b, sv[-1]) for b in bv])) if len(bv) > 1 else 0.0

    dup = 0.0
    if registry is not None:
        try:
            from tree_registry import TreeRegistry
            new = TreeRegistry._step_words(steps)
            for t in registry.trees.values():
                old = TreeRegistry._step_words(
                    [{"name": n.prompt, "directive": n.directive}
                     for n in t.nodes.values()])
                if old and new:
                    dup = max(dup, len(new & old) / max(1, min(len(new), len(old))))
        except Exception:
            pass

    return np.array([bsim, link, ssim, spread, dup,
                     len(steps) / 4.0, len(branches) / 3.0, 1.0])


# ── 2겹: 작은 신경망 ─────────────────────────────────────────
class TinyScorer:
    """
    입력 8 → 은닉 6 → 1. numpy 만으로 돈다.
    '좋은 설계'의 정답은 나중에 온다: 만들어진 유형이 실제로 쓰였는가.
    """

    def __init__(self, seed=42):
        rng = np.random.default_rng(seed)
        self.W1 = rng.normal(0, 0.4, (8, 6))
        self.b1 = np.zeros(6)
        self.W2 = rng.normal(0, 0.4, (6, 1))
        self.b2 = np.zeros(1)
        self.n_trained = 0

    def score(self, x) -> float:
        x = np.asarray(x, float).reshape(1, -1)
        h = np.tanh(x @ self.W1 + self.b1)
        z = float((h @ self.W2 + self.b2).ravel()[0])
        return 1.0 / (1.0 + np.exp(-z))

    def fit(self, X, y, epochs=300, lr=0.08):
        X, y = np.asarray(X, float), np.asarray(y, float).reshape(-1, 1)
        for _ in range(epochs):
            h = np.tanh(X @ self.W1 + self.b1)
            p = 1.0 / (1.0 + np.exp(-(h @ self.W2 + self.b2)))
            d2 = (p - y) / len(X)
            gW2 = h.T @ d2
            gb2 = d2.sum(0)
            d1 = (d2 @ self.W2.T) * (1 - h ** 2)
            gW1 = X.T @ d1
            gb1 = d1.sum(0)
            for p_, g in ((self.W2, gW2), (self.b2, gb2),
                          (self.W1, gW1), (self.b1, gb1)):
                p_ -= lr * g
        self.n_trained = len(X)
        return self

    def blob(self):
        return {"W1": self.W1.tolist(), "b1": self.b1.tolist(),
                "W2": self.W2.tolist(), "b2": self.b2.tolist(),
                "n": self.n_trained}

    @classmethod
    def load(cls, d):
        m = cls()
        if not d:
            return m
        try:
            m.W1 = np.array(d["W1"]); m.b1 = np.array(d["b1"])
            m.W2 = np.array(d["W2"]); m.b2 = np.array(d["b2"])
            m.n_trained = d.get("n", 0)
        except Exception:
            pass
        return m


# ── 판정 ────────────────────────────────────────────────────
def judge(design: dict, registry=None, scorer=None) -> dict:
    r = rule_check(design, registry)
    if not r["ok"]:
        return {"ok": False, "why": r["why"], "stage": "rule"}
    x = features(design, registry)
    if scorer is None or scorer.n_trained < 8:
        # 아직 배운 게 없다 — 규칙만으로 통과시킨다 (애기는 단순하게 시작한다)
        return {"ok": True, "score": None, "stage": "rule", "features": x.tolist()}
    s = scorer.score(x)
    return {"ok": s >= PASS_SCORE, "score": round(s, 3), "stage": "model",
            "why": None if s >= PASS_SCORE else f"구조 점수 낮음({s:.2f})",
            "features": x.tolist()}


def learn_from_outcomes(registry, scorer=None, log=print):
    """
    결과로 배운다. 만들어진 유형이 실제로 쓰였으면 1, 시들거나 안 쓰였으면 0.
    creation_log 에 남겨둔 특징 벡터를 그대로 쓴다.
    """
    X, y = [], []
    for c in (getattr(registry, "creation_log", []) or []):
        f = c.get("features")
        if not f:
            continue
        tid = c.get("type_id")
        used = registry.usage_count.get(tid, 0)
        alive = tid in registry.trees
        X.append(f)
        y.append(1.0 if (alive and used >= 2) else 0.0)
    if len(X) < 8 or len(set(y)) < 2:
        return scorer, {"trained": False, "n": len(X)}
    sc = (scorer or TinyScorer()).fit(X, y)
    log(f"  구조 판정기 학습: {len(X)}건 (좋음 {int(sum(y))})")
    return sc, {"trained": True, "n": len(X), "good": int(sum(y))}
