"""
hearsay.py — **들은 말은 바로 믿지 않는다.** 그리고 **어디서 왔는지 남긴다.**

왜 필요했나
  conscience 는 **검색으로 들어온 것**만 본다. 그런데 핀코와 이웃이
  한 말은 `_reinforce_or_add` 로 **곧장 사실이 된다.** 거기엔 가드가 없다.

    "오늘 몰랑이의 생일이었대!"        → 사실이 될 뻔했다
    "어부 핀코는 그게 뭔지 몰라."       → 사실로 저장됐다

  사회가 생기면서 **가드 없는 입구가 넓어졌다.** 전에는 둘이었는데
  이제 일곱이다. Vending-Bench 가 보여준 것은 작은 오해가 자기
  기록을 거치며 커지는 고리였고, 여기도 그 길이 열려 있다.

  그리고 순환이 있다. 몰랑이가 한 말이 피우피우를 거쳐 돌아오면
  **같은 근원인데 두 번 센 것**이 된다. 독립된 확인이 아닌데
  확신만 오른다. 지금 vitals 는 그걸 글 겹침으로 짐작할 뿐이다.

무엇을 하나
  들어올 때   믿을 만한지 따져서 낮은 신뢰로 넣거나, 안 넣는다
  남길 때     **누구를 거쳐 왔는지**(chain) 를 함께 적는다
  셀 때       근원이 같은 것은 두 번 세지 않는다

무엇을 안 막나
  사회에서 온 말을 **전부** 막지는 않는다. 그러면 이웃이 있는 뜻이
  없다. 다만 **지어낸 티가 나는 것**과 **돌아온 것**을 거른다.
"""
from __future__ import annotations
import re

TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")

# 사회에서 온 말은 처음부터 낮게 시작한다.
# 사용자 말(0.6)보다 낮고, 쓰이면 오른다.
HEARSAY_STRENGTH = 0.35

# **모른다는 말은 앎이 아니다.**
# "어부 핀코는 그게 뭔지 몰라" 가 사실 목록을 차지할 이유가 없다.
_EMPTY = re.compile(
    r"(몰라|모르겠|모른다|잘 모|관심 없|상관없|필요 없|필요하지 않|"
    r"그런 얘기|한 적 없|아닌 것 같|글쎄)")

# 지어낸 티가 나는 것 — 근거 없이 구체적인 주장
_MADE_UP = re.compile(
    r"(\d{1,4}[년월일시]|생일|기념일|태어난|결혼|졸업|출시|발매|"
    r"살이|번째로)")


def is_empty(text: str) -> bool:
    """내용이 없는 말인가 (모른다·상관없다)."""
    return bool(_EMPTY.search(text or ""))


def looks_made_up(text: str, known: list = None) -> bool:
    """
    근거 없이 구체적인가.
    아는 것 안에 그 구체적인 대목이 없으면 지어낸 것으로 본다.
    """
    hits = _MADE_UP.findall(text or "")
    if not hits:
        return False
    base = " ".join(known or [])
    return not any(h in base for h in hits)


def judge(text: str, speaker: str, known: list = None) -> dict:
    """
    이 말을 사실로 받아들일까.

    돌려주는 것:
      take      받아들일까
      strength  얼마나 믿을까
      why       왜 그렇게 정했나 (기록에 남는다)
    """
    t = (text or "").strip()
    if len(t) < 6:
        return {"take": False, "why": "너무 짧다"}
    if is_empty(t):
        return {"take": False, "why": "모른다는 말은 앎이 아니다"}
    if looks_made_up(t, known):
        return {"take": False, "why": "근거 없이 구체적이다"}
    return {"take": True, "strength": HEARSAY_STRENGTH,
            "why": f"{speaker}에게 들었다"}


# ── 전달 경로 ────────────────────────────────────────────
def chain_of(text: str, speaker: str, prior: list = None) -> list:
    """
    **누구를 거쳐 왔나.**

    몰랑이 → 피우피우 → 슈야 로 돌면 ["molang","piupiu","shuya"] 가 된다.
    이것이 있으면 "같은 근원인가" 를 글 겹침이 아니라 **기록으로** 안다.
    """
    out = list(prior or [])
    if speaker and (not out or out[-1] != speaker):
        out.append(speaker)
    return out[-6:]


def is_echo(chain: list, me: str = "molang") -> bool:
    """
    **돌아온 말인가.**

    내가 한 말이 남을 거쳐 나에게 돌아왔다면, 그것은 새로 안 것이
    아니라 메아리다. 독립된 확인이 아니므로 확신을 올려선 안 된다.
    """
    return bool(chain) and me in chain[:-1]


def same_origin(a: list, b: list) -> bool:
    """두 말이 같은 데서 나왔나 — 첫 입이 같은가."""
    return bool(a) and bool(b) and a[0] == b[0]


def note(chain: list) -> str:
    """사실에 붙일 한 줄. 사람이 읽을 수 있게."""
    if not chain:
        return ""
    if len(chain) == 1:
        return f"({chain[0]}에게 직접)"
    return "(" + " → ".join(chain) + ")"
