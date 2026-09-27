"""
home.py — 몰랑이와 피우피우가 사는 집.

왜 집인가
  둘은 감각이 거의 없다. 검색 결과와 대화가 입력의 전부다.
  카메라로 바깥을 보는 건 아직 못 하지만, **자기들만의 공간**은 가질 수 있다.
  그리고 공간이 있으면 세 가지가 생긴다.

    1) 관심의 방향   있는 곳이 궁금한 것을 바꾼다 (부엌에 오래 있으면 재료가 궁금해진다)
    2) 기억의 자리   '어디서 있었던 일'인지가 남는다
    3) 대화의 계기   같은 방에 있으면 말이 더 오간다 (다른 방이어도 대화는 된다)

  순서가 중요하다. 이 집은 돌아다니기 위한 무대가 아니라,
  **관심이 자라는 밭**이다.

어떻게 두나
  방마다 '결'이 있다 (낱말 몇 개). 그 낱말을 벡터로 만들어 방의 좌표로 쓴다.
  누군가의 관심 벡터가 방의 좌표와 가까우면 그 방에 끌린다.
  머물면 그 방의 결이 관심에 조금씩 스민다 — 그게 이 집의 핵심이다.

자율
  닫힌 공간이라 위험이 없다. 그래서 스스로 하게 둔다.
    · 물건을 옮기거나 새로 만든다 (요즘 관심에서 이름을 얻는다)
    · 자주 가는 방이 생기고, 안 가는 방은 먼지가 앉는다
  무엇을 만들어두고 어디에 오래 있었는지가 성격의 기록이 된다.
"""
from __future__ import annotations
import math
import random
import time

import numpy as np

DIM = 64
DWELL_WEIGHT = 0.05      # 머문 방의 결이 관심에 스미는 정도
MOVE_TEMP = 0.8          # 낮으면 늘 같은 방, 높으면 아무 데나
BUILD_CHANCE = 0.25      # 회차마다 뭔가 만들거나 옮길 확률

ROOMS = {
    "부엌": ["재료", "굽기", "발효", "맛", "냄비", "빵"],
    "서재": ["책", "기록", "역사", "언어", "지도", "수학"],
    "창가": ["하늘", "날씨", "구름", "바다", "빛", "계절"],
    "작업방": ["만들기", "도구", "종이", "색", "기계", "고치기"],
    "마당": ["흙", "씨앗", "벌레", "새", "나무", "바람"],
    "다락": ["오래된", "상자", "추억", "먼지", "사진", "편지"],
}


def _vec(text: str):
    from organism.embedder import hashed_embedding
    return hashed_embedding(text or "", dim=DIM)


def room_vectors() -> dict:
    return {name: _vec(" ".join(words)) for name, words in ROOMS.items()}


def interest_vector(interests: dict, top=8):
    """지금 관심을 하나의 방향으로."""
    items = sorted((interests or {}).items(), key=lambda kv: -kv[1])[:top]
    if not items:
        return np.zeros(DIM)
    v = np.zeros(DIM)
    for t, w in items:
        v += _vec(t) * float(w)
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


# ── 집 상태 ──────────────────────────────────────────────────
def blank() -> dict:
    return {"where": {"molang": "창가", "piupiu": "부엌"},
            "objects": {r: [] for r in ROOMS},
            "visits": {r: 0 for r in ROOMS},
            "log": []}


def load(sb) -> dict:
    try:
        rows = (sb.table("molang_home").select("layout")
                .eq("id", 1).limit(1).execute().data) or []
        if rows and rows[0].get("layout"):
            h = rows[0]["layout"]
            for k, v in blank().items():
                h.setdefault(k, v)
            return h
    except Exception:
        pass
    return blank()


def save(sb, home: dict):
    try:
        home["log"] = (home.get("log") or [])[-60:]
        sb.table("molang_home").upsert(
            {"id": 1, "layout": home}, on_conflict="id").execute()
        return True
    except Exception:
        return False


# ── 움직임 ───────────────────────────────────────────────────
def move(home: dict, who: str, interests: dict, rng=None) -> str:
    """
    어디로 갈까. 관심과 가까운 방에 끌리되, 늘 같은 방만 가지 않게
    최근에 많이 간 방은 조금 식힌다(새로움).
    """
    rng = rng or random.Random(time.time_ns())
    iv = interest_vector(interests)
    rv = room_vectors()
    visits = home.get("visits") or {}
    total = max(1, sum(visits.values()))

    scores = {}
    for name, v in rv.items():
        pull = float(iv @ v) if iv.any() else 0.0
        fresh = 1.0 - 0.5 * (visits.get(name, 0) / total)
        objs = len((home.get("objects") or {}).get(name, []))
        scores[name] = (pull + 0.15 * math.log1p(objs)) * fresh

    names = list(scores)
    z = [math.exp(scores[n] / max(1e-6, MOVE_TEMP)) for n in names]
    tot = sum(z)
    r = rng.random() * tot
    acc = 0.0
    picked = names[-1]
    for n, w in zip(names, z):
        acc += w
        if acc >= r:
            picked = n
            break

    home.setdefault("where", {})[who] = picked
    home.setdefault("visits", {})[picked] = visits.get(picked, 0) + 1
    return picked


def dwell(state, room: str, weight: float = DWELL_WEIGHT, rng=None) -> list:
    """
    머문 방의 결이 관심에 스민다. **이 집의 핵심.**
    부엌에 오래 있으면 재료가 궁금해지고, 다락에 있으면 옛것이 떠오른다.

    다만 방의 낱말을 그대로 관심사로 넣으면 '책·기록·역사' 같은 일반어가
    관심 지형을 채운다. 그래서 두 갈래로 나눈다.
      · 이미 있는 관심 중 그 방의 결과 가까운 것을 **밀어준다** (주된 효과)
      · 새 낱말은 가끔, 아주 작게만 들어온다 (씨앗 하나 떨어지듯)
    """
    rng = rng or random.Random(time.time_ns())
    words = ROOMS.get(room, [])
    if not words:
        return []
    rv = _vec(" ".join(words))
    bumped = []

    # 1) 이 방과 가까운 '기존 관심'을 밀어준다
    for t, w in sorted((state.interests or {}).items(), key=lambda kv: -kv[1])[:20]:
        sim = float(rv @ _vec(t))
        if sim > 0.25:
            state.interests[t] = max(0.0, min(5.0, w + weight * sim * 2))
            bumped.append(t)
        if len(bumped) >= 3:
            break

    # 2) 새 낱말은 가끔 하나만, 작게
    if rng.random() < 0.25:
        w0 = rng.choice(words)
        old = float((state.interests or {}).get(w0, 0.0))
        state.interests[w0] = max(0.0, min(5.0, old + weight * 0.4))
        bumped.append(w0)
    return bumped[:4]


# ── 자율: 꾸미기 ─────────────────────────────────────────────
def build(home: dict, who: str, interests: dict, rng=None) -> dict | None:
    """
    요즘 관심에서 이름을 얻어 물건을 만들거나 옮긴다.
    무엇을 만들어뒀는지가 그 시기의 기록이 된다.
    """
    rng = rng or random.Random(time.time_ns())
    if rng.random() > BUILD_CHANCE:
        return None
    top = [t for t, _ in sorted((interests or {}).items(),
                                key=lambda kv: -kv[1])[:6]]
    if not top:
        return None
    try:
        from organism.curiosity import _is_topic_like
        top = [t for t in top if _is_topic_like(t)]
    except Exception:
        pass
    if not top:
        return None

    room = home.get("where", {}).get(who) or rng.choice(list(ROOMS))
    objs = home.setdefault("objects", {}).setdefault(room, [])
    name = rng.choice(top)

    if objs and rng.random() < 0.3:          # 옮기기
        item = objs.pop(rng.randrange(len(objs)))
        other = rng.choice([r for r in ROOMS if r != room])
        home["objects"].setdefault(other, []).append(item)
        ev = {"at": time.time(), "who": who, "what": "옮김",
              "item": item.get("name"), "from": room, "to": other}
    else:                                    # 만들기
        if any(o.get("name") == name for o in objs):
            return None
        item = {"name": name, "by": who, "at": time.time()}
        objs.append(item)
        home["objects"][room] = objs[-8:]     # 방마다 여덟 개까지
        ev = {"at": time.time(), "who": who, "what": "만듦",
              "item": name, "room": room}
    home.setdefault("log", []).append(ev)
    return ev


# ── 한 회차 ──────────────────────────────────────────────────
def tick(sb, state, piu_interests: dict = None, rng=None, log=print) -> dict:
    """집에서 일어나는 한 회차. 관심 → 이동 → 머묾 → 꾸미기."""
    rng = rng or random.Random(time.time_ns())
    home = load(sb)

    mol_room = move(home, "molang", state.interests, rng)
    piu_room = move(home, "piupiu", piu_interests or state.interests, rng)

    bumped = dwell(state, mol_room, rng=rng)   # 관심의 방향 (1순위)
    if piu_interests is not None:              # 피우피우도 제 방의 결을 받는다
        dwell(type("S", (), {"interests": piu_interests})(), piu_room, rng=rng)
    built = [e for e in (build(home, "molang", state.interests, rng),
                         build(home, "piupiu", piu_interests or state.interests,
                               rng)) if e]

    save(sb, home)
    same = mol_room == piu_room
    log(f"  집: 몰랑이 {mol_room} · 피우피우 {piu_room}"
        + ("  (같은 방)" if same else "")
        + (f" · {built[0]['who']}가 {built[0]['item']}를 {built[0]['what']}"
           if built else ""))
    return {"molang": mol_room, "piupiu": piu_room, "same_room": same,
            "dwell_bumped": bumped, "built": built,
            "objects": {r: [o["name"] for o in v]
                        for r, v in (home.get("objects") or {}).items() if v}}


def describe(home: dict) -> str:
    """집을 한 줄로 (프롬프트에 넣을 때)."""
    w = home.get("where") or {}
    objs = home.get("objects") or {}
    here = ", ".join(f"{k}: {v}" for k, v in w.items())
    stuff = "; ".join(f"{r}({', '.join(o['name'] for o in v)})"
                      for r, v in objs.items() if v)
    return f"[집] {here}" + (f" · 물건 — {stuff}" if stuff else "")
