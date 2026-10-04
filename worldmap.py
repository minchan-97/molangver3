"""
worldmap.py — 집·바깥·마을을 하나의 지형으로.

지금까지 흩어져 있던 것
  home.py     방 여섯 개 (집 안)
  land.py     바다·숲 같은 바깥
  village.py  이웃들의 집과 함께 만든 곳

  각자 자기 격자를 가지고 있어서, **한 세계로 안 보였다.**
  몰랑이는 자기 방은 아는데 집이 어떻게 생겼는지는 모르고,
  마을이 집에서 어느 쪽인지도 몰랐다.

하나로 묶되 섬은 따로
  캐럿 아일랜드는 비행기를 타고 가는 **먼 곳**이다. 같은 지도에 넣으면
  걸어서 갈 수 있는 것처럼 보인다. 그래서 여행 중에만 따로 보인다.

안 가본 곳은 보이지 않는다
  세 가지 상태가 있다.
    가봄    직접 다녀온 곳. 또렷하게 보인다.
    들음    피우피우나 이웃이 얘기해준 곳. 흐리게 보인다 —
            있다는 건 알지만 가보지 않았다.
    모름    검게 가려진 칸. 뭔가 있다는 것만 보인다.

  그래서 **지도가 함께 넓어진다.** 혼자 다 돌지 않아도,
  누가 다녀와서 말해주면 그만큼 세계가 드러난다.
"""
from __future__ import annotations
import time

# 세계는 두 층이다.
#
#   바깥  집 세 채와 바다·숲이 **한 동네**에 놓인다.
#         몰랑이네에서 미피네가 어느 쪽인지, 바다가 얼마나 먼지가 보인다.
#   집 안  몰랑이네 안의 방 여섯 개. 바깥 지도에 섞으면
#         '부엌'이 '바다' 옆에 있는 것처럼 보여 세계가 뭉개진다.
#
# 둘을 나란히 보여준다 — 하나는 동네, 하나는 그 집 안.
ZONES = {
    "village": {"label": "마을", "origin": (0, 0)},
    "land": {"label": "바깥", "origin": (0, 0)},
    "home": {"label": "집 안", "origin": (0, 0)},
}

ICON = {
    # 집
    "다락": "🪜", "마당": "🌿", "부엌": "🍳", "서재": "📚",
    "창가": "🪟", "작업방": "🛠️",
    # 바깥
    "바다": "🌊", "산": "⛰️", "숲": "🌲", "들판": "🌾", "강": "🏞️",
    # 마을
    "몰랑이네": "🐰", "슈야토야네": "🧁", "미피네": "🍼",
    "빵집": "🥐", "우물가": "🪣", "꽃밭": "🌷", "언덕": "🌄",
    "가게": "🏪", "놀이터": "🎠",
}


def blank() -> dict:
    # 자기 집은 가보고 말고 할 것이 없다 — 거기 산다.
    return {"seen": {"몰랑이네": {"first_at": 0, "n": 1, "by": ["molang"]}},
            "heard": {}}


def load(sb) -> dict:
    try:
        rows = (sb.table("molang_world").select("data")
                .eq("id", 1).limit(1).execute().data) or []
        if rows and rows[0].get("data"):
            d = rows[0]["data"]
            for k, v in blank().items():
                d.setdefault(k, v)
            # 자기 집은 늘 아는 곳이다 (이미 쌓인 것에도 채운다)
            d.setdefault("seen", {}).setdefault(
                "몰랑이네", {"first_at": 0, "n": 1, "by": ["molang"]})
            (d.get("heard") or {}).pop("몰랑이네", None)
            return d
    except Exception:
        pass
    return blank()


def save(sb, w: dict) -> bool:
    try:
        sb.table("molang_world").upsert(
            {"id": 1, "data": w}, on_conflict="id").execute()
        return True
    except Exception:
        return False


# ── 드러나는 것 ─────────────────────────────────────────────
def visit(w: dict, place: str, who: str = "molang") -> bool:
    """직접 다녀왔다. 가장 또렷한 앎이다."""
    if not place:
        return False
    first = place not in (w.get("seen") or {})
    rec = w.setdefault("seen", {}).setdefault(
        place, {"first_at": time.time(), "n": 0, "by": []})
    rec["n"] = int(rec.get("n", 0)) + 1
    rec["last_at"] = time.time()
    if who not in rec.setdefault("by", []):
        rec["by"].append(who)
    # 들어서 알던 곳에 실제로 갔으면, 이제 들은 것이 아니다
    (w.get("heard") or {}).pop(place, None)
    return first


def hear_of(w: dict, place: str, from_who: str = "") -> bool:
    """
    누가 다녀와서 얘기해줬다. 있다는 건 알지만 가보지는 않았다.
    이미 가본 곳이면 아무 일도 없다.
    """
    if not place or place in (w.get("seen") or {}):
        return False
    first = place not in (w.get("heard") or {})
    rec = w.setdefault("heard", {}).setdefault(
        place, {"at": time.time(), "from": []})
    if from_who and from_who not in rec.setdefault("from", []):
        rec["from"].append(from_who)
    return first


def status(w: dict, place: str) -> str:
    """가봄 / 들음 / 모름."""
    if place in (w.get("seen") or {}):
        return "seen"
    if place in (w.get("heard") or {}):
        return "heard"
    return "unknown"


# ── 한 장으로 ───────────────────────────────────────────────
def compose(sb) -> dict:
    """
    **바깥**: 집 세 채와 바다·숲이 한 동네에.
    **집 안**: 몰랑이네 방 여섯 개.
    (섬은 빼고 — 비행기를 타고 가는 먼 곳이다)
    """
    outside, inside, where = {}, {}, {}

    # 누가 어디 있나 — 바깥에 나가 있으면 거기로
    out_now = {}
    try:
        import home
        h = home.load(sb)
        out_now = {k: v.get("place") for k, v in (h.get("outside") or {}).items()}
        for who, room in (h.get("where") or {}).items():
            if room and who not in out_now:
                where.setdefault(room, []).append(who)
        for who, place in out_now.items():
            if place:
                where.setdefault(place, []).append(who)
    except Exception:
        pass

    # 그곳에 사는 핀코 — 알게 된 것만
    pinkos = {}
    try:
        import pinko as _pk
        for place, v in (_pk.load(sb) or {}).items():
            if v.get("known"):
                pinkos[place] = v.get("name")
    except Exception:
        pass
    try:
        import villagers
        for n, x in villagers.load(sb).items():
            if x.get("where"):
                where.setdefault(x["where"], []).append(n)
    except Exception:
        pass

    # ── 바깥: 마을(집들·함께 만든 곳) ──
    try:
        import village
        v = village.load(sb)
        for name, p in (v.get("places") or {}).items():
            r, c = p["at"]
            outside[(r, c)] = {"name": name, "zone": "village",
                               "kind": p.get("kind")}
    except Exception:
        pass

    # ── 바깥: 바다·숲 같은 곳 ──
    # 마을 아래 한 줄에 나란히 둔다. 집들과 섞이지 않게.
    try:
        import land
        l = land.load(sb)
        ys = [k[0] for k in outside] or [0]
        row = max(ys) + 1
        for i, p in enumerate(l.get("places") or []):
            if not p.get("kind"):
                continue
            outside[(row, i)] = {"name": p["kind"], "zone": "land",
                                 "dist": p.get("dist")}
    except Exception:
        pass

    # ── 집 안: 방 여섯 개 ──
    try:
        import home as _hm
        for name, (r, c) in (_hm.layout().get("coords") or {}).items():
            inside[(r, c)] = {"name": name, "zone": "home"}
    except Exception:
        pass

    return {"outside": outside, "inside": inside,
            "where": where, "pinkos": pinkos}


def _to_rows(grid: dict, where: dict, w: dict, pinkos: dict = None) -> list:
    """
    **빈 줄과 빈 칸은 접는다.**
    격자가 7x7 인데 집이 셋뿐이면 화면이 거의 빈 칸이 된다.
    실제로 뭔가 있는 줄과 칸만 모아서, 서로의 위치 관계는 지킨 채 좁힌다.
    """
    if not grid:
        return []
    ys = sorted({k[0] for k in grid})
    xs = sorted({k[1] for k in grid})
    out = []
    for r in ys:
        row = []
        for c in xs:
            cell = grid.get((r, c))
            if not cell:
                row.append(None)
                continue
            st = status(w, cell["name"])
            row.append({
                "name": cell["name"] if st != "unknown" else "",
                "real": cell["name"],
                "zone": cell["zone"],
                "status": st,
                "icon": ICON.get(cell["name"], "📍") if st != "unknown" else "",
                "who": where.get(cell["name"], []),
                "heard_from": (w.get("heard") or {}).get(
                    cell["name"], {}).get("from", []),
                "pinko": (pinkos or {}).get(cell["name"]),
            })
        out.append(row)
    return out


def rows(sb, w: dict) -> dict:
    """
    앱이 그릴 두 장 — 바깥과 집 안.
    모르는 곳은 이름 없이 검은 칸으로.
    """
    comp = compose(sb)
    return {
        "outside": _to_rows(comp["outside"], comp["where"], w,
                            comp.get("pinkos")),
        "inside": _to_rows(comp["inside"], comp["where"], w),
    }


def describe(w: dict) -> str:
    s, h = len(w.get("seen") or {}), len(w.get("heard") or {})
    if not s and not h:
        return ""
    out = f"[세계] 가본 곳 {s}곳"
    if h:
        out += f" · 들어서 아는 곳 {h}곳"
    return out


def context_line(w: dict, here: str = "") -> str:
    """대화 프롬프트에 — 얼마나 알고 있나."""
    seen = list((w.get("seen") or {}))
    heard = list((w.get("heard") or {}))
    if not seen:
        return ""
    line = f"[네가 아는 곳] {', '.join(seen[:8])}"
    if heard:
        line += f"\n[가보진 않았지만 들어서 아는 곳] {', '.join(heard[:5])}"
    return line + "\n"
