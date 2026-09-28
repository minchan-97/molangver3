"""
land.py — 집 바깥의 지형. 활동 반경이 넓어지면 생긴다.

집과 무엇이 다른가
  집  안에서 물건을 만들고 옮긴다. **바뀐다.**
  지형 한 번 생기면 그 자리에 머문다. **재배열되지 않는다.**
       바다가 오늘 동쪽에 있었으면 내일도 동쪽이다.
       그래야 '멀리 간다'는 말이 뜻을 갖는다.

어떻게 생기나 (GSOM 의 성장을 그대로 빌린다)
  · 관심이 한 방향으로 오래 쌓이면 격자 가장자리에 새 자리가 생긴다.
  · 그 자리의 결(관심 낱말들)이 무엇인지 보고 지형을 정한다.
      바다·파도·물   → 바다
      산·바위·높이   → 산
      나무·풀·숲     → 숲
      길·마을·사람   → 마을
      모래·빛·더위   → 들판
  · 지형은 집에서 얼마나 먼지(거리)를 갖는다. 멀수록 가기 어렵다.

무엇을 하나
  · 가면 그 지형의 결이 관심에 크게 얹힌다 (집보다 세게 — 나갔으니까)
  · 자극(밝기·소리·바람·냄새)이 있고, 그게 기분에 닿는다
  · 처음 간 곳은 사실로 남는다 ("바다를 처음 보았다")

왜 지형은 안 바뀌나
  집은 자기 것이라 마음대로 해도 되지만, 세상은 그렇지 않다.
  그 차이를 몸으로 아는 것이 '바깥'이 있다는 뜻이다.
"""
from __future__ import annotations
import math
import random
import time

import numpy as np

DIM = 64
GROW_AFTER = 3.0        # 관심이 이만큼 쌓인 방향으로 지형이 생긴다
MAX_PLACES = 12
VISIT_WEIGHT = 0.10     # 지형에서 오는 자극 (집의 0.04 보다 세다)

# 결 → 지형. 낱말이 겹치는 만큼 그 지형이 된다.
KINDS = {
    "바다": (["바다", "파도", "물", "해변", "소금", "배", "섬", "해운대"],
             {"밝기": 0.8, "소리": 0.7, "바람": 0.9, "냄새": 0.8}),
    "산":   (["산", "바위", "언덕", "높이", "골짜기", "정상", "돌"],
             {"밝기": 0.6, "소리": 0.2, "바람": 0.7, "냄새": 0.4}),
    "숲":   (["숲", "나무", "풀", "잎", "그늘", "이끼", "새"],
             {"밝기": 0.4, "소리": 0.5, "바람": 0.4, "냄새": 0.7}),
    "마을": (["마을", "길", "사람", "집들", "가게", "시장", "경전철"],
             {"밝기": 0.7, "소리": 0.9, "바람": 0.3, "냄새": 0.6}),
    "들판": (["들", "모래", "빛", "하늘", "구름", "지평선", "바람"],
             {"밝기": 0.9, "소리": 0.3, "바람": 0.8, "냄새": 0.3}),
    "물가": (["강", "시내", "연못", "물가", "돌다리", "물고기"],
             {"밝기": 0.6, "소리": 0.5, "바람": 0.4, "냄새": 0.5}),
}


def _vec(text: str):
    from organism.embedder import hashed_embedding
    return hashed_embedding(text or "", dim=DIM)


# ── 저장 ─────────────────────────────────────────────────────
def blank() -> dict:
    return {"places": [], "visits": {}, "log": []}


def load(sb) -> dict:
    try:
        rows = (sb.table("molang_land").select("layout")
                .eq("id", 1).limit(1).execute().data) or []
        if rows and rows[0].get("layout"):
            d = rows[0]["layout"]
            for k, v in blank().items():
                d.setdefault(k, v)
            return d
    except Exception:
        pass
    return blank()


def save(sb, land: dict):
    try:
        land["log"] = (land.get("log") or [])[-60:]
        sb.table("molang_land").upsert(
            {"id": 1, "layout": land}, on_conflict="id").execute()
        return True
    except Exception:
        return False


# ── 생김 ─────────────────────────────────────────────────────
def _kind_of(words) -> tuple:
    """관심 낱말 묶음이 어느 지형에 가까운가."""
    v = _vec(" ".join(words))
    best, score = None, -1.0
    for name, (keys, _) in KINDS.items():
        s = float(v @ _vec(" ".join(keys)))
        if any(k in " ".join(words) for k in keys):
            s += 0.35                      # 낱말이 직접 겹치면 확실히
        if s > score:
            best, score = name, s
    return best, score


def maybe_grow(land: dict, interests: dict, log=print) -> dict | None:
    """
    관심이 한쪽으로 쌓이면 바깥에 자리가 하나 생긴다.
    이미 있는 지형과 같은 종류면 만들지 않는다 (바다가 둘일 필요는 없다).
    """
    if len(land.get("places", [])) >= MAX_PLACES:
        return None
    top = [(t, w) for t, w in sorted((interests or {}).items(),
                                     key=lambda kv: -kv[1])[:8] if w >= 0.3]
    if not top:
        return None
    total = sum(w for _, w in top)
    if total < GROW_AFTER:
        return None

    kind, score = _kind_of([t for t, _ in top])
    if not kind or score < 0.15:
        return None
    if any(p["kind"] == kind for p in land["places"]):
        return None

    # 집에서 얼마나 먼가 — 나중에 생길수록 멀다 (반경이 넓어진다)
    dist = 2.0 + 1.5 * len(land["places"])
    # 무엇 때문에 생겼는지 — 그 지형과 실제로 겹친 관심만 적는다
    keys = KINDS[kind][0]
    cause = [t for t, _ in top
             if any(k in t or t in k for k in keys)] or [t for t, _ in top[:2]]
    place = {"kind": kind, "dist": round(dist, 1),
             "born": time.time(), "from": cause[:3],
             "stim": KINDS[kind][1]}
    land["places"].append(place)
    land.setdefault("log", []).append(
        {"at": time.time(), "what": "생김", "kind": kind,
         "from": place["from"]})
    log(f"  지형 생김: {kind} (거리 {dist} · {', '.join(place['from'])} 에서)")
    return place


# ── 나감 ─────────────────────────────────────────────────────
def maybe_go(land: dict, state, mood_entry: dict = None, rng=None,
             log=print) -> dict | None:
    """
    바깥에 나갈까. 멀수록 어렵고, 심심하면 멀리 간다.
    (기분이 행동을 바꾸는 자리 — 금지가 아니라 가중치)
    """
    rng = rng or random.Random(time.time_ns())
    places = land.get("places") or []
    if not places:
        return None

    name = (mood_entry or {}).get("name")
    urge = {"심심함": 0.75, "들뜸": 0.5}.get(name, 0.25)
    if rng.random() > urge:
        return None

    visits = land.get("visits") or {}
    scored = []
    for p in places:
        been = visits.get(p["kind"], 0)
        fresh = 1.0 / (1.0 + been)          # 처음 가는 곳이 끌린다
        reach = 1.0 / (1.0 + p["dist"] / 6.0)   # 먼 곳은 어렵다
        scored.append((fresh * reach * (1.0 + rng.random() * 0.3), p))
    scored.sort(key=lambda x: -x[0])
    place = scored[0][1]

    visits[place["kind"]] = visits.get(place["kind"], 0) + 1
    land["visits"] = visits
    first = visits[place["kind"]] == 1

    # 지형의 결이 관심에 — 집보다 세게. 나갔으니까.
    words = KINDS[place["kind"]][0]
    bumped = []
    for w in words[:3]:
        old = float((state.interests or {}).get(w, 0.0))
        state.interests[w] = max(0.0, min(5.0, old + VISIT_WEIGHT *
                                          (1.8 if first else 1.0)))
        bumped.append(w)

    land.setdefault("log", []).append(
        {"at": time.time(), "what": "다녀옴", "kind": place["kind"],
         "first": first})
    log(f"  바깥: {place['kind']} 에 다녀옴"
        + (" (처음)" if first else "") + f" · 거리 {place['dist']}")
    return {"place": place, "first": first, "bumped": bumped,
            "stim": place["stim"]}


def stim_to_mood(out: dict) -> dict:
    """
    자극이 기분에 닿는다.
    밝고 바람 불면 들뜨고, 어둡고 조용하면 가라앉는다.
    """
    if not out:
        return {}
    s = out.get("stim") or {}
    lift = (s.get("밝기", 0.5) * 0.4 + s.get("바람", 0.5) * 0.3
            + s.get("냄새", 0.5) * 0.3)
    noise = s.get("소리", 0.5)
    return {"lift": round(lift, 2), "noise": round(noise, 2),
            "note": ("환하고 바람이 좋다" if lift > 0.65 else
                     "조용하고 어둑하다" if lift < 0.4 else "")}


def describe(land: dict) -> str:
    ps = land.get("places") or []
    if not ps:
        return ""
    v = land.get("visits") or {}
    return "[바깥] " + " · ".join(
        f"{p['kind']}(거리 {p['dist']}{', 가본 적 없음' if not v.get(p['kind']) else ''})"
        for p in ps)

