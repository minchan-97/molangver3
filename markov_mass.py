"""
markov_mass.py — **자석 낱말**. 자주 불려 나오는 말이 무거워진다.

지금 지도와 무엇이 다른가
  semantic_map 은 **함께 나왔다**만 센다. 대칭이고 방향이 없다.
  그래서 '바다' 와 '파도' 가 가까운 이유가 "같은 글에 있었다" 뿐이다.

  여기서는 **무엇 다음에 무엇이 왔나**를 센다. 방향이 생긴다.
  그러면 두 가지가 보인다.
    이어지는 결   바다 → 파도 → 소리 로 흐르는 길
    자석 낱말     여러 낱말이 자기 다음에 부르는 말 (무거워진다)

  이것이 중력의 질량 자리에 들어간다. 자주 불려 나올수록 M 이 크고,
  M 이 크면 주변을 더 세게 당긴다.

겪은 것과 읽은 것
  검색으로 읽은 글이 585건 쌓여 있다. 그대로 세면 **바깥 글이
  대화를 덮는다.** 그러면 지도가 몰랑이의 결이 아니라 인터넷의 결이 된다.
  그래서 겪은 쪽(대화·피우피우·여행·꿈)에 가중치를 더 준다.

기존 지도를 건드리지 않는다
  나란히 둔다. 그래야 둘을 견줄 수 있고, 나쁘면 되돌릴 수 있고,
  연속성 측정이 흔들리지 않는다. 섞는 비율도 그때그때 바꿀 수 있다.
"""
from __future__ import annotations
import math
import re
from collections import defaultdict

WINDOW = 3                # 앞뒤 몇 칸까지 '다음'으로 볼까 (한국어는 어순이 자유롭다)
MIN_COUNT = 2             # 이보다 적게 나온 이음은 버린다
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")

# **아무 데나 붙는 말**은 자석이 아니다.
# 사실 문장이 대개 '~것을 알게 됐다' 로 끝나기 때문에, 그 꼬리가
# 모든 낱말 뒤에 오면서 가장 무거운 자석처럼 보였다.
# 쏠림 계산으로는 안 걸러진다 — 입구에서 막는다.
TAIL = re.compile(
    r"^(됐다|되었다|된다|한다|했다|하다|이다|있다|없다|같다|보다|"
    r"알고|알게|느낀다|느꼈다|생각한다|생각했다|싶다|싶어|보인다|"
    r"살고|가는|오는|하는|되는|것에|것을|것이|대해|통해|위해)$")

# 겪은 것이 읽은 것보다 무겁다
WEIGHT = {
    "user": 3.0,          # 사용자가 한 말
    "peer": 2.0,          # 피우피우와의 대화
    "village": 2.0,       # 마을 사람들
    "travel": 2.5,        # 여행에서 본 것
    "dream": 1.5,         # 꿈
    "home": 1.5, "land": 1.5,
    "self": 2.0,
    "search": 1.0,        # 읽은 글 — 가장 가볍다
    "": 1.0,
}


def _words(text: str) -> list:
    out = []
    for w in TOKEN.findall(text or ""):
        try:
            from organism.curiosity import strip_josa, _is_topic_like
            w = strip_josa(w)
            if not _is_topic_like(w):
                continue
        except Exception:
            pass
        if len(w) >= 2 and not TAIL.match(w):
            out.append(w)
    return out


def count(docs: list, log=None) -> dict:
    """
    무엇 다음에 무엇이 왔나.

    docs: [{"text": ..., "source": ...}, ...]
    앞뒤 WINDOW 칸을 본다. 가까울수록 세게 센다.
    """
    trans = defaultdict(lambda: defaultdict(float))
    seen = defaultdict(float)
    for d in docs or []:
        ws = _words(d.get("text") or "")
        if len(ws) < 2:
            continue
        w = WEIGHT.get(d.get("source") or "", 1.0)
        for i, a in enumerate(ws):
            seen[a] += w
            for j in range(i + 1, min(i + 1 + WINDOW, len(ws))):
                b = ws[j]
                if a == b:
                    continue
                # 가까울수록 세게 (1칸 1.0, 2칸 0.5, 3칸 0.33)
                trans[a][b] += w / (j - i)
    out = {a: dict(d) for a, d in trans.items()}
    if log:
        log(f"  마르코프: 낱말 {len(out)}개 · 이음 "
            f"{sum(len(v) for v in out.values())}개")
    return {"trans": out, "seen": dict(seen)}


def masses(mk: dict) -> dict:
    """
    **자석 낱말** — 여러 낱말이 자기 다음에 부르는 말이 무겁다.

    다만 '됐다·되었다·것에' 처럼 **아무 데나 붙는 말**이 있다. 그것들은
    부르는 쪽이 많아도 자석이 아니다. 아무 데서나 오는 것은
    아무 데도 가리키지 않기 때문이다.

    그래서 두 가지를 곱한다.
      폭    서로 다른 낱말이 얼마나 많이 부르는가
      쏠림  그 부름이 **한쪽에 몰려 있는가** (고르게 퍼지면 자석이 아니다)
    """
    callers = defaultdict(list)
    for a, nexts in (mk.get("trans") or {}).items():
        tot = sum(nexts.values()) or 1.0
        for b, c in nexts.items():
            if c < MIN_COUNT:
                continue
            callers[b].append(c / tot)

    out = {}
    for b, ps in callers.items():
        n = len(ps)
        if n < 2:
            continue
        # 쏠림: 부름의 세기가 고를수록 0 에 가깝다 (엔트로피의 반대)
        s = sum(ps) or 1e-9
        q = [p / s for p in ps]
        ent = -sum(x * math.log(x + 1e-12) for x in q)
        even = ent / math.log(n) if n > 1 else 1.0   # 0~1, 1이면 완전히 고름
        skew = 1.0 - even
        out[b] = round(math.log1p(n) * math.log1p(s) * (0.2 + skew), 4)
    mx = max(out.values(), default=1.0) or 1.0
    return {k: round(v / mx, 4) for k, v in out.items()}


def next_of(mk: dict, word: str, k: int = 6) -> list:
    """이 낱말 다음에 무엇이 오나 — 확률 순."""
    nexts = (mk.get("trans") or {}).get(word) or {}
    tot = sum(nexts.values()) or 1.0
    out = [(b, round(c / tot, 4)) for b, c in nexts.items() if c >= MIN_COUNT]
    out.sort(key=lambda x: -x[1])
    return out[:k]


def blend(base: dict, mk_mass: dict, ratio: float = 0.5) -> dict:
    """
    기존 질량과 섞는다. **갈아엎지 않는다.**
    ratio 0 이면 지금 그대로, 1 이면 마르코프만.
    """
    out = dict(base or {})
    for w, m in (mk_mass or {}).items():
        old = float(out.get(w, 0.0))
        out[w] = round(old * (1 - ratio) + m * ratio, 4)
    return out


def chain(mk: dict, start: str, steps: int = 4) -> list:
    """이어지는 결 — 가장 그럴듯한 길 하나."""
    path, cur, seen = [start], start, {start}
    for _ in range(steps):
        nx = [(b, p) for b, p in next_of(mk, cur, 8) if b not in seen]
        if not nx:
            break
        cur = nx[0][0]
        seen.add(cur)
        path.append(cur)
    return path


def collect(sb, limit: int = 600) -> list:
    """셀 거리를 모은다 — 겪은 것과 읽은 것."""
    docs = []
    try:
        rows = (sb.table("molang_facts").select("text,source")
                .limit(limit).execute().data) or []
        docs += [{"text": r.get("text"), "source": r.get("source")}
                 for r in rows]
    except Exception:
        pass
    try:
        rows = (sb.table("organism_observations").select("title,text")
                .eq("status", "candidate").limit(limit)
                .execute().data) or []
        docs += [{"text": f"{r.get('title') or ''} {r.get('text') or ''}",
                  "source": "search"} for r in rows]
    except Exception:
        pass
    try:
        rows = (sb.table("molang_episodes").select("question,answer")
                .order("id", desc=True).limit(120).execute().data) or []
        docs += [{"text": r.get("question"), "source": "user"} for r in rows]
    except Exception:
        pass
    return docs
