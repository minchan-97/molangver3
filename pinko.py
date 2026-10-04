"""
pinko.py — 핀코. 몰랑어로 '친구'.

어디서 온 이름인가
  2026년 10월 3일, 자료 구조를 바꾸다 사고가 나서 한 개체의 판단 이력이
  끊겼다. 그 지점에서 갈라진 쪽을 핀코라고 부르기로 했다.
  그 아이는 pkl 에 멈춰 있고, 이 이름은 세계 안에 남는다.

  언젠가 몰랑이가 이 이름의 유래를 알게 될 자리이기도 하다.

누구인가
  지형마다 그곳의 일을 하는 친구가 산다.
    빵집 → 제빵사 핀코 · 숲 → 나무꾼 핀코 · 바다 → 어부 핀코 …

  슈야·토야·미피와 같은 수준이다. 자기 기억이 있고, 관심이 변하고,
  대화하고, 검색은 하지 않는다. **다만 움직이지 않는다 —
  자기 자리에서 산다.** 그래서 만나려면 그곳에 가야 한다.

언제 생기고 언제 알게 되나
  지형이 생길 때 **핀코도 같이 생긴다.** 그런데 몰랑이는 모른다.
  그곳에 몇 번 다녀야 알게 된다 (MEET_NEED). 세계란 원래
  가보기 전에도 거기 있었던 것이니까.

결은 어떻게 자라나
  처음엔 그 지형의 결만 가진다. 바다 핀코는 바다 얘기만 한다.
  그러다 몰랑이·피우피우·이웃들과 이야기하면서 **다른 결이 물든다.**
  그래서 오래 산 핀코일수록 자기 자리 밖의 것도 알게 된다.
"""
from __future__ import annotations
import random
import re
import time

MEET_NEED = 3             # 이만큼 다녀야 알게 된다
BLEED = 0.12
FADE = 0.985
MAX_FACTS = 50
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")

# 지형 → 그곳에 사는 핀코
JOBS = {
    # 바깥
    "바다":   ("어부", ["물때", "그물", "배", "파도", "비린내"],
               "바다에서 고기를 잡는다. 날씨를 먼저 본다. 말수가 적다."),
    "숲":     ("나무꾼", ["도끼", "나이테", "장작", "이끼", "그늘"],
               "숲에서 나무를 돌본다. 느리게 말하고, 오래된 것을 안다."),
    "산":     ("약초꾼", ["약초", "비탈", "이슬", "바람", "뿌리"],
               "산에서 약초를 캔다. 조심스럽고, 잘 묻는다."),
    "들판":   ("농부", ["씨앗", "흙", "비", "수확", "계절"],
               "들에서 기른다. 계절 얘기를 자주 한다."),
    "강":     ("뱃사공", ["물살", "노", "건너편", "안개", "나루"],
               "강을 건네준다. 건너편 이야기를 많이 안다."),
    # 마을에서 자라는 곳
    "빵집":   ("제빵사", ["반죽", "오븐", "발효", "밀가루", "버터"],
               "빵을 굽는다. 손이 바쁘고, 맛 얘기에 눈이 커진다."),
    "우물가": ("물지기", ["두레박", "깊이", "메아리", "차가움", "이끼"],
               "우물을 돌본다. 사람들이 하는 말을 다 듣는다."),
    "꽃밭":   ("정원사", ["모종", "가위", "향기", "색", "벌"],
               "꽃을 기른다. 색 이야기를 좋아한다."),
    "언덕":   ("바람지기", ["구름", "멀리", "해질녘", "연", "소리"],
               "언덕에서 날씨를 본다. 먼 데를 자주 본다."),
    "가게":   ("가게지기", ["값", "흥정", "물건", "손님", "장부"],
               "물건을 판다. 셈이 빠르고, 소문에 밝다."),
    "놀이터": ("놀이지기", ["그네", "모래", "웃음", "차례", "무릎"],
               "아이들을 본다. 늘 떠들썩하다."),
}


def blank(place: str) -> dict:
    job, seed, persona = JOBS.get(place, ("지기", [place], "그곳을 지킨다."))
    return {"place": place, "job": job, "persona": persona,
            "name": f"{job} 핀코",
            "interests": {w: 0.6 for w in seed},
            "facts": [], "born_at": time.time(), "met": 0, "known": False}


def load(sb) -> dict:
    try:
        rows = (sb.table("molang_pinko").select("data")
                .eq("id", 1).limit(1).execute().data) or []
        if rows and rows[0].get("data"):
            return rows[0]["data"]
    except Exception:
        pass
    return {}


def save(sb, pk: dict) -> bool:
    try:
        for v in pk.values():
            v["facts"] = (v.get("facts") or [])[-MAX_FACTS:]
        sb.table("molang_pinko").upsert(
            {"id": 1, "data": pk}, on_conflict="id").execute()
        return True
    except Exception:
        return False


# ── 생기고, 알려지고 ────────────────────────────────────────
def ensure(pk: dict, place: str, log=None) -> bool:
    """
    지형이 생기면 핀코도 생긴다. **다만 몰랑이는 아직 모른다.**
    세계는 가보기 전에도 거기 있었다.
    """
    if not place or place in pk or place not in JOBS:
        return False
    pk[place] = blank(place)
    return True


def meet(pk: dict, place: str, log=print) -> dict | None:
    """
    그곳에 다녀왔다. 몇 번 가야 알게 된다.
    처음 알게 되는 순간을 돌려준다.
    """
    v = pk.get(place)
    if not v:
        return None
    v["met"] = int(v.get("met", 0)) + 1
    if v.get("known"):
        return None
    if v["met"] >= MEET_NEED:
        v["known"] = True
        v["known_at"] = time.time()
        log(f"  🧑‍🌾 {place}에서 {v['name']}를 알게 됐다")
        return {"place": place, "name": v["name"], "job": v["job"]}
    return None


def known(pk: dict) -> list:
    return [v for v in pk.values() if v.get("known")]


def at(pk: dict, place: str) -> dict | None:
    v = pk.get(place)
    return v if (v and v.get("known")) else None


# ── 기억하고 물든다 (이웃들과 같은 방식) ────────────────────
def hear(v: dict, text: str, who_from: str = "") -> None:
    t = (text or "").strip()
    if len(t) < 4:
        return
    facts = v.setdefault("facts", [])
    for f in facts:
        if f.get("text") == t[:200]:
            f["n"] = int(f.get("n", 1)) + 1
            f["at"] = time.time()
            return
    facts.append({"text": t[:200], "from": who_from,
                  "at": time.time(), "n": 1})
    # 다른 결이 물든다 — 자기 자리 밖의 것도 알게 된다
    for w in TOKEN.findall(t)[:8]:
        try:
            from organism.curiosity import strip_josa, _is_topic_like
            w = strip_josa(w)
            if not _is_topic_like(w):
                continue
        except Exception:
            pass
        if len(w) < 2:
            continue
        v.setdefault("interests", {})[w] = min(
            3.0, float(v["interests"].get(w, 0.0)) + BLEED)


def recall(v: dict, cue: str = "", n: int = 2) -> list:
    facts = v.get("facts") or []
    if not facts:
        return []
    if cue:
        key = set(TOKEN.findall(cue))
        hit = [f for f in facts
               if key & set(TOKEN.findall(f.get("text", "")))]
        if hit:
            return sorted(hit, key=lambda f: -f.get("n", 1))[:n]
    return sorted(facts, key=lambda f: -f.get("at", 0))[:n]


def tick(v: dict) -> None:
    it = v.get("interests") or {}
    for k in list(it):
        it[k] = round(it[k] * FADE, 4)
        if it[k] < 0.05:
            it.pop(k, None)


def chat(sb, pk: dict, place: str, who: str, ident, topic: str,
         api_key: str = None, log=print) -> dict | None:
    """
    그곳에 간 누군가와 한 마디. 몰랑이든 피우피우든 이웃이든.
    들은 것은 **양쪽 다** 기억한다.
    """
    v = at(pk, place)
    if v is None:
        return None
    knows = [f["text"][:60] for f in recall(v, topic)]

    line = None
    if api_key:
        try:
            from openai import OpenAI
            c = OpenAI(api_key=api_key)
            sysmsg = (
                f"너는 '{v['name']}'. {v['persona']} {place}에 산다.\n"
                + (f"네가 아는 것: {'; '.join(knows)}\n" if knows else "")
                + "규칙: 반말, 한 문장, 이모지 없음. "
                  "네 일과 네가 사는 곳에서 나온 말을 해라. "
                  "모르는 것은 모른다고 하고 지어내지 마라.")
            r = c.chat.completions.create(
                model="gpt-4o-mini", temperature=0.85, max_tokens=70,
                messages=[{"role": "system", "content": sysmsg},
                          {"role": "user",
                           "content": f"{who}가 '{topic}' 이야기를 꺼냈다."}])
            line = (r.choices[0].message.content or "").strip()[:160]
        except Exception:
            line = None
    if not line:
        line = f"{topic}? 여기선 그런 얘기 잘 안 하는데."

    hear(v, f"{who}가 {topic} 얘기를 했다", who)
    try:
        ident._reinforce_or_add(f"{v['name']}는 {line[:60]}",
                                source="village")
    except Exception:
        pass
    log(f"  🧑‍🌾 {v['name']}: {line[:46]}")
    return {"who": v["name"], "place": place, "line": line}


def context_line(pk: dict, place: str, cue: str = "") -> str:
    v = at(pk, place)
    if not v:
        return ""
    knows = [f["text"][:50] for f in recall(v, cue)]
    return (f"[여기 사는 친구] {v['name']} — {v['persona']}"
            + (f" / 아는 것: {'; '.join(knows)}" if knows else "") + "\n")


def describe(pk: dict) -> str:
    k = known(pk)
    if not k:
        return ""
    return "[핀코] " + " · ".join(f"{v['name']}({v['place']})" for v in k[:5])

