"""
word_gravity.py — 낱말이 어디로 끌리는가.

무엇이 문제였나
  의미 지도는 실의 **굵기**만 안다. 그래서 같은 낱말이 여러 자리에 걸쳐 있을 때
  **어디가 제 자리인지** 가리지 못한다.
    · '한로로' 가 '한로'(24절기) 와 엉켜 있다
    · '바다' 에 붙은 것이 '다운로드', '무료' (이미지 사이트 자료)
  굵기만 보면 둘 다 그냥 "이어져 있다" 이다.

어떻게 가리나 (GravPrison 의 중력 퍼텐셜 공식을 그대로 빌린다)
      potential(r, M) = -G·M / r
  낱말에 옮기면
    M (질량)  그 낱말이 얼마나 자주, 얼마나 굳게 쓰였나 — **친숙도**
    r (거리)  두 낱말이 얼마나 멀리 있나 — 연결도의 역수
    끌림      |−G·M/r| — 무겁고 가까울수록 세게 끌린다

  그러면 같은 실이라도 **어느 쪽으로 더 끌리는지**가 숫자로 갈린다.
  '바다' 는 '바다사진'(가볍고 한 자료에만 붙음) 보다 '파도'(무겁고 여러 자료에
  걸침) 쪽으로 더 끌린다 — 자료가 쌓이면.

무엇이 달라지나
  · 프롬프트에 넣을 이웃을 **끌림 순서**로 고른다 → 말이 더 자연스러워진다
  · 한 낱말이 어느 갈래에 속하는지 **끌림 합**으로 정한다 → 엉킨 마디가 갈린다
  · 끌림이 어느 쪽에도 크지 않으면 '아직 자리를 못 잡은 낱말' 로 표시한다

조사·말끝은 질량을 갖지 않는다 (어디에나 붙어 모든 것을 끌어당긴다)
"""
from __future__ import annotations
import math

G = 10.0                 # 세기 (GravPrison 기본값을 그대로)
EPS = 1e-9
MIN_MASS = 0.15          # 이보다 가벼우면 끌지 못한다


MARKOV_RATIO = 0.0        # 0이면 지금 그대로, 1이면 마르코프만.
                          # **나란히 둔다** — 갈아엎지 않고 섞는 비율만 바꾼다.


def masses_with_markov(gmap: dict, facts: list = None,
                       mk_mass: dict = None, ratio: float = None) -> dict:
    """
    기존 질량과 **자석 낱말**(마르코프)을 섞는다.

    기존 지도를 건드리지 않는 이유:
      · 둘을 견줘야 어느 쪽이 나은지 알 수 있다
      · 나쁘면 되돌릴 수 있다
      · 연속성 측정이 지금 구조에 기대고 있다
    """
    base = masses(gmap, facts)
    r = MARKOV_RATIO if ratio is None else ratio
    if not mk_mass or r <= 0:
        return base
    import markov_mass as _mk
    return _mk.blend(base, mk_mass, r)


def masses(gmap: dict, facts: list = None) -> dict:
    """
    낱말의 질량 = 친숙도.
      얼마나 자주 나왔나 × 얼마나 여러 갈래에 걸치나 × (사실로 굳었으면 더)
    """
    freq = gmap.get("freq") or {}
    edges = gmap.get("edges") or {}
    if not freq:
        return {}

    spread = {}
    for (a, b) in edges:
        spread[a] = spread.get(a, 0) + 1
        spread[b] = spread.get(b, 0) + 1

    fact_words = set()
    for f in (facts or []):
        t = f.get("text", "") if isinstance(f, dict) else str(f)
        try:
            from organism.curiosity import strip_josa, canon_name
            import re
            for w in re.findall(r"[가-힣A-Za-z]{2,}", t):
                fact_words.add(canon_name(strip_josa(w)))
        except Exception:
            pass

    # 조사·말끝은 질량을 갖지 않는다. 어디에나 붙어 있어서 자주 나오는데,
    # 무겁게 잡으면 **모든 낱말을 자기 쪽으로 끌어당겨** 지도가 망가진다.
    # ('것을'이 '바다'만큼 무거워지는 일이 실제로 있었다)
    def _weightless(x: str) -> bool:
        try:
            from organism.curiosity import _is_topic_like, TALK_WORDS
            if x in TALK_WORDS or not _is_topic_like(x):
                return True
        except Exception:
            pass
        return (len(x) < 2
                or x.endswith(("것을", "것이", "것은", "것에", "되다", "하다"))
                or x in ("것을", "것이", "것은", "것에", "많다", "됐다",
                         "되었다", "있다", "없다", "같다", "한다", "된다"))

    mx = max(freq.values()) or 1
    out = {}
    for w, c in freq.items():
        if _weightless(w):
            out[w] = 0.0
            continue
        base = math.log1p(c) / math.log1p(mx)          # 자주 나왔나
        reach = math.log1p(spread.get(w, 0)) / 3.0      # 여러 곳에 걸치나
        solid = 0.4 if w in fact_words else 0.0         # 사실로 굳었나
        out[w] = round(min(2.0, base + reach + solid), 3)
    return out


def distance(gmap: dict, a: str, b: str) -> float:
    """연결이 굵을수록 가깝다. 없으면 아주 멀다."""
    e = gmap.get("edges") or {}
    w = e.get((a, b), e.get((b, a), 0.0))
    return 1.0 / (w + EPS) if w > 0 else 1e6


def pull(gmap: dict, mass: dict, a: str, b: str) -> float:
    """
    a 가 b 에게 얼마나 끌리는가. |−G·M_b / r|
    (끌림은 한쪽 방향이다 — 무거운 쪽이 더 세게 당긴다)
    """
    M = mass.get(b, 0.0)
    if M < MIN_MASS:
        return 0.0
    r = distance(gmap, a, b)
    return round(abs(-G * M / (r + EPS)), 4)


def attracted(gmap: dict, mass: dict, word: str, k=8) -> list:
    """이 낱말이 끌리는 쪽 — 끌림이 센 순서로."""
    import semantic_map as S
    out = []
    for nb, _ in S.neighbors(gmap, word, k=40):
        p = pull(gmap, mass, word, nb)
        if p > 0:
            out.append((nb, p))
    out.sort(key=lambda x: -x[1])
    return out[:k]


def home_branch(gmap: dict, mass: dict, clusters: list, word: str) -> dict:
    """
    이 낱말의 제 자리는 어느 갈래인가.
    갈래 안 낱말들이 당기는 힘을 다 더해서 가장 센 쪽.
    (한 마디가 여러 갈래에 걸쳐 있을 때 이걸로 갈린다)
    """
    scores = []
    for c in (clusters or []):
        s = sum(pull(gmap, mass, word, m) for m in c["members"] if m != word)
        if s > 0:
            scores.append((c["name"], round(s, 3)))
    if not scores:
        return {"branch": None, "score": 0.0, "settled": False, "rivals": []}
    scores.sort(key=lambda x: -x[1])
    top = scores[0]
    second = scores[1][1] if len(scores) > 1 else 0.0
    # 1등이 2등을 넉넉히 앞서야 '자리를 잡았다'고 본다
    settled = top[1] > second * 1.6 and top[1] > 0.5
    return {"branch": top[0], "score": top[1], "settled": settled,
            "rivals": scores[1:3]}


def unsettled(gmap: dict, mass: dict, clusters: list, limit=20) -> list:
    """
    아직 자리를 못 잡은 낱말들.
    여러 갈래가 비슷한 힘으로 당기고 있다 — 엉켜 있다는 뜻.
    ('한로로'가 절기와 가수 사이에서 갈리지 못하는 것처럼)
    """
    out = []
    for w in (gmap.get("freq") or {}):
        h = home_branch(gmap, mass, clusters, w)
        if h["branch"] and not h["settled"] and h["rivals"]:
            out.append({"word": w, "between": [h["branch"]] +
                        [r[0] for r in h["rivals"]],
                        "score": h["score"]})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


def context_line(gmap: dict, mass: dict, clusters: list, words: list,
                 k=5) -> str:
    """
    프롬프트에 넣을 줄. 이웃을 **끌림 순서**로 준다.
    굵기순으로 주면 '바다 → 다운로드' 가 앞에 오지만,
    끌림순이면 무겁고 여러 곳에 걸친 쪽이 앞에 온다.
    """
    lines = []
    for w in words[:4]:
        att = attracted(gmap, mass, w, k)
        if not att:
            continue
        lines.append(f"  {w} → " + ", ".join(f"{n}" for n, _ in att))
        h = home_branch(gmap, mass, clusters, w)
        if h["branch"] and not h["settled"]:
            lines.append(f"    ({w}는 아직 "
                         f"{', '.join([h['branch']] + [r[0] for r in h['rivals']])} "
                         "사이에서 자리를 못 잡음 — 단정하지 말 것)")
    return "\n".join(lines)
