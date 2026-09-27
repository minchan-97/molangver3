"""
mood.py — 몰랑이의 기분. 네 축으로.

왜 필요한가
  지금 몰랑이는 목적에 따라 움직이지만, **왜 그게 좋은지**에 대한 내부 신호가
  없다. 표정은 답변에서 판별한 것이고, 꿈의 feeling 은 LLM 이 쓴 낱말이다.
  안쪽이 비어 있다.

네 축 (한쪽으로 쏠리지 않게 서로를 막는다)
  1. 새로움      처음 만난 것        — **작은** 상
  2. 굳음        처음 확신이 된 것    — **큰** 상
  3. 되씹기      이미 아는 걸 또 확인  — 상 거의 없음
  4. 심심함      알 게 너무 없을 때    — 불편 (밖으로 나가게)

  왜 이렇게 나누나
    새것만 상을 주면 계속 옮겨 다니며 아무것도 안 배운다.
    굳는 것만 상을 주면 아는 것만 되씹는다.
    그래서 **반쯤 아는 것**(미확신·격리·열린 구멍)이 가장 끌리는 자리가 되게 한다.
    그리고 그마저 떨어지면 심심해져서 밖으로 나간다.

놀람은 무엇으로 재나
  이미 만들어 둔 NM 엔진(neural_markov_engine)이 있으면 그걸 쓴다.
  avg_logp 와 캘리브레이션(mu/std)으로 "이 글이 얼마나 예상 밖인가"가 나온다.
  없으면 임베딩 거리로 대신한다 — 있는 것으로 굴러가게.

기분이 하는 일
  · 주제 고르기에 힘을 싣는다 (심심하면 탐색 쪽, 불안하면 굳히는 쪽)
  · 먼저 말 걸기의 계기가 된다 (심심함 / 벅참)
  · 기록으로 남아 나중에 추세를 볼 수 있다
기분은 판단을 대신하지 않는다. 가중치로만 작용한다.
"""
from __future__ import annotations
import math
import time

W_NEW = 0.25          # 새로움 — 작게
W_SETTLED = 1.0       # 처음 굳음 — 크게
W_REPEAT = 0.05       # 되씹기 — 거의 없음
BORED_BELOW = 0.18    # 불안이 이보다 낮으면 심심하다
OVERWHELMED = 0.75    # 이보다 높으면 벅차다
KEEP = 120


# ── 지금 상태 재기 ───────────────────────────────────────────
def measure(sb, identity, state=None) -> dict:
    """
    불안(엔트로피)과 그 원인.
    반쯤 아는 것이 많을수록 높다 — 모르는 게 많아서가 아니라 **덜 정해져서**.
    """
    unsure = settled = 0
    try:
        for f in identity.learned_facts:
            s = f.get("strength") or 0
            if 0.2 < s < 0.6:
                unsure += 1
            elif s >= 0.8:
                settled += 1
    except Exception:
        pass

    pending = 0
    try:
        r = (sb.table("organism_observations").select("id", count="exact")
             .eq("status", "quarantine").execute())
        pending = r.count or 0
    except Exception:
        pass

    qe = float(getattr(state, "last_qe", 0.0) or 0.0) if state else 0.0

    # 미확신·격리가 많을수록, 지도가 어수선할수록 높다
    raw = unsure * 0.8 + pending * 0.5 + qe * 6.0
    unrest = 1.0 - math.exp(-raw / 14.0)
    return {"unrest": round(unrest, 3), "unsure": unsure,
            "settled": settled, "pending": pending, "qe": round(qe, 3)}


# ── 놀람 (NM 엔진이 있으면 그걸로) ───────────────────────────
def surprise(texts, engine=None) -> float:
    """이 글들이 얼마나 예상 밖인가. 0(익숙) ~ 1(낯섦)."""
    if not texts:
        return 0.0
    if engine is not None and getattr(engine, "is_trained", False):
        try:
            zs = []
            for t in texts[:5]:
                r = engine.evaluate(t)
                lp = r.get("avg_logp")
                if lp is None:
                    continue
                z = (lp - engine.mu) / max(1e-6, engine.std)
                zs.append(1.0 / (1.0 + math.exp(z)))   # 낮은 logp = 낯섦
            if zs:
                return round(sum(zs) / len(zs), 3)
        except Exception:
            pass
    # 엔진이 없으면 임베딩 거리로 (있는 것으로 굴린다)
    try:
        import numpy as np
        from organism.embedder import hashed_embedding
        V = np.array([hashed_embedding(t, dim=64) for t in texts[:8]])
        if len(V) < 2:
            return 0.5
        S = V @ V.T
        np.fill_diagonal(S, 0)
        return round(float(1.0 - S.mean()), 3)
    except Exception:
        return 0.5


# ── 사건 → 기쁨 ─────────────────────────────────────────────
def reward(events: dict) -> dict:
    """
    이번 회차에 무슨 일이 있었나 → 기쁨.
      events: {"new": n, "settled": n, "repeat": n}
    """
    new = events.get("new", 0)
    settled = events.get("settled", 0)
    repeat = events.get("repeat", 0)
    joy = (W_NEW * math.log1p(new)
           + W_SETTLED * math.log1p(settled)
           + W_REPEAT * math.log1p(repeat))
    return {"joy": round(min(1.0, joy), 3),
            "from": {"새로움": new, "굳음": settled, "되씹기": repeat}}


def feel(sb, identity, state=None, events=None, engine=None,
         texts=None, log=print) -> dict:
    """한 회차의 기분. 상태 + 사건 + 놀람."""
    m = measure(sb, identity, state)
    r = reward(events or {})
    s = surprise(texts or [], engine)

    unrest = m["unrest"]
    if unrest < BORED_BELOW:
        name, note = "심심함", "알 게 너무 없다 — 밖으로 나가야 한다"
    elif unrest > OVERWHELMED:
        name, note = "벅참", "덜 정해진 게 너무 많다 — 하나씩 굳혀야 한다"
    elif r["joy"] >= 0.5:
        name, note = "뿌듯함", "아는 것이 단단해졌다"
    elif s >= 0.6:
        name, note = "들뜸", "낯선 것을 만났다"
    else:
        name, note = "잔잔함", ""

    entry = {"at": time.time(), "name": name, "unrest": unrest,
             "joy": r["joy"], "surprise": s, "note": note,
             "detail": {**m, **r["from"]}}

    if state is not None:
        hist = list(getattr(state, "moods", []) or [])
        hist.append(entry)
        state.moods = hist[-KEEP:]

    log(f"  기분: {name} (불안 {unrest:.2f} · 기쁨 {r['joy']:.2f} · 놀람 {s:.2f})")
    return entry


# ── 기분이 행동에 주는 힘 ────────────────────────────────────
def bias(entry: dict) -> dict:
    """
    주제 고르기에 실을 힘.
      심심하면 밖으로 (탐색 ↑), 벅차면 안으로 (굳히기 ↑).
    금지가 아니라 가중치다.
    """
    name = (entry or {}).get("name")
    if name == "심심함":
        return {"explore": 0.65, "consolidate": 0.15,
                "why": "알 게 없어 새것을 찾는다"}
    if name == "벅참":
        return {"explore": 0.20, "consolidate": 0.80,
                "why": "덜 정해진 것부터 굳힌다"}
    if name == "들뜸":
        return {"explore": 0.55, "consolidate": 0.35, "why": "낯선 쪽으로"}
    return {"explore": 0.40, "consolidate": 0.45, "why": ""}


def recent(state, n=10) -> list:
    return (getattr(state, "moods", []) or [])[-n:]


def trend(state, n=20) -> dict:
    """추세 — 나아지고 있나."""
    h = recent(state, n)
    if len(h) < 4:
        return {}
    half = len(h) // 2
    old = sum(x["unrest"] for x in h[:half]) / half
    new = sum(x["unrest"] for x in h[half:]) / (len(h) - half)
    return {"unrest_was": round(old, 3), "unrest_now": round(new, 3),
            "direction": "가라앉는 중" if new < old - 0.03
            else "오르는 중" if new > old + 0.03 else "비슷"}
