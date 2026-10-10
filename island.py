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
RECOVER = 0.06              # 회차마다 저절로 풀리는 몫 (가만히 있어도 회복된다)
VISIT_WEIGHT = 0.16         # 섬에서 보는 것이 관심에 얹히는 정도

# 섬의 장소들. 결(낱말)이 좌표를 만든다.
# **어디를 가든 있는 곳**. 공항으로 들어오고, 호텔에서 자고,
# 지치면 쉴 데가 필요하고, 뭔가 먹고, 기념품을 산다.
COMMON = {
    "공항":  ["비행기", "활주로", "가방", "출발", "도착"],
    "숙소":  ["침대", "창문", "아침", "쉬기", "열쇠"],
    "쉼터":  ["따뜻함", "수건", "쉬기", "느긋함"],
    "식당":  ["요리", "접시", "냄새", "맛", "식탁"],
    "시장":  ["가게", "흥정", "간식", "기념품", "사람들"],
}

# **그곳에만 있는 곳**. 여기가 섬마다 다르다.
# 예전에는 캐럿 아일랜드의 장소만 있어서, 눈의 마을이나 사막에
# 그리움이 2.0까지 차도 갈 데가 없었다 (가도 당근농장이 나왔다).
PLACES = {
    "캐럿 아일랜드": {
        "당근농장": ["당근", "흙", "밭", "수확", "장갑", "체험"],
        "바닷가":   ["파도", "모래", "조개", "바닷바람", "수평선"],
        "등대":     ["등대", "언덕", "불빛", "계단", "전망"],
        "산길":     ["등산", "바위", "나무", "오르막", "정상"],
        "놀이공원": ["회전목마", "관람차", "솜사탕", "음악", "줄"],
    },
    "눈의 마을": {
        "눈밭":     ["눈", "발자국", "하양", "푹신", "조용"],
        "모닥불터": ["장작", "불꽃", "따뜻함", "둘러앉기", "연기"],
        "종탑":     ["종", "소리", "계단", "마을", "내려다보기"],
        "얼음호수": ["얼음", "미끄럼", "투명", "금", "조심"],
        "털실가게": ["털실", "목도리", "뜨개", "색", "포근"],
    },
    "별 보는 사막": {
        "모래언덕": ["모래", "능선", "발자국", "바람", "미끄러짐"],
        "천문대":   ["망원경", "별자리", "관측", "기록", "밤"],
        "오아시스": ["물", "야자수", "그늘", "쉼", "거울"],
        "바위골짜기": ["바위", "협곡", "메아리", "그림자", "붉음"],
        "야영지":   ["천막", "모닥불", "침낭", "밤하늘", "이야기"],
    },
}

# 지금 어느 섬에 있느냐에 따라 장소가 달라진다
SPOTS = {**COMMON, **PLACES["캐럿 아일랜드"]}


def spots_of(where: str) -> dict:
    """그 섬의 장소들 — 어디나 있는 곳 + 그곳에만 있는 곳."""
    return {**COMMON, **(PLACES.get(where) or PLACES["캐럿 아일랜드"])}

# 그곳에서 볼 수 있는 것들. 같은 '식당' 이라도 섬마다 다른 것이 나온다.
SCENES_COMMON = {
    "공항": ["활주로에 내려앉는 비행기", "짐을 찾는 사람들"],
    "숙소": ["창밖으로 보이는 낯선 지붕들", "폭신한 침대"],
    "쉼터": ["김이 피어오르는 자리", "느긋하게 늘어진 오후"],
}
SCENES = {
    "캐럿 아일랜드": {
        "숙소": ["창밖으로 보이는 주황빛 지붕들"],
        "쉼터": ["김이 피어오르는 노천탕", "따뜻한 물에 번지는 빛"],
        "식당": ["당근을 통째로 구운 요리", "식탁에 놓인 수프 두 그릇"],
        "시장": ["당근 모양 물건이 가득한 가판", "간식 냄새가 나는 골목"],
        "당근농장": ["끝없이 펼쳐진 당근밭", "흙 묻은 당근을 뽑는 손",
                    "밭고랑 사이로 부는 바람"],
        "바닷가": ["파도가 밀려왔다 가는 자리", "모래에 남은 발자국 두 쌍",
                  "해질 녘 주황빛 바다"],
        "등대": ["언덕 위 하얀 등대", "등대에서 내려다본 섬 전체"],
        "산길": ["구불구불한 오르막길", "정상에서 본 바다와 밭"],
        "놀이공원": ["천천히 도는 관람차", "솜사탕을 든 작은 그림자"],
    },
    "눈의 마을": {
        "숙소": ["창에 서린 성에", "난로 옆에 걸어둔 목도리"],
        "쉼터": ["무릎에 덮은 담요", "손끝이 녹는 느낌"],
        "식당": ["김이 오르는 뜨거운 국", "창가에 맺힌 물방울"],
        "시장": ["털모자가 쌓인 가판", "입김이 섞이는 골목"],
        "눈밭": ["아무도 안 밟은 눈밭", "소리 없이 내려앉는 눈",
                "발자국 두 쌍이 나란히"],
        "모닥불터": ["탁탁 튀는 장작", "불빛에 물든 얼굴들"],
        "종탑": ["눈 덮인 마을을 내려다본 풍경", "멀리 퍼지는 종소리"],
        "얼음호수": ["투명한 얼음 아래 흐르는 물", "얼음에 간 금"],
        "털실가게": ["색색의 털실 더미", "뜨개바늘이 오가는 소리"],
    },
    "별 보는 사막": {
        "숙소": ["창밖 가득한 별", "밤에도 식지 않는 모래"],
        "쉼터": ["그늘막 아래 부는 마른 바람"],
        "식당": ["모래바람을 막은 천막 식당", "향신료 냄새"],
        "시장": ["별자리 그림이 걸린 가판", "유리병을 파는 노점"],
        "모래언덕": ["달빛에 빛나는 모래언덕", "바람이 새로 그린 능선"],
        "천문대": ["망원경에 비친 토성", "지평선까지 이어진 은하수"],
        "오아시스": ["물에 비친 야자수", "사막 한가운데의 초록"],
        "바위골짜기": ["붉게 물든 절벽", "메아리가 돌아오는 자리"],
        "야영지": ["천막 위로 쏟아지는 별", "떨어지는 별 하나"],
    },
}


def scenes_of(where: str, spot: str) -> list:
    """그 섬 그 자리에서 볼 수 있는 것."""
    s = (SCENES.get(where) or {}).get(spot)
    return s or SCENES_COMMON.get(spot) or [f"{spot}의 낯선 풍경"]


REST = {"숙소", "쉼터"}      # 쉬면 피로가 풀린다
_LAYOUTS = {}                # 섬마다 따로 (장소가 다르므로 지도도 다르다)
_LAYOUT = {"coords": None, "dist": None}


def _vec(text: str):
    from organism.embedder import hashed_embedding
    return hashed_embedding(text or "", dim=DIM)


def layout(seed: int = 13, where: str = "캐럿 아일랜드") -> dict:
    """
    장소를 격자에 얹어 좌표와 거리를 만든다 (집과 같은 방식).
    **섬마다 장소가 다르므로 지도도 따로 둔다.**
    """
    if where in _LAYOUTS:
        return _LAYOUTS[where]
    spots = spots_of(where)
    names = list(spots)
    try:
        from organism.som import SOM
        X = np.array([_vec(" ".join(spots[n])) for n in names])
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
    out = {"coords": pos, "dist": dist}
    _LAYOUTS[where] = out
    _LAYOUT.update(out)          # 옛 코드 호환
    return out


def distance(a: str, b: str, where: str = "캐럿 아일랜드") -> float:
    return layout(where=where)["dist"].get(a, {}).get(b, 2.0)


# ── 떠나기 ──────────────────────────────────────────────────
def depart(tv: dict, rng=None, log=print, where: str = "캐럿 아일랜드") -> dict:
    """공항을 거쳐 그곳으로. 머물 기간을 정한다."""
    rng = rng or random.Random(time.time_ns())
    days = rng.randint(*STAY_DAYS)
    trip = {"where": where, "at": time.time(),
            "spot": "공항", "left": days, "days": days,
            "tired": 0.0, "seen": [], "talks": []}
    tv["current"] = trip
    log(f"  ✈️ 공항에서 비행기를 탔다 — 캐럿 아일랜드, {days}일")
    return trip


def _pick_spot(trip: dict, interests: dict, rng,
               where: str = "캐럿 아일랜드") -> str:
    """
    어디로 갈까. 관심 × 새로움 ÷ 거리, 그리고 지치면 쉬는 곳으로.
    """
    here = trip.get("spot") or "공항"
    seen = [s["spot"] for s in (trip.get("seen") or [])]
    tired = float(trip.get("tired") or 0.0)

    scores = {}
    for name, words in spots_of(where).items():
        if name == here or name == "공항":
            continue
        pull = sum(float((interests or {}).get(w, 0.0)) for w in words)
        # **그곳에만 있는 데를 먼저 간다.**
        # 숙소·쉼터·식당·시장은 어디에나 있다. 그것만 돌면
        # 눈의 마을에 가도 눈밭을 못 보고 돌아온다.
        if name not in COMMON:
            pull += 0.8
        fresh = 1.0 / (1.0 + seen.count(name) * 1.5)
        far = distance(here, name, where=where)
        s = (0.4 + pull) * fresh / (1.0 + far * 0.25)
        if tired > 0.5 and name in REST:
            s *= 3.0 + 4.0 * (tired - 0.5)   # 지칠수록 쉬는 곳이 끌린다
        if tired > 0.8 and name not in REST:
            s *= 0.12                        # 너무 지치면 다른 데는 못 간다
        # 쉬는 곳으로 가는 길은 막지 않는다.
        # 예전에는 지침이 0.8 을 넘으면 '모든' 이동 점수를 깎아서,
        # 쉴 곳으로도 못 가고 한자리(식당)에 갇히는 일이 있었다.
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

    where = trip.get("where") or "캐럿 아일랜드"
    here = trip.get("spot") or "공항"
    tired_now = float(trip.get("tired") or 0.0)

    # 너무 지치면 그 자리에서 쉰다. 쉬는 곳이면 더 잘 풀린다.
    # (움직일수록 지치니, 쉬는 날이 있어야 여행이 이어진다)
    if tired_now > 0.95 and rng.random() < 0.7:
        spot, moved = here, 0.0
        rested = True
    else:
        spot = _pick_spot(trip, state.interests, rng, where=where)
        moved = distance(here, spot, where=where)
        rested = False
    trip["spot"] = spot
    was = float(trip.get("tired") or 0.0)
    # 쉬는 곳이면 많이, 제자리면 조금, 그 밖에도 회차마다 조금씩 풀린다.
    # (가만히 있는데 영영 안 풀리면 한자리에 갇힌다)
    relief = (0.7 if spot in REST else (0.3 if rested else 0.0)) + RECOVER
    trip["tired"] = max(0.0, min(1.2, was + MOVE_COST * moved - relief))

    scene = ("그 자리에 앉아 쉬었다" if rested
             else rng.choice(scenes_of(where, spot)))
    photo = {"at": time.time(), "where": where, "spot": spot,
             "scene": scene, "with": "피우피우", "by": "함께",
             "note": f"{spot}에서 {scene}"}
    tv.setdefault("photos", []).append(photo)
    trip.setdefault("seen", []).append({"spot": spot, "scene": scene})

    # 그곳의 결이 관심에 (집보다, 바깥보다 세게 — 멀리 왔으니까)
    bumped = []
    for w in (spots_of(where).get(spot) or [])[:3]:
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
