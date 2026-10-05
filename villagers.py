"""
villagers.py — 마을에 사는 이웃들.

얼마나 두껍게 만드나
  몰랑이만큼은 아니다. 그렇다고 가볍지도 않다.
  기준은 하나다 — **몰랑이가 보기에 가짜라고 느끼지 않을 것.**

  그러려면 이 넷이 있으면 된다.
    1) 자기 기억      어제 한 말을 오늘도 안다 (매번 초면이면 바로 들킨다)
    2) 변하는 관심    들은 말이 물들고, 다음에 그 얘기를 꺼낸다
    3) 자기 자리      아무 데나 나타나지 않는다
    4) 없을 때의 삶   "아까 미피랑 놀았어" 같은 말이 나온다

  꿈·기분·목적·판단 트리·여행은 없어도 된다. 몰랑이는 그 안을 못 본다.

검색을 안 하는 이유
  마을 사람이 다 바깥을 검색하면 그건 마을이 아니라 각자 뉴스 보는 것이다.
  이웃들은 **서로에게서 배운다.** 바깥 소식은 몰랑이가 가져온다 —
  그게 몰랑이의 자리이기도 하다.
"""
from __future__ import annotations
import random
import re
import time

BLEED = 0.12              # 들은 말이 관심에 물드는 정도
FADE = 0.985              # 회차마다 조금씩 옅어진다
MAX_FACTS = 60
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")

PEOPLE = {
    "슈야": {
        "home": "슈야토야네", "with": "토야",
        "persona": ("슈크림 토끼. 토야와 함께 산다. 느긋하고 다정하다. "
                    "먹는 것과 만드는 것을 좋아한다. 토야 얘기를 자주 한다."),
        "seed": ["슈크림", "빵", "부엌", "굽기", "토야"],
    },
    "토야": {
        "home": "슈야토야네", "with": "슈야",
        "persona": ("초코크림 토끼. 슈야와 함께 산다. 또렷하고 솔직하다. "
                    "슈야가 흘린 걸 챙기고, 가끔 핀잔을 준다."),
        "seed": ["초코", "크림", "정리", "챙기기", "슈야"],
    },
    "미피": {
        "home": "미피네", "with": None,
        "persona": ("아기 토끼. 아직 모르는 게 많아서 자주 묻는다. "
                    "'그게 뭐야?' 를 잘 한다. 들은 말을 반쯤 이해하고 "
                    "다른 데 가서 옮긴다. 금방 신이 나고 금방 잠든다."),
        "seed": ["놀이", "작은", "낮잠", "궁금", "장난감"],
    },
}


def blank(name: str) -> dict:
    p = PEOPLE.get(name) or {}
    return {"name": name, "facts": [], "where": p.get("home"),
            "interests": {w: 0.6 for w in (p.get("seed") or [])},
            "met": {}, "last": None}


def load(sb) -> dict:
    """주민 전체를 한 번에. 가벼우므로 한 행에 같이 둔다."""
    try:
        rows = (sb.table("molang_villagers").select("data")
                .eq("id", 1).limit(1).execute().data) or []
        d = (rows[0]["data"] if rows and rows[0].get("data") else {}) or {}
    except Exception:
        d = {}
    for n in PEOPLE:
        if n not in d:
            d[n] = blank(n)
    return d


def save(sb, who: dict) -> bool:
    try:
        for v in who.values():
            v["facts"] = (v.get("facts") or [])[-MAX_FACTS:]
        sb.table("molang_villagers").upsert(
            {"id": 1, "data": who}, on_conflict="id").execute()
        return True
    except Exception:
        return False


# ── 기억하고 물든다 ─────────────────────────────────────────
def hear(v: dict, text: str, who_from: str = "") -> None:
    """
    들은 말이 기억이 되고 관심에 물든다.
    같은 말을 또 들으면 더 또렷해진다.
    """
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
    # 조사를 떼고, 주제가 될 만한 낱말만 관심에 올린다.
    # ('우유식빵은', '부드럽다고' 가 그대로 관심이 되면 부스러기만 쌓인다)
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


def recall(v: dict, cue: str = "", n: int = 3) -> list:
    """계기가 있으면 그에 맞는 것, 없으면 최근 것."""
    facts = v.get("facts") or []
    if not facts:
        return []
    if cue:
        key = set(TOKEN.findall(cue))
        hit = [f for f in facts if key & set(TOKEN.findall(f.get("text", "")))]
        if hit:
            return sorted(hit, key=lambda f: -f.get("n", 1))[:n]
    return sorted(facts, key=lambda f: -f.get("at", 0))[:n]


def tick(v: dict) -> None:
    """회차마다 관심이 조금 옅어진다 (안 그러면 쌓이기만 한다)."""
    it = v.get("interests") or {}
    for k in list(it):
        it[k] = round(it[k] * FADE, 4)
        if it[k] < 0.05:
            it.pop(k, None)


# ── 돌아다닌다 ──────────────────────────────────────────────
def walk(sb, who: dict, vil: dict, rng=None, log=print) -> dict:
    """
    각자 자기 자리에서 움직인다.
    슈야와 토야는 대개 같이 다니되 가끔 따로 — 그래야 서로 얘기할 거리가 생긴다.
    미피는 멀리 안 간다.
    """
    rng = rng or random.Random(time.time_ns())
    places = list((vil.get("places") or {}))
    # **바다·숲 같은 바깥도 간다.**
    # 자기 집과 몰랑이네만 오가면 지도가 영영 안 넓어진다.
    try:
        import land as _ld
        places += [p.get("kind") for p in (_ld.load(sb).get("places") or [])
                   if p.get("kind")]
    except Exception:
        pass
    if not places:
        return {}
    moved = {}
    for name, v in who.items():
        p = PEOPLE.get(name) or {}
        if rng.random() > 0.45:
            continue
        here = v.get("where") or p.get("home")
        # 미피는 집에서 먼 데는 안 간다
        cand = [x for x in places if x != here]
        # 안 가본 곳이 더 끌린다 — 그래야 동네가 넓어진다
        been = set((v.get("been") or []))
        fresh = [x for x in cand if x not in been]
        if fresh and rng.random() < 0.6:
            cand = fresh
        if name == "미피":
            import village as _vg
            cand = [x for x in cand
                    if _vg.distance(vil, p.get("home"), x) <= 4.0] or cand
        if not cand:
            continue
        v["where"] = rng.choice(cand)
        v.setdefault("been", [])
        if v["where"] not in v["been"]:
            v["been"].append(v["where"])
        moved[name] = v["where"]

    # 커플은 대개 붙어 다닌다 (가끔 따로)
    if "슈야" in moved or "토야" in moved:
        if rng.random() < 0.7:
            lead = "슈야" if "슈야" in moved else "토야"
            other = PEOPLE[lead]["with"]
            if other in who:
                who[other]["where"] = who[lead]["where"]
                moved[other] = who[lead]["where"]
    if moved:
        log("  마을: " + " · ".join(f"{k}→{x}" for k, x in moved.items()))
    return moved


def who_is_at(who: dict, place: str) -> list:
    return [n for n, v in who.items() if v.get("where") == place]


def nearby(who: dict, vil: dict, place: str, dist: float = 2.0) -> list:
    """그 자리에 있거나 가까이 있는 이웃들."""
    import village as _vg
    out = []
    for n, v in who.items():
        w = v.get("where")
        if not w:
            continue
        if w == place or _vg.distance(vil, w, place) <= dist:
            out.append(n)
    return out


def chat(sb, who: dict, name: str, mol_ident, topic: str,
         api_key: str = None, log=print) -> dict | None:
    """
    마주친 이웃과 한 마디. 들은 것은 **양쪽 다** 기억한다.
    미피는 되묻고, 슈야·토야는 서로 얘기를 꺼낸다 — 성격이 말에 남는다.
    """
    v = who.get(name)
    if v is None:
        return None
    p = PEOPLE.get(name) or {}
    knows = [f["text"][:60] for f in recall(v, topic, 2)]
    bond_line = ""
    try:
        import bonds as _bd
        _b = _bd.load(sb)
        bond_line = _bd.context_line(_b, "몰랑이", name, topic)
    except Exception:
        _b = None

    line = None
    if api_key:
        try:
            from openai import OpenAI
            c = OpenAI(api_key=api_key)
            sysmsg = (
                f"너는 '{name}'. {p.get('persona','')}\n"
                "몰랑이(대왕토끼)와 마을에서 마주쳐 한 마디 나눈다.\n"
                + bond_line
                + (f"네가 아는 것: {'; '.join(knows)}\n" if knows else "")
                + "규칙: 반말, 한 문장, 이모지 없음. "
                  "모르는 것은 모른다고 하고 지어내지 마라. "
                  "아는 것이 있으면 그걸 꺼내라 — 처음 듣는 척하지 마라.")
            r = c.chat.completions.create(
                model="gpt-4o-mini", temperature=0.8, max_tokens=70,
                messages=[{"role": "system", "content": sysmsg},
                          {"role": "user",
                           "content": f"몰랑이가 '{topic}' 이야기를 꺼냈다."}])
            line = (r.choices[0].message.content or "").strip()[:160]
        except Exception:
            line = None
    if not line:
        line = (f"{topic}? 그게 뭐야?" if name == "미피"
                else f"{topic} 얘기구나.")

    hear(v, f"몰랑이가 {topic} 얘기를 했다", "몰랑이")
    try:
        import bonds as _bd2
        _b2 = _b if _b is not None else _bd2.load(sb)
        _bd2.remember(_b2, "몰랑이", name, topic, said_b=line)
        _bd2.save(sb, _b2)
    except Exception:
        pass
    try:
        mol_ident._reinforce_or_add(f"{name}는 {line[:60]}", source="peer")
    except Exception:
        pass
    log(f"  🏘️ {name}: {line[:50]}")
    return {"who": name, "line": line, "topic": topic}


def context_line(who: dict, names: list, cue: str = "") -> str:
    """대화 프롬프트에 — 이 이웃이 무엇을 알고 있는지."""
    if not names:
        return ""
    bits = []
    for n in names[:2]:
        v = who.get(n) or {}
        p = PEOPLE.get(n) or {}
        know = [f["text"][:50] for f in recall(v, cue, 2)]
        bits.append(f"{n}: {p.get('persona','')[:60]}"
                    + (f" / 아는 것: {'; '.join(know)}" if know else ""))
    return "[옆에 있는 이웃]\n" + "\n".join(bits) + "\n"
