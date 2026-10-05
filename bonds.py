"""
bonds.py — 누구와 얼마나 가까운가, 그리고 **함께 기억하는 것**.

왜 필요했나
  어부 핀코가 "몰랑이가 그런 얘기를 한 적이 없다" 고 했다.
  맞는 말이었다. 몰랑이는 피우피우에게 한 말을 기억하는데,
  핀코는 그 자리에 없었으니 모른다.

  그런데 지금까지는 **각자 자기 기억만** 있었다. 둘이 같은 일을
  겪어도 그것이 '우리가 함께한 일' 로 남지 않았다.
  그래서 관계가 쌓이지 않았다.

무엇을 담나
  둘 사이에 하나씩 둔다. 누가 먼저랄 것 없이 **쌍**으로.
    met      몇 번 만났나
    talks    **함께 기억하는 대화** (양쪽이 같은 것을 본다)
    warmth   가까움. 만나면 오르고, 오래 안 보면 옅어진다.
    topics   그 사이에서 자주 나온 이야기

왜 쌍으로 두나
  "몰랑이가 아는 핀코" 와 "핀코가 아는 몰랑이" 를 따로 두면
  서로 다른 것을 기억하게 된다. 그러면 "저번에 그 얘기 했잖아" 가
  성립하지 않는다. 함께한 일은 하나여야 한다.

가까움은 어떻게 변하나
  만나서 이야기하면 오른다 (MEET_GAIN).
  오래 안 보면 옅어진다 — 다만 바닥이 있다. 한 번 가까웠던 사이는
  완전히 남이 되지 않는다.
"""
from __future__ import annotations
import re
import time

MEET_GAIN = 0.08          # 만나서 이야기하면 오르는 폭
FADE_PER_DAY = 0.015      # 안 보면 하루에 이만큼 옅어진다
FLOOR = 0.15              # 한 번 가까웠던 사이의 바닥
MAX_TALKS = 12            # 함께 기억하는 대화 수
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")


def key(a: str, b: str) -> str:
    """누가 먼저랄 것 없이 같은 열쇠."""
    return "|".join(sorted([a, b]))


def blank() -> dict:
    return {}


def load(sb) -> dict:
    try:
        rows = (sb.table("molang_bonds").select("data")
                .eq("id", 1).limit(1).execute().data) or []
        if rows and rows[0].get("data"):
            return rows[0]["data"]
    except Exception:
        pass
    return blank()


def save(sb, bd: dict) -> bool:
    try:
        for v in bd.values():
            v["talks"] = (v.get("talks") or [])[-MAX_TALKS:]
        sb.table("molang_bonds").upsert(
            {"id": 1, "data": bd}, on_conflict="id").execute()
        return True
    except Exception:
        return False


def get(bd: dict, a: str, b: str) -> dict:
    k = key(a, b)
    return bd.setdefault(k, {
        "who": sorted([a, b]), "met": 0, "warmth": 0.3,
        "talks": [], "topics": {}, "last_at": 0})


def remember(bd: dict, a: str, b: str, topic: str,
             said_a: str = "", said_b: str = "", place: str = "") -> dict:
    """
    **함께 기억한다.** 둘 다 같은 것을 본다.
    그래서 나중에 "저번에 그 얘기 했잖아" 가 성립한다.
    """
    v = get(bd, a, b)
    v["met"] = int(v.get("met", 0)) + 1
    v["last_at"] = time.time()
    v["warmth"] = round(min(1.0, float(v.get("warmth", 0.3)) + MEET_GAIN), 3)
    v.setdefault("talks", []).append({
        "at": time.time(), "topic": topic, "place": place,
        a: (said_a or "")[:120], b: (said_b or "")[:120]})
    for w in TOKEN.findall(topic or "")[:3]:
        v.setdefault("topics", {})[w] = int(v["topics"].get(w, 0)) + 1
    return v


def recall(bd: dict, a: str, b: str, cue: str = "", n: int = 2) -> list:
    """둘이 나눈 이야기 중에서. 계기가 있으면 그에 맞는 것으로."""
    v = bd.get(key(a, b))
    if not v or not v.get("talks"):
        return []
    talks = v["talks"]
    if cue:
        k = set(TOKEN.findall(cue))
        hit = [t for t in talks
               if k & set(TOKEN.findall(f"{t.get('topic','')} "
                                        f"{t.get(a,'')} {t.get(b,'')}"))]
        if hit:
            return hit[-n:]
    return talks[-n:]


def fade(bd: dict) -> int:
    """
    오래 안 보면 옅어진다. 다만 바닥 아래로는 안 내려간다 —
    한 번 가까웠던 사이는 완전히 남이 되지 않는다.
    """
    n = 0
    now = time.time()
    for v in bd.values():
        last = float(v.get("last_at") or 0)
        if not last:
            continue
        days = (now - last) / 86400
        if days < 1:
            continue
        w = float(v.get("warmth", 0.3))
        new = max(FLOOR, round(w - FADE_PER_DAY * days, 3))
        if new < w:
            v["warmth"] = new
            n += 1
    return n


def closest(bd: dict, who: str, n: int = 3) -> list:
    """누구와 가장 가까운가."""
    out = []
    for v in bd.values():
        if who in (v.get("who") or []):
            other = [x for x in v["who"] if x != who]
            if other:
                out.append((other[0], float(v.get("warmth", 0)),
                            int(v.get("met", 0))))
    return sorted(out, key=lambda x: -x[1])[:n]


def context_line(bd: dict, a: str, b: str, cue: str = "") -> str:
    """
    대화 프롬프트에 — **이 상대와 전에 무슨 얘기를 했나.**
    이것이 없으면 매번 초면이 된다.
    """
    v = bd.get(key(a, b))
    if not v:
        return ""
    talks = recall(bd, a, b, cue)
    line = f"[{b}와의 사이] {v.get('met', 0)}번 만남"
    tops = sorted((v.get("topics") or {}).items(), key=lambda x: -x[1])[:3]
    if tops:
        line += " · 자주 나온 얘기: " + ", ".join(t for t, _ in tops)
    if talks:
        line += "\n[전에 나눈 말]\n" + "\n".join(
            f"  {t.get('topic','')}: {t.get(b,'')[:50]}" for t in talks)
    return line + "\n(전에 한 얘기를 처음 듣는 척하지 마라.)\n"


def describe(bd: dict, who: str = "몰랑이") -> str:
    near = closest(bd, who)
    if not near:
        return ""
    return "[사이] " + " · ".join(
        f"{n}({w:.2f}, {m}번)" for n, w, m in near)
