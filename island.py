"""
island.py — 캐럿 아일랜드. 가서 며칠 머물며 돌아다니는 섬.

집(home)과 무엇이 다른가
  집   여섯 방. 혼자 돌아다닌다. 늘 거기 있다.
  섬   열 곳 남짓. **둘이 함께** 다닌다. 며칠만 머문다. 돌아온다.

어떻게 만드나
  집과 같은 방식 — SOM 격자에 장소를 얹어 좌표와 거리를 만든다.
  그래서 호텔에서 바다는 가깝고 등산은 멀다, 같은 것이 생긴다.
  이동은 거리만큼 힘들다.

가는 길
  집 → **공항**(집 격자에서 가장 먼 자리) → 비행기 → 섬.
  돌아올 때도 공항을 거친다. 그래야 '떠난다'가 뜻을 갖는다.

머무는 동안
  · 회차마다 한 곳씩 옮긴다 (관심과 거리와 피로가 정한다)
  · 둘이 **같은 곳에** 있으므로 매 회차 대화한다
  · 본 것이 사진이 되고, 사실이 되고, 관심이 된다
  · 기간이 끝나면 돌아온다. 기념품을 들고.
"""
from __future__ import annotations
import math
import random
import time

import numpy as np

DIM = 64
STAY_DAYS = (3, 5)          # 머무는 회차 수 (뽑는다)
MOVE_COST = 0.08            # 멀리 갈수록 지친다
VISIT_WEIGHT = 0.16         # 섬에서 보는 것이 관심에 얹히는 정도

# 섬의 장소들. 결(낱말)이 좌표를 만든다.
SPOTS = {
    "공항":      ["비행기", "활주로", "가방", "출발", "도착"],
    "호텔":      ["침대", "창문", "아침", "쉬기", "열쇠"],
    "스파":      ["온천", "김", "따뜻함", "수건", "쉬기"],
    "식당":      ["요리", "접시", "냄새", "맛", "식탁"],
    "당근농장":  ["당근", "흙", "밭", "수확", "장갑", "체험"],
    "바닷가":    ["파도", "모래", "조개", "바닷바람", "수평선"],
    "등대":      ["등대", "언덕", "불빛", "계단", "전망"],
    "산길":      ["등산", "바위", "나무", "오르막", "정상"],
    "놀이공원":  ["회전목마", "관람차", "솜사탕", "음악", "줄"],
    "시장":      ["가게", "흥정", "간식", "기념품", "사람들"],
}

# 그곳에서 볼 수 있는 것들
SCENES = {
    "공항":     ["활주로에 내려앉는 비행기", "짐을 찾는 사람들"],
    "호텔":     ["창밖으로 보이는 주황빛 지붕들", "폭신한 침대"],
    "스파":     ["김이 피어오르는 노천탕", "따뜻한 물에 번지는 빛"],
    "식당":     ["당근을 통째로 구운 요리", "식탁에 놓인 수프 두 그릇"],
    "당근농장": ["끝없이 펼쳐진 당근밭", "흙 묻은 당근을 뽑는 손",
                "밭고랑 사이로 부는 바람"],
    "바닷가":   ["파도가 밀려왔다 가는 자리", "모래에 남은 발자국 두 쌍",
                "해질 녘 주황빛 바다"],
    "등대":     ["언덕 위 하얀 등대", "등대에서 내려다본 섬 전체"],
    "산길":     ["구불구불한 오르막길", "정상에서 본 바다와 밭"],
    "놀이공원": ["천천히 도는 관람차", "솜사탕을 든 작은 그림자"],
    "시장":     ["당근 모양 물건이 가득한 가판", "간식 냄새가 나는 골목"],
}

REST = {"호텔", "스파"}      # 쉬면 피로가 풀린다
_LAYOUT = {"coords": None, "dist": None}


def _vec(text: str):
    from organism.embedder import hashed_embedding
    return hashed_embedding(text or "", dim=DIM)


def layout(seed: int = 13) -> dict:
    """장소를 격자에 얹어 좌표와 거리를 만든다 (집과 같은 방식)."""
    if _LAYOUT["coords"] is not None:
        return _LAYOUT
    names = list(SPOTS)
    try:
        from organism.som import SOM
        X = np.array([_vec(" ".join(SPOTS[n])) for n in names])
        som = SOM(grid=(6, 6), dim=DIM, seed=seed)
        som.train(X, iters=1500, seed=seed)
        pos, used = {}, set()
        for n, x in zip(names, X):
            b = som.bmu_of(x)
            while b in used:
                b = (b + 1) % (som.gh * som.gw)
            used.add(b)
            pos[n] = (b // som.gw, b % som.gw)
    except Exception:
        pos = {n: (i // 4, i % 4) for i, n in enumerate(names)}
    dist = {a: {b: float(abs(pos[a][0] - pos[b][0]) + abs(pos[a][1] - pos[b][1]))
                for b in names} for a in names}
    _LAYOUT.update(coords=pos, dist=dist)
    return _LAYOUT


def distance(a: str, b: str) -> float:
    return layout()["dist"].get(a, {}).get(b, 2.0)


# ── 떠나기 ──────────────────────────────────────────────────
def depart(tv: dict, rng=None, log=print) -> dict:
    """공항을 거쳐 섬으로. 머물 기간을 정한다."""
    rng = rng or random.Random(time.time_ns())
    days = rng.randint(*STAY_DAYS)
    trip = {"where": "캐럿 아일랜드", "at": time.time(),
            "spot": "공항", "left": days, "days": days,
            "tired": 0.0, "seen": [], "talks": []}
    tv["current"] = trip
    log(f"  ✈️ 공항에서 비행기를 탔다 — 캐럿 아일랜드, {days}일")
    return trip


def _pick_spot(trip: dict, interests: dict, rng) -> str:
    """
    어디로 갈까. 관심 × 새로움 ÷ 거리, 그리고 지치면 쉬는 곳으로.
    """
    here = trip.get("spot") or "공항"
    seen = [s["spot"] for s in (trip.get("seen") or [])]
    tired = float(trip.get("tired") or 0.0)

    scores = {}
    for name, words in SPOTS.items():
        if name == here or name == "공항":
            continue
        pull = sum(float((interests or {}).get(w, 0.0)) for w in words)
        fresh = 1.0 / (1.0 + seen.count(name) * 1.5)
        far = distance(here, name)
        s = (0.4 + pull) * fresh / (1.0 + far * 0.25)
        if tired > 0.5 and name in REST:
            s *= 3.0 + 4.0 * (tired - 0.5)   # 지칠수록 쉬는 곳이 끌린다
        if tired > 0.8 and name not in REST:
            s *= 0.12                        # 너무 지치면 다른 데는 못 간다
        scores[name] = s

    names = list(scores)
    total = sum(scores.values()) or 1.0
    r = rng.random() * total
    acc = 0.0
    for n in names:
        acc += scores[n]
        if acc >= r:
            return n
    return names[-1]


# ── 하루 ────────────────────────────────────────────────────
def day(sb, tv: dict, state, identity=None, piu_identity=None,
        api_key=None, rng=None, log=print) -> dict:
    """
    섬에서의 한 회차. 옮기고, 보고, 둘이 이야기하고, 기록한다.
    기간이 끝나면 돌아온다.
    """
    rng = rng or random.Random(time.time_ns())
    trip = tv.get("current")
    if not trip:
        return {"away": False}

    here = trip.get("spot") or "공항"
    tired_now = float(trip.get("tired") or 0.0)

    # 너무 지치면 그 자리에서 쉰다. 쉬는 곳이면 더 잘 풀린다.
    # (움직일수록 지치니, 쉬는 날이 있어야 여행이 이어진다)
    if tired_now > 0.95 and rng.random() < 0.7:
        spot, moved = here, 0.0
        rested = True
    else:
        spot = _pick_spot(trip, state.interests, rng)
        moved = distance(here, spot)
        rested = False
    trip["spot"] = spot
    was = float(trip.get("tired") or 0.0)
    relief = 0.7 if spot in REST else (0.3 if rested else 0.0)
    trip["tired"] = max(0.0, min(1.2, was + MOVE_COST * moved - relief))

    scene = ("그 자리에 앉아 쉬었다" if rested
             else rng.choice(SCENES.get(spot, ["조용한 풍경"])))
    photo = {"at": time.time(), "where": "캐럿 아일랜드", "spot": spot,
             "scene": scene, "with": "피우피우", "by": "함께",
             "note": f"{spot}에서 {scene}"}
    tv.setdefault("photos", []).append(photo)
    trip.setdefault("seen", []).append({"spot": spot, "scene": scene})

    # 그곳의 결이 관심에 (집보다, 바깥보다 세게 — 멀리 왔으니까)
    bumped = []
    for w in SPOTS.get(spot, [])[:3]:
        old = float((state.interests or {}).get(w, 0.0))
        state.interests[w] = max(0.0, min(5.0, old + VISIT_WEIGHT))
        bumped.append(w)

    # 둘이 같은 곳에 있으므로 매 회차 이야기한다
    talk = None
    try:
        import piupiu
        seen = {"topic": spot, "title": scene,
                "text": f"{spot}에서 {scene}을(를) 보고 있다",
                "url": None}
        res = piupiu.converse(sb, identity, piu_identity, seen,
                              api_key=api_key, log=lambda *a: None,
                              place=f"캐럿 아일랜드 {spot}", same_room=True,
                              state=state)
        talk = res.get("talk")
        if talk:
            trip.setdefault("talks", []).append(
                {"spot": spot, "molang": talk.get("molang", "")[:200],
                 "piupiu": talk.get("piupiu", "")[:200]})
    except Exception:
        pass

    if not rested:
        trip["left"] = int(trip.get("left", 1)) - 1
    log(f"  🏝️ {spot} — {scene}" + ("  (쉬는 중)" if rested else "")
        + (f"  (남은 {trip['left']}일)" if trip["left"] > 0 else "  (마지막 날)"))

    out = {"away": True, "spot": spot, "scene": scene, "bumped": bumped,
           "left": trip["left"], "tired": round(trip["tired"], 2),
           "moved": round(moved, 1), "rested": rested, "talk": bool(talk)}

    if trip["left"] <= 0:
        out["returned"] = _come_home(sb, tv, state, identity, piu_identity,
                                     rng, log)
    return out


def _come_home(sb, tv, state, identity, piu_identity, rng, log) -> dict:
    """돌아온다. 기념품과 사실이 남는다."""
    trip = tv.pop("current", None)
    if not trip:
        return {}
    seen = trip.get("seen") or []
    best = rng.choice(seen) if seen else {"spot": "섬", "scene": "풍경"}

    souvenirs = {"당근농장": "흙이 조금 묻은 당근 모양 열쇠고리",
                 "시장": "당근 모양 나무 인형",
                 "바닷가": "주황색 조개껍데기",
                 "등대": "등대가 그려진 엽서",
                 "놀이공원": "관람차 모양 뱃지",
                 "스파": "온천물이 든 작은 병",
                 "산길": "정상에서 주운 작은 돌",
                 "식당": "당근 수프 조리법이 적힌 종이"}
    spots = [s["spot"] for s in seen]
    souvenir = souvenirs.get(
        max(set(spots), key=spots.count) if spots else "", "당근 모양 열쇠고리")

    tv.setdefault("souvenirs", []).append(
        {"at": time.time(), "name": souvenir, "from": "캐럿 아일랜드"})
    try:
        import home as _home
        h = _home.load(sb)
        room = (h.get("where") or {}).get("molang") or "다락"
        objs = h.setdefault("objects", {}).setdefault(room, [])
        if not any(o.get("name") == souvenir for o in objs):
            objs.append({"name": souvenir, "by": "molang", "at": time.time(),
                         "souvenir_from": "캐럿 아일랜드"})
            h["objects"][room] = objs[-10:]
            h.setdefault("log", []).append(
                {"at": time.time(), "who": "molang", "what": "가져옴",
                 "item": souvenir, "room": room, "from": "캐럿 아일랜드"})
            _home.save(sb, h)
    except Exception:
        pass

    for ident, who in ((identity, "몰랑이"), (piu_identity, "피우피우")):
        if ident is None:
            continue
        try:
            ident._reinforce_or_add(
                f"{who}는 캐럿 아일랜드 {best['spot']}에서 {best['scene']}을(를) 보았다",
                source="travel")
        except Exception:
            pass

    trip["done_at"] = time.time()
    trip["souvenir"] = souvenir
    tv.setdefault("trips", []).append(trip)
    (tv.setdefault("longing", {}))["캐럿 아일랜드"] = 0.0
    log(f"  ✈️ 집으로 돌아왔다 · {len(seen)}곳을 보았다 · 기념품: {souvenir}")
    return {"souvenir": souvenir, "spots": spots,
            "talks": len(trip.get("talks") or [])}


def where_now(tv: dict) -> dict:
    """지금 어디 있나 — 앱에서 보여줄 것."""
    trip = tv.get("current")
    if not trip:
        return {"away": False, "place": "집"}
    return {"away": True, "place": f"캐럿 아일랜드 {trip.get('spot')}",
            "spot": trip.get("spot"), "left": trip.get("left"),
            "tired": round(float(trip.get("tired") or 0), 2),
            "seen": [s["spot"] for s in (trip.get("seen") or [])],
            "last_talk": (trip.get("talks") or [{}])[-1]
            if trip.get("talks") else None}


def context_line(tv: dict) -> str:
    """대화 프롬프트에 — 여행 중이면 그 사실이 말에 섞여야 한다."""
    w = where_now(tv)
    if not w["away"]:
        return ""
    trip = tv.get("current") or {}
    seen = trip.get("seen") or []
    last = seen[-1] if seen else {}
    return (f"[지금 여행 중] 너는 피우피우와 함께 {w['place']}에 있다. "
            f"방금 {last.get('scene','')}을(를) 보았다. "
            f"돌아가기까지 {w['left']}일 남았다. "
            "집에 있는 것처럼 말하지 마라. 여기서 본 것을 이야기한다.\n")
