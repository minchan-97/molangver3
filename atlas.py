"""
atlas.py — **한 좌표계로 묶은 지도.**

왜 필요했나
  지금까지 있던 것은 지도가 아니라 **자리 번호**였다.

    마을   SOM 격자 좌표 (3, 5) — 결이 비슷한 것끼리 가까이
    바깥   거리 2.0 — **좌표가 없다**
    집 안  또 다른 격자

  셋이 서로 모르는 좌표계라 **한 화면에 그릴 수가 없었다.**
  그리고 빵집에서 음악방까지 어떻게 가는지도 없이 순간이동이었다.

무엇을 하나
  마을 격자를 가운데 두고, 바깥을 **거리에 따라 바깥 고리**에 놓는다.
  가까운 것은 안쪽, 먼 것은 바깥쪽. 그러면 '멀어서 안 간다' 가
  눈으로도 말이 된다.

        [밤하늘터]  [언덕마루]
   [숲]    ┌─────────┐    [꽃길]
          │  마을    │
   [바다]  └─────────┘   [메아리벽]

한 번 정하면 안 바꾼다
  **이것이 가장 중요하다.** 새 지형이 생길 때마다 전체가 다시
  배치되면 매번 다른 세계가 된다. 어제 본 자리에 오늘도 있어야
  지도다. 그래서 한 번 정한 자리는 저장해 두고, 새로 생긴 것만
  빈자리에 붙인다.
"""
from __future__ import annotations
import math
import time

W = 21                  # 전체 격자 (바깥 고리까지)
H = 15
# 마을이 놓일 가운데 칸 (x, y, w, h).
# 좁게 잡아야 **마을처럼 모여 보인다.** 넓으면 흩어져서
# 집이 어디고 가게가 어딘지 눈에 안 들어온다.
VILLAGE_BOX = (7, 5, 7, 5)


def blank() -> dict:
    return {"spots": {}, "size": [W, H], "built_at": time.time()}


def load(sb) -> dict:
    try:
        rows = (sb.table("molang_atlas").select("data")
                .eq("id", 1).limit(1).execute().data) or []
        if rows and rows[0].get("data"):
            d = rows[0]["data"]
            d.setdefault("spots", {})
            d.setdefault("size", [W, H])
            return d
    except Exception:
        pass
    return blank()


def save(sb, a: dict) -> bool:
    try:
        sb.table("molang_atlas").upsert(
            {"id": 1, "data": a}, on_conflict="id").execute()
        return True
    except Exception:
        return False


def _free(a: dict, want: tuple, box: tuple = None) -> list:
    """
    빈 자리를 찾는다. 바라는 자리가 찼으면 가까운 데로 밀린다.
    **이미 놓인 것은 절대 밀어내지 않는다.**
    """
    taken = {tuple(v["xy"]) for v in (a.get("spots") or {}).values()}
    x0, y0 = want
    for r in range(0, max(W, H)):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                x, y = x0 + dx, y0 + dy
                if box:
                    bx, by, bw, bh = box
                    if not (bx <= x < bx + bw and by <= y < by + bh):
                        continue
                if not (0 <= x < W and 0 <= y < H):
                    continue
                if (x, y) not in taken:
                    return [x, y]
    return [x0 % W, y0 % H]


def place_village(a: dict, vil: dict) -> int:
    """
    마을 자리를 가운데 칸에 놓는다.
    SOM 좌표(at)의 **차례를 지켜서** 옮긴다 — 가까운 것끼리 가깝게.
    """
    bx, by, bw, bh = VILLAGE_BOX
    n = 0
    for name, p in sorted((vil.get("places") or {}).items(),
                          key=lambda kv: tuple(kv[1].get("at") or (0, 0))):
        if name in (a.get("spots") or {}):
            continue
        # SOM 좌표의 **차례만** 가져온다 (값 자체는 격자가 달라 의미 없다).
        # 그래야 결이 비슷한 것끼리 가까이 남는다.
        at = p.get("at") or (0, 0)
        want = (bx + int(at[1]) % bw, by + int(at[0]) % bh)
        a.setdefault("spots", {})[name] = {
            "xy": _free(a, want, VILLAGE_BOX), "zone": "village",
            "icon": _icon(name, "village"), "born": p.get("born_at")}
        n += 1
    return n


def place_land(a: dict, land: dict) -> int:
    """
    바깥을 **거리에 따라 바깥 고리**에 놓는다.
    가까운 것은 마을 가까이, 먼 것은 멀리. 방향은 이름으로 고르되
    한 번 정하면 안 바뀐다.
    """
    bx, by, bw, bh = VILLAGE_BOX
    cx, cy = bx + bw / 2, by + bh / 2
    n = 0
    places = [p for p in (land.get("places") or []) if p.get("kind")]
    for i, p in enumerate(places):
        name = p["kind"]
        if name in (a.get("spots") or {}):
            continue
        # 거리가 멀수록 바깥으로. 방향은 이름의 해시로 (늘 같다)
        dist = float(p.get("dist") or 3.0)
        ring = min(max(bw, bh) / 2 + 1.5 + dist * 0.55,
                   min(W, H) / 2 - 1)
        ang = (sum(ord(c) for c in name) % 360) * math.pi / 180
        want = (int(cx + ring * math.cos(ang)),
                int(cy + ring * math.sin(ang) * 0.75))
        a.setdefault("spots", {})[name] = {
            "xy": _free(a, want), "zone": "land",
            "icon": _icon(name, "land"), "dist": dist}
        n += 1
    return n


_ICON = {
    # 집
    "몰랑이네": "🏠", "슈야토야네": "🧁", "미피네": "🍼",
    # 마을
    "빵집": "🥐", "우물가": "⛲", "꽃밭": "🌷", "언덕": "🌾",
    "가게": "🏪", "놀이터": "🛝", "도서관": "📚", "음악방": "🎵",
    "사진관": "📷", "별보는터": "🔭", "목욕탕": "♨️",
    "작업실": "🔧", "카페": "☕", "텃밭": "🥕",
    # 바깥
    "바다": "🌊", "숲": "🌲", "산": "⛰️", "들판": "🌾", "물가": "🏞️",
    "언덕마루": "🌄", "밤하늘터": "✨", "꽃길": "🌸", "폐허": "🏚️",
    "안개골": "🌫️", "메아리벽": "🔊", "마을": "🏘️",
}


def _icon(name: str, zone: str) -> str:
    return _ICON.get(name, "🏡" if zone == "village" else "📍")


def rebuild(sb, log=print) -> dict:
    """
    지도를 세운다. **이미 놓인 것은 건드리지 않는다.**
    새로 생긴 곳만 빈자리에 붙인다.
    """
    a = load(sb)
    try:
        import village as V
        nv = place_village(a, V.load(sb))
    except Exception:
        nv = 0
    try:
        import land as L
        nl = place_land(a, L.load(sb))
    except Exception:
        nl = 0
    if nv or nl:
        save(sb, a)
        if log:
            log(f"  🗺️ 지도에 새 자리 {nv + nl}곳 "
                f"(마을 {nv} · 바깥 {nl})")
    return {"spots": len(a.get("spots") or {}), "new": nv + nl}


def distance(a: dict, p: str, q: str) -> float:
    """두 자리 사이의 **진짜 거리**. 한 좌표계이므로 비교가 된다."""
    s = a.get("spots") or {}
    if p not in s or q not in s:
        return 9.9
    (x1, y1), (x2, y2) = s[p]["xy"], s[q]["xy"]
    return round(math.hypot(x2 - x1, y2 - y1), 2)


def view(sb) -> dict:
    """화면이 그릴 한 장. 자리 + 지금 누가 어디 있나."""
    a = load(sb)
    out = {"size": a.get("size") or [W, H],
           "spots": a.get("spots") or {}, "who": {}}
    try:
        import villagers as VP
        for n, v in (VP.load(sb) or {}).items():
            out["who"][n] = {"at": v.get("where"),
                             "feel": (v.get("feel") or {})}
    except Exception:
        pass
    try:
        import home as HM
        h = HM.load(sb)
        w = (h.get("where") or {})
        for who, room in w.items():
            out["who"][{"molang": "몰랑이",
                        "piupiu": "피우피우"}.get(who, who)] = {
                "at": "몰랑이네", "room": room}
    except Exception:
        pass
    try:
        import pinko as PK
        out["pinko"] = {k: v.get("name")
                        for k, v in (PK.load(sb) or {}).items()
                        if isinstance(v, dict) and v.get("known")}
    except Exception:
        pass
    return out


# ── 발자국 ───────────────────────────────────────────────
def step(sb, who: dict, home: dict = None) -> int:
    """
    **이 회차에 누가 어디 있었나**를 한 줄씩 적는다.

    마주침만으로는 재생이 안 된다. 만난 순간에만 점이 찍히고
    그 사이가 비기 때문이다. 하루 96줄이면 하루치를 되돌려 볼 수 있다.
    """
    rows, now = [], time.time()
    for n, v in (who or {}).items():
        rows.append({"at": now, "who": n, "spot": v.get("where"),
                     "feel": _feel_name(v)})
    for key, name in (("molang", "몰랑이"), ("piupiu", "피우피우")):
        room = ((home or {}).get("where") or {}).get(key)
        if room:
            rows.append({"at": now, "who": name,
                         "spot": "몰랑이네", "room": room})
    if not rows:
        return 0
    try:
        sb.table("molang_steps").insert(rows).execute()
        return len(rows)
    except Exception:
        return 0


def _feel_name(v: dict) -> str:
    try:
        import feelings as F
        return F.name(F.of(v))
    except Exception:
        return ""


def replay(sb, hours: int = 24) -> dict:
    """하루치 발자국. 화면이 이걸로 되감는다."""
    try:
        since = time.time() - hours * 3600
        rows = (sb.table("molang_steps")
                .select("at,who,spot,room,feel")
                .gte("at", since).order("at").limit(3000)
                .execute().data) or []
    except Exception:
        return {"frames": []}

    # 같은 시각끼리 묶는다 (한 회차가 한 장면)
    frames, cur, t0 = [], {}, None
    for r in rows:
        t = round(float(r.get("at") or 0) / 60)      # 분 단위로 묶기
        if t0 is None:
            t0 = t
        if t != t0:
            if cur:
                frames.append({"at": t0 * 60, "who": cur})
            cur, t0 = {}, t
        cur[r["who"]] = {"spot": r.get("spot"), "room": r.get("room"),
                         "feel": r.get("feel")}
    if cur:
        frames.append({"at": (t0 or 0) * 60, "who": cur})
    return {"frames": frames, "n": len(frames)}
