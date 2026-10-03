"""
village.py — 몰랑이네 마을.

집(home.py)과 무엇이 다른가
  집   방 여섯 개. 몰랑이와 피우피우만 산다. 방은 미리 정해져 있다.
  마을 집들이 모여 있다. 이웃이 산다. **장소는 함께 쌓은 관심에서 생긴다.**

어떻게 자리가 정해지나
  집과 같은 방식이다 — 결(낱말)을 벡터로 만들어 SOM 격자에 얹는다.
  그래서 결이 비슷한 집이 가까이 놓인다. 슈야·토야네(크림·부엌)는
  몰랑이네 부엌 쪽과 가깝고, 미피네(작고 따뜻한 것)는 또 다른 쪽이다.

  **그리고 한 번 정해진 자리는 바뀌지 않는다.**
  어제 있던 집이 오늘 다른 데 있으면 그건 세계가 아니다.
  (바깥 지형 land.py 가 재배열하지 않는 것과 같은 이유)

함께 만드는 곳
  한 사람의 관심이 아니라 **마을 전체의 관심**이 쌓이면 장소가 생긴다.
  다들 빵 이야기를 하면 빵집이 생긴다. 그 장소는 누구의 것도 아니다.

누가 누구와 마주치나
  자리가 정해지면 거리가 정해지고, 거리가 정해지면 누가 자주 만나는지가
  정해진다. "슈야는 몰랑이와 친하다" 를 적어두지 않아도 그렇게 된다.
"""
from __future__ import annotations
import math
import random
import time

import numpy as np

DIM = 64
GRID = (7, 7)
MEET_DIST = 2.0           # 이만큼 가까우면 마주친다
PLACE_NEED = 4.0          # 마을 관심이 이만큼 쌓이면 새 장소가 생긴다
WALK = 0.35               # 회차마다 움직일 확률

# 처음부터 있는 것 — 집들
HOMES = {
    "몰랑이네":   ["몰랑이", "피우피우", "바다", "창가", "다락"],
    "슈야토야네": ["슈크림", "초코크림", "부엌", "함께", "따뜻함", "빵"],
    "미피네":     ["아기", "작은", "포근함", "낮잠", "장난감"],
}

# 마을 관심이 쌓이면 생길 수 있는 곳
CAN_GROW = {
    "빵집":     ["빵", "크림", "굽기", "밀가루", "냄새"],
    "우물가":   ["물", "두레박", "모여", "이야기", "그늘"],
    "꽃밭":     ["꽃", "씨앗", "흙", "봄", "색"],
    "언덕":     ["언덕", "바람", "멀리", "앉아", "하늘"],
    "가게":     ["가게", "물건", "값", "고르기", "주인"],
    "놀이터":   ["놀이", "그네", "모래", "웃음", "뛰기"],
}


def _vec(text: str):
    from organism.embedder import hashed_embedding
    return hashed_embedding(text or "", dim=DIM)


def blank() -> dict:
    return {"places": {}, "walks": [], "born": []}


def load(sb) -> dict:
    try:
        rows = (sb.table("molang_village").select("data")
                .eq("id", 1).limit(1).execute().data) or []
        if rows and rows[0].get("data"):
            d = rows[0]["data"]
            for k, v in blank().items():
                d.setdefault(k, v)
            return d
    except Exception:
        pass
    return blank()


def save(sb, v: dict) -> bool:
    try:
        v["walks"] = (v.get("walks") or [])[-60:]
        sb.table("molang_village").upsert(
            {"id": 1, "data": v}, on_conflict="id").execute()
        return True
    except Exception:
        return False


# ── 자리 정하기 (한 번만) ───────────────────────────────────
def _free_spot(v: dict, words: list, seed: int = 7) -> tuple:
    """
    결이 비슷한 것끼리 가까이. 이미 찬 자리는 피한다.
    **자리를 정하는 건 생길 때 한 번뿐이다.**
    """
    taken = {tuple(p["at"]) for p in (v.get("places") or {}).values()}
    try:
        from organism.som import SOM
        names = list(HOMES) + list(CAN_GROW)
        X = np.array([_vec(" ".join(HOMES.get(n) or CAN_GROW.get(n, [])))
                      for n in names])
        som = SOM(grid=GRID, dim=DIM, seed=seed)
        som.train(X, iters=1200, seed=seed)
        b = som.bmu_of(_vec(" ".join(words)))
        r, c = b // som.gw, b % som.gw
    except Exception:
        rng = random.Random(hash(" ".join(words)) & 0xffff)
        r, c = rng.randrange(GRID[0]), rng.randrange(GRID[1])

    # 찬 자리면 가까운 빈 자리로 (멀리 날아가지 않게 나선으로)
    if (r, c) in taken:
        for d in range(1, max(GRID)):
            for dr in range(-d, d + 1):
                for dc in range(-d, d + 1):
                    rr, cc = (r + dr) % GRID[0], (c + dc) % GRID[1]
                    if (rr, cc) not in taken:
                        return (rr, cc)
    return (r, c)


def ensure_homes(sb, v: dict, log=print) -> list:
    """집들이 아직 없으면 자리를 정해 둔다. 이미 있으면 건드리지 않는다."""
    made = []
    for name, words in HOMES.items():
        if name in (v.get("places") or {}):
            continue
        at = _free_spot(v, words)
        v.setdefault("places", {})[name] = {
            "kind": "home", "words": words, "at": list(at),
            "born_at": time.time()}
        made.append(name)
    if made:
        log(f"  마을에 집이 놓였다: {', '.join(made)}")
    return made


def distance(v: dict, a: str, b: str) -> float:
    p = v.get("places") or {}
    if a not in p or b not in p:
        return 99.0
    (r1, c1), (r2, c2) = p[a]["at"], p[b]["at"]
    return float(abs(r1 - r2) + abs(c1 - c2))


# ── 함께 쌓은 관심이 장소를 만든다 ──────────────────────────
def maybe_grow(sb, v: dict, interests_list: list, log=print) -> str | None:
    """
    **마을 전체의 관심**을 더해서, 어느 곳의 결과 충분히 겹치면 생긴다.
    한 사람 것이 아니라 모두의 것이다.
    """
    merged = {}
    for d in (interests_list or []):
        for k, w in (d or {}).items():
            merged[k] = merged.get(k, 0.0) + float(w)
    if not merged:
        return None

    best, score = None, 0.0
    for name, words in CAN_GROW.items():
        if name in (v.get("places") or {}):
            continue
        s = sum(merged.get(w, 0.0) for w in words)
        if s > score:
            best, score = name, s
    if not best or score < PLACE_NEED:
        return None

    at = _free_spot(v, CAN_GROW[best])
    v.setdefault("places", {})[best] = {
        "kind": "spot", "words": CAN_GROW[best], "at": list(at),
        "born_at": time.time(), "from_score": round(score, 2)}
    v.setdefault("born", []).append(
        {"at": time.time(), "name": best, "score": round(score, 2)})
    log(f"  🏘️ 마을에 {best}이(가) 생겼다 (모인 관심 {score:.1f})")
    return best


def describe(v: dict) -> str:
    p = v.get("places") or {}
    if not p:
        return ""
    homes = [k for k, x in p.items() if x.get("kind") == "home"]
    spots = [k for k, x in p.items() if x.get("kind") != "home"]
    out = f"[마을] 집 {len(homes)}채"
    if spots:
        out += " · " + ", ".join(spots)
    return out


def layout_rows(v: dict) -> list:
    """앱에서 격자로 그릴 때 쓸 줄."""
    p = v.get("places") or {}
    if not p:
        return []
    rows = sorted({x["at"][0] for x in p.values()})
    cols = sorted({x["at"][1] for x in p.values()})
    grid = {(x["at"][0], x["at"][1]): k for k, x in p.items()}
    return [[grid.get((r, c)) for c in cols] for r in rows]
