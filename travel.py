"""
travel.py — 멀리 떠나는 일. 그리고 돌아와서 남는 것.

집 바깥(land)과 무엇이 다른가
  바깥  심심하면 그날 다녀온다. 거리 2~3.5. 걸어서 간다.
  여행  **바로 못 간다.** 가고 싶은 마음이 며칠 쌓여야 하고,
        둘이 함께 가고, 다녀오면 **남는 것이 있다.**

  여행은 다녀온 뒤가 더 긴 일이다. 그래서 이 파일의 절반은 '돌아온 뒤'다.

무엇이 남나
  기념품  그곳의 결을 담은 물건. 집의 한 방에 놓인다.
          (당근 모양 기념품처럼 — 그 섬이 어떤 곳이었는지가 모양에 남는다)
  사진    **이미지가 아니라 그 순간의 기록이다.**
          언제, 어디서, 누가 있었고, 무엇을 보았고, 그때 기분이 어땠나.
          나중에 회상이 이걸 불러내면 "그때 그랬지" 가 된다.
  사실    "캐럿 아일랜드에서 당근밭을 보았다" 처럼 기억으로 굳는다.

언제 떠나나 (조건이 다 차야)
  · 그곳에 대한 마음(longing)이 임계를 넘을 것
  · 기분이 '심심함' 이나 '들뜸' 일 것 — 벅찰 때 떠나지 않는다
  · 마지막 여행 이후 충분히 지났을 것
"""
from __future__ import annotations
import random
import re
import time

LONGING_STEP = 0.18       # 관심이 향할 때마다 쌓이는 그리움
LONGING_NEED = 1.0        # 이만큼 쌓여야 떠날 수 있다
COOLDOWN_H = 72           # 여행 사이 간격
MAX_PHOTOS = 40

# 먼 곳들. 집 바깥(land)보다 훨씬 멀고, 비행기를 타야 한다.
FARAWAY = {
    "캐럿 아일랜드": {
        "dist": 30.0, "by": "비행기",
        "words": ["당근", "섬", "밭", "주황", "바다", "바닷바람", "파도",
                  "등대", "항구", "모래", "여행"],
        "stim": {"밝기": 0.9, "소리": 0.5, "바람": 0.8, "냄새": 0.7},
        "souvenirs": ["당근 모양 열쇠고리", "당근밭 흙이 든 작은 병",
                      "등대가 그려진 엽서", "주황색 조개껍데기"],
        "scenes": ["끝없이 펼쳐진 당근밭", "언덕 위 하얀 등대",
                   "항구에 묶인 작은 배들", "해질 녘 주황빛 바다"],
    },
    "눈의 마을": {
        "dist": 42.0, "by": "비행기",
        "words": ["눈", "겨울", "굴뚝", "모닥불", "고요", "발자국",
                  "따뜻함", "여행"],
        "stim": {"밝기": 0.6, "소리": 0.1, "바람": 0.6, "냄새": 0.3},
        "souvenirs": ["눈 결정 모양 유리", "털실로 뜬 목도리",
                      "나무를 깎아 만든 작은 집"],
        "scenes": ["굴뚝마다 피어오르는 연기", "아무도 안 밟은 눈밭",
                   "창에 서린 성에"],
    },
    "별 보는 사막": {
        "dist": 55.0, "by": "비행기",
        "words": ["별", "모래", "밤하늘", "은하수", "지평선", "고요",
                  "우주", "천문학", "여행"],
        "stim": {"밝기": 0.3, "소리": 0.1, "바람": 0.7, "냄새": 0.2},
        "souvenirs": ["별자리가 새겨진 돌", "유리병에 담은 모래",
                      "밤하늘 지도"],
        "scenes": ["지평선까지 이어진 은하수", "달빛에 빛나는 모래언덕",
                   "떨어지는 별 하나"],
    },
}


def blank() -> dict:
    return {"longing": {}, "trips": [], "photos": [], "souvenirs": []}


def load(sb) -> dict:
    try:
        rows = (sb.table("molang_travel").select("data")
                .eq("id", 1).limit(1).execute().data) or []
        if rows and rows[0].get("data"):
            d = rows[0]["data"]
            for k, v in blank().items():
                d.setdefault(k, v)
            return d
    except Exception:
        pass
    return blank()


def save(sb, tv: dict) -> bool:
    try:
        tv["photos"] = (tv.get("photos") or [])[-MAX_PHOTOS:]
        sb.table("molang_travel").upsert(
            {"id": 1, "data": tv}, on_conflict="id").execute()
        return True
    except Exception:
        return False


# ── 가고 싶은 마음이 쌓인다 ──────────────────────────────────
def _closeness(word: str, keys: list) -> float:
    """
    낱말이 그곳의 결과 얼마나 가까운가. 0~1.
    정확히 같은 낱말만 세면 '바다'가 '바닷바람'과 안 이어져 그리움이
    영영 0 에 머문다. 그래서 임베딩 거리도 함께 본다.
    """
    if word in keys:
        return 1.0
    # 앞 두 글자가 같으면 (바다/바닷바람)
    if any(len(word) >= 2 and len(k) >= 2 and word[:2] == k[:2] for k in keys):
        return 0.7
    try:
        from organism.embedder import hashed_embedding as emb
        v = emb(word, dim=64)
        best = max(float(v @ emb(k, dim=64)) for k in keys)
        return max(0.0, min(1.0, (best - 0.2) / 0.6))
    except Exception:
        return 0.0


def stir_longing(tv: dict, interests: dict, log=print) -> dict:
    """
    관심이 그곳의 결과 겹치면 그리움이 조금 쌓인다.
    바로 떠나지 않는다 — 며칠에 걸쳐 모여야 떠날 수 있다.
    """
    grew = {}
    for name, place in FARAWAY.items():
        keys = place["words"]
        hit = 0.0
        for w, weight in sorted((interests or {}).items(),
                                key=lambda kv: -kv[1])[:20]:
            c = _closeness(w, keys)
            if c > 0.25:
                hit += float(weight) * c
        if hit <= 0:
            continue
        old = float((tv.setdefault("longing", {})).get(name, 0.0))
        add = LONGING_STEP * min(2.0, hit / 2.0)
        tv["longing"][name] = round(min(2.0, old + add), 3)
        grew[name] = tv["longing"][name]
    return grew


def _hours_since_last(tv: dict) -> float:
    trips = tv.get("trips") or []
    if not trips:
        return 9999.0
    return (time.time() - float(trips[-1].get("at", 0))) / 3600


def ready(tv: dict, mood_name: str = "") -> tuple:
    """떠날 수 있나. (갈 곳, 이유) — 못 가면 (None, 까닭)."""
    if _hours_since_last(tv) < COOLDOWN_H:
        return None, "다녀온 지 얼마 안 됨"
    if mood_name == "벅참":
        return None, "지금은 정리할 게 많다"
    long = tv.get("longing") or {}
    cand = [(v, k) for k, v in long.items() if v >= LONGING_NEED]
    if not cand:
        top = max(long.values()) if long else 0.0
        return None, f"아직 그리움이 덜 쌓임({top:.2f}/{LONGING_NEED})"
    cand.sort(reverse=True)
    return cand[0][1], "떠날 때가 됐다"


# ── 떠나고, 보고, 남긴다 ────────────────────────────────────
def go(sb, tv: dict, state, identity=None, piu_identity=None,
       mood_entry=None, rng=None, log=print) -> dict | None:
    """
    여행을 시작한다. 바로 다녀오는 게 아니라 **며칠 머문다.**
    집 → 공항 → 비행기 → 섬. 그 뒤는 island.day() 가 회차마다 돌린다.
    """
    if tv.get("current"):
        return {"went": None, "why": "이미 여행 중"}
    rng = rng or random.Random(time.time_ns())
    where, why = ready(tv, (mood_entry or {}).get("name", ""))
    if not where:
        return {"went": None, "why": why}
    if where != "캐럿 아일랜드":
        # 아직 섬 지도가 있는 곳은 캐럿 아일랜드뿐이다
        where = "캐럿 아일랜드"

    try:
        import island
        trip = island.depart(tv, rng, log=log)
    except Exception as e:
        return {"went": None, "why": f"출발 실패: {str(e)[:60]}"}

    # 공항은 집에서 가장 먼 자리에 있다 — 떠난다는 느낌이 거기서 온다
    log("  🛫 집에서 가장 먼 공항까지 가서 비행기를 탔다")
    return {"went": where, "days": trip["days"], "starting": True}


# ── 돌아온 뒤 ───────────────────────────────────────────────
def recall_photo(tv: dict, cue: str = "", rng=None) -> dict | None:
    """
    사진을 꺼내 본다. 계기가 있으면 그에 맞는 것으로.
    (회상이 이걸 부르면 "그때 그랬지" 가 된다)
    """
    photos = tv.get("photos") or []
    if not photos:
        return None
    rng = rng or random.Random(time.time_ns())
    if cue:
        key = set(re.findall(r"[가-힣A-Za-z]{2,}", cue))
        hit = [p for p in photos
               if key & set(re.findall(r"[가-힣A-Za-z]{2,}",
                                       f"{p.get('where','')} {p.get('scene','')}"))]
        if hit:
            return rng.choice(hit)
    # 오래된 것일수록 더 잘 떠오른다
    old = sorted(photos, key=lambda p: p.get("at", 0))[:max(1, len(photos) // 2)]
    return rng.choice(old or photos)


def photo_line(photo: dict) -> str:
    """사진 한 장을 말로."""
    if not photo:
        return ""
    import datetime
    try:
        when = datetime.datetime.fromtimestamp(photo["at"]).strftime("%m월 %d일")
    except Exception:
        when = "언젠가"
    return (f"{when}에 {photo.get('with')}랑 {photo.get('where')}에 갔을 때 "
            f"찍은 거야. {photo.get('scene')}이(가) 보이지.")


def describe(tv: dict) -> str:
    trips = tv.get("trips") or []
    if not trips:
        long = tv.get("longing") or {}
        if long:
            top = max(long.items(), key=lambda kv: kv[1])
            return f"[여행] 아직 못 가봄 · {top[0]}에 가고 싶음({top[1]:.1f})"
        return ""
    last = trips[-1]
    return (f"[여행] {len(trips)}번 다녀옴 · 마지막은 {last['where']} "
            f"· 사진 {len(tv.get('photos') or [])}장 "
            f"· 기념품 {len(tv.get('souvenirs') or [])}개")
