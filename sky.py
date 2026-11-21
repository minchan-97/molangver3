"""
sky.py — **그 위를 지나가는 것.** 하루와 날씨와 계절.

왜 필요했나
  지형은 안 바뀌어야 맞다. 바다가 오늘 동쪽이면 내일도 동쪽이다.
  그런데 **그 위를 지나가는 것까지 안 바뀌면** 어제의 바다와 오늘의
  바다가 완전히 같아진다. 그러면 '거기 있었다' 가 뜻을 못 갖는다.

  molang_time.py 가 있었지만 그건 프롬프트에 넣을 문장만 만들었다 —
  "지금은 이른 아침이야". **세계 자체는 밤낮을 몰랐다.** 밤에 창가가
  어둡지 않고, 비가 와도 아무도 안 젖었다.

**아무 데도 저장하지 않는다**
  이것이 이 파일의 핵심이다. 날씨는 누가 정하는 것이 아니다.
  그래서 **날짜에서 바로 계산한다.** 같은 날이면 누가 언제 물어도
  같은 답이 나오고, 표도 권한도 저장 실패도 없다.
  되돌려 보기도 쉽다 — 어제를 물으면 어제가 나온다.

무엇을 하나
  자극(밝기·소리·바람·냄새)에 곱한다. 자리는 그대로 두고
  **그 자리가 지금 어떤가**만 바꾼다.

    밤      바깥이 어둡고 조용하다      밝기 ×0.3
    비      어둑하고 빗소리가 난다      밝기 ×0.65 · 소리 ×1.3 · 냄새 ×1.3
    눈      환하고 아주 조용하다        밝기 ×1.15 · 소리 ×0.5
    여름    환하고 냄새가 짙다
    겨울    어둑하고 냄새가 옅다

  **실내는 덜 받는다.** 비가 와도 도서관은 도서관이다.
  그 차이가 '안에 있다' 는 뜻이다.

무엇을 안 하나
  막지 않는다. 비가 와도 나갈 수 있다. 다만 끌리는 자리가 달라진다.
  이 저장소가 내내 지켜 온 규칙이다 — 금지가 아니라 가중치.
"""
from __future__ import annotations
import hashlib
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# 하루 — 바깥의 밝기와 소리가 때마다 다르다
PART = [
    # (끝나는 시각, 이름, 밝기, 소리)
    (5,  "새벽", 0.20, 0.45),
    (9,  "아침", 0.85, 0.90),
    (17, "낮",   1.00, 1.00),
    (20, "저녁", 0.65, 0.85),
    (24, "밤",   0.30, 0.55),
]

SEASON = {  # 월 → (이름, 밝기, 냄새)
    12: ("겨울", 0.85, 0.75), 1: ("겨울", 0.85, 0.75), 2: ("겨울", 0.85, 0.75),
    3: ("봄", 1.0, 1.15), 4: ("봄", 1.0, 1.15), 5: ("봄", 1.0, 1.15),
    6: ("여름", 1.1, 1.2), 7: ("여름", 1.1, 1.2), 8: ("여름", 1.1, 1.2),
    9: ("가을", 0.95, 1.0), 10: ("가을", 0.95, 1.0), 11: ("가을", 0.95, 1.0),
}

# 날씨 — 계절마다 나올 확률이 다르다. 합이 100 이면 된다.
ODDS = {
    "봄":   [("맑음", 45), ("흐림", 25), ("비", 20), ("바람", 10)],
    "여름": [("맑음", 40), ("흐림", 25), ("비", 30), ("바람", 5)],
    "가을": [("맑음", 50), ("흐림", 25), ("비", 15), ("바람", 10)],
    "겨울": [("맑음", 40), ("흐림", 30), ("눈", 20), ("바람", 10)],
}

WEATHER = {  # 이름 → (밝기, 소리, 바람, 냄새, 한 마디)
    "맑음": (1.0, 1.0, 1.0, 1.0, ""),
    "흐림": (0.8, 1.0, 1.0, 0.95, "하늘이 낮다"),
    "비":   (0.65, 1.3, 1.1, 1.3, "비가 온다"),
    "눈":   (1.15, 0.5, 0.9, 0.7, "눈이 온다"),
    "바람": (1.0, 1.15, 1.6, 0.8, "바람이 세다"),
}

# 실내는 하늘을 덜 받는다. 0 이면 아예 안 받고 1 이면 바깥과 같다.
INSIDE = 0.35
INDOOR = {"빵집", "가게", "도서관", "음악방", "사진관",
          "목욕탕", "작업실", "카페"}


def _weather(day: str, season: str) -> str:
    """날짜에서 바로. 같은 날이면 늘 같은 날씨가 나온다."""
    n = int(hashlib.sha1(day.encode()).hexdigest()[:8], 16) % 100
    acc = 0
    for name, odds in ODDS.get(season) or ODDS["봄"]:
        acc += odds
        if n < acc:
            return name
    return "맑음"


def now(when=None) -> dict:
    """지금 하늘. 아무것도 안 읽고 날짜에서 센다."""
    t = when or datetime.now(KST)
    hour = t.hour
    part, p_lit, p_snd = "낮", 1.0, 1.0
    for end, nm, lit, snd in PART:
        if hour < end:
            part, p_lit, p_snd = nm, lit, snd
            break
    season, s_lit, s_smell = SEASON.get(t.month, ("봄", 1.0, 1.0))
    w = _weather(t.strftime("%Y-%m-%d"), season)
    w_lit, w_snd, w_wind, w_smell, w_note = WEATHER[w]
    note = " · ".join(x for x in (f"{part}", w_note) if x)
    return {"part": part, "season": season, "weather": w, "hour": hour,
            "note": note,
            "mul": {"밝기": round(p_lit * s_lit * w_lit, 3),
                    "소리": round(p_snd * w_snd, 3),
                    "바람": round(w_wind, 3),
                    "냄새": round(s_smell * w_smell, 3)}}


def apply(stim: dict, place: str = None, s: dict = None) -> dict:
    """
    자리의 자극에 지금 하늘을 곱한다.
    실내면 덜 받는다 — 비가 와도 도서관은 도서관이다.
    """
    if not stim:
        return {}
    s = s or now()
    inside = bool(place) and (place in INDOOR or str(place).endswith("네"))
    k = INSIDE if inside else 1.0
    out = {}
    for key, v in stim.items():
        m = (s["mul"]).get(key)
        if m is None:
            out[key] = v
            continue
        # 실내면 1.0 쪽으로 당겨서 덜 받게 한다
        mm = 1.0 + (m - 1.0) * k
        out[key] = round(max(0.0, min(1.0, float(v) * mm)), 3)
    return out


def indoor(place: str) -> bool:
    """지붕이 있나. 비를 맞느냐 안 맞느냐가 여기서 갈린다."""
    return bool(place) and (place in INDOOR or str(place).endswith("네"))


def wet(s: dict = None) -> bool:
    """지금 젖는 날인가."""
    return (s or now())["weather"] in ("비", "눈")


def line(s: dict = None) -> str:
    """사람이 읽을 한 줄. 화면과 프롬프트에 쓴다."""
    s = s or now()
    bit = s["weather"] if s["weather"] != "맑음" else "맑음"
    return f"{s['season']} {s['part']} · {bit}"
