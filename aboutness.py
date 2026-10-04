"""
aboutness.py — 이 말은 **누구에 대한 것인가**.

왜 필요했나
  사실 250건 중 몰랑이 자기 사실이 **4건** 뿐이었다. 나머지는 거의
  사용자 이야기인데, 그것들이 몰랑이의 기억 저장소에 함께 담겨
  프롬프트로 들어갔다. 그래서 "부산 일광에 살고 있다" 같은 말이
  자기 사실처럼 읽혔다.

  owner 와 about 은 다르다.
    owner  이 기억이 **누구의 저장소**에 있는가 (늘 molang)
    about  이 말이 **누구에 대한 것**인가 (user / molang / piupiu / …)
  둘을 섞으면 정체성이 무너진다. 그래서 열을 따로 둔다.

어떻게 가르나 — 낱말이 아니라 **화자와 출처**로
  "나는 당근을 좋아해" 는 몰랑이 말일 수도, 사용자 말일 수도 있다.
  문장만 보면 못 가른다. 그래서 두 가지를 쓴다.

  1) 겪음의 출처   여행·집·꿈처럼 **몰랑이 몸에서 일어난 일**은
                   주어를 묻지 않아도 몰랑이 것이다.
  2) 맥락의 인칭   화자를 알면 인칭이 풀린다.
                   사용자 발화의 '나' 는 사용자, '너' 는 몰랑이.
                   몰랑이 발화에서는 뒤집힌다.

  그래도 안 갈리면 unknown 으로 두고, 나중에 맥락이 쌓여 정해지게 한다.
  (지우지 않는다 — 모른다는 것도 상태다)
"""
from __future__ import annotations
import re

# 이름 → 누구
NAMES = {
    "사용자": "user", "찬기": "user", "민찬기": "user",
    "몰랑이": "molang",
    "피우피우": "piupiu",
    "슈야": "shuya", "토야": "toya", "미피": "mipi",
}

# 출처 → 누구에 대한 것인가 (주어를 묻지 않아도 되는 것)
BY_SOURCE = {
    "travel": "molang",      # 여행에서 겪은 일
    "home": "molang",        # 집에서 일어난 일
    "dream": "molang",       # 꿈
    "land": "molang",        # 바깥 나들이
    "peer": "piupiu",        # 또래 대화에서 알게 된 것
    "village": None,         # 마을 — 누가 말했는지에 따라 다르다
}

SUBJ = re.compile(r"^\s*([가-힣A-Za-z]{2,6})(?:은|는|이|가|도|의|씨|야)\s")
# 사람에게만 붙는 서술 (이게 없으면 사물·개념 설명으로 본다)
PERSONAL = re.compile(
    r"(좋아|싫어|생각한|느낀|산다|살고|만든|먹는|듣는|간다|했다|한다고|"
    r"무서워|궁금|관심|바란|원한|기억한|보았|다녀)")
IMPERSONAL = re.compile(r"(이다\.?$|이었다|로 알려|라고 한다|에 속한다|로 불린)")

# 화자의 '나/너' 가 가리키는 것
FIRST = re.compile(r"(^|\s)(나는|내가|나도|난 |내 )")
SECOND = re.compile(r"(^|\s)(너는|네가|너도|넌 |네 )")


def judge(text: str, source: str = "", speaker: str = "") -> tuple:
    """
    (누구에 대한 말인가, 왜 그렇게 봤나)

    speaker 는 **누가 말했나** — 'user' / 'molang' / 'piupiu' / 마을 이름.
    비어 있으면 source 로 짐작한다.
    """
    t = (text or "").strip()
    if not t:
        return "unknown", "빈 말"

    # 1) 주어에 이름이 있으면 그대로
    m = SUBJ.match(t)
    if m and m.group(1) in NAMES:
        return NAMES[m.group(1)], "주어"

    # 2) 사람 이름이 아닌 것이 주어거나, 사람 서술이 없으면 → 세상 사실
    #    ("솜사탕은 달콤하고 부드럽다", "여리고는 오래된 도시이다")
    if m and not PERSONAL.search(t):
        return "world", "사물 설명"
    if IMPERSONAL.search(t) and not PERSONAL.search(t):
        return "world", "세상"

    # 3) 겪음의 출처 — 몰랑이 몸에서 일어난 일은 주어를 안 묻는다
    if source in BY_SOURCE and BY_SOURCE[source]:
        return BY_SOURCE[source], "겪음"

    # 4) 맥락의 인칭 — 화자를 알면 '나/너' 가 풀린다
    sp = speaker or ("user" if source == "user" else "")
    if sp:
        if SECOND.search(t):
            return ("molang" if sp != "molang" else "user"), "인칭(너)"
        if FIRST.search(t):
            return sp, "인칭(나)"
        # 주어 없이 말하면 대개 자기 얘기다
        return sp, "주어 생략"

    return "unknown", "모호"


def stamp(fact: dict, speaker: str = "") -> dict:
    """사실 하나에 about 을 붙인다."""
    a, why = judge(fact.get("text", ""), fact.get("source", ""), speaker)
    fact["about"] = a
    fact["about_why"] = why
    return fact


def split(facts: list) -> dict:
    """모아서 나눠 본다 — 지금 무엇이 얼마나 있는지."""
    out = {}
    for f in facts or []:
        a, _ = judge(f.get("text", ""), f.get("source", ""),
                     f.get("speaker", ""))
        out.setdefault(a, []).append(f)
    return out


def mine(facts: list) -> list:
    """몰랑이 자신에 대한 것만."""
    return [f for f in (facts or [])
            if judge(f.get("text", ""), f.get("source", ""),
                     f.get("speaker", ""))[0] == "molang"]


def describe(facts: list) -> str:
    s = split(facts)
    order = ["user", "piupiu", "molang", "shuya", "toya", "mipi",
             "world", "unknown"]
    KO = {"user": "사용자", "molang": "자기", "piupiu": "피우피우",
          "shuya": "슈야", "toya": "토야", "mipi": "미피",
          "world": "세상", "unknown": "모름"}
    return " · ".join(f"{KO.get(k, k)} {len(s[k])}"
                      for k in order if s.get(k))

