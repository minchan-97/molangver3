"""
semantic_map.py — 기억을 목록이 아니라 지도로.

무엇이 문제였나
  한로로를 여러 번 검색했는데도 곡 이름을 못 댔다. 관측이 행으로 쌓이고
  승인된 것이 문장 통째로 트리에 붙을 뿐이라, "한로로에 딸린 것이 무엇인가"
  를 물을 자리가 없었다. 목록은 훑을 수는 있어도 **딸려 나오지 않는다.**

어떻게 바꾸나 (관계 이름을 미리 정하지 않는다)
  1. 가깝다만 쌓는다   같은 자료에 함께 나온 두 낱말을 잇는다. 반복되면 굵어진다.
  2. 뭉치가 생긴다     굵게 이어진 것들이 한 덩어리가 된다.
  3. 이름이 붙는다     뭉친 것들이 함께 지니는 낱말이 그 갈래의 이름이 된다.
                       (미리 '곡','가수' 를 정해두면 그 틀 밖은 영영 안 보인다)
  4. 그 갈래로 뻗는다  새 자료는 있는 갈래에 붙거나, 없으면 새 갈래를 만든다.

무엇이 좋아지나
  · 딸려 나온다   '한로로' 마디에서 가지만 따라가면 된다 (전부 훑지 않는다)
  · 빈자리가 보인다  가지가 없으면 '모른다'가 드러난다 — 지어낼 자리가 준다
  · 새로 생긴다   두 마디가 같은 이웃을 공유하면, 직접 말한 적 없는 연결이 생긴다

한계를 먼저 적어둔다
  자료가 적으면 갈래가 안 갈린다. 지금 관측 수백 건으로는 성글다.
  다만 목록 구조는 쌓여도 좋아지지 않지만, 지도는 쌓일수록 좋아진다.
"""
from __future__ import annotations
import math
import re
import time
from collections import Counter, defaultdict

TOKEN = re.compile(r"[가-힣A-Za-z][가-힣A-Za-z0-9]{1,15}")
MIN_LINK = 2            # 이만큼 함께 나와야 실이 생긴다
MIN_CLUSTER = 3         # 뭉치로 치는 최소 크기
MAX_NODES = 1200


def _words(text: str) -> list:
    ws = TOKEN.findall(text or "")
    try:
        from organism.curiosity import _is_topic_like, strip_josa, canon_name
        out = []
        for w in ws:
            w = canon_name(strip_josa(w))
            if _is_topic_like(w):
                out.append(w)
        return out
    except Exception:
        return [w for w in ws if 2 <= len(w) <= 12]


# ── 1단계: 가깝다만 쌓기 ─────────────────────────────────────
def build(docs: list[str], keep=MAX_NODES) -> dict:
    """
    자료 묶음 → 지도.
    docs 하나가 한 자료(관측 제목+본문, 사실 문장, 대화 한 토막).
    """
    co = defaultdict(Counter)
    freq = Counter()
    for d in docs:
        ws = list(dict.fromkeys(_words(d)))[:14]      # 한 자료 안 중복 제거
        for w in ws:
            freq[w] += 1
        for i in range(len(ws)):
            for j in range(i + 1, len(ws)):
                co[ws[i]][ws[j]] += 1
                co[ws[j]][ws[i]] += 1

    # 너무 흔한 낱말은 이어봐야 뜻이 없다 (어디에나 붙는다)
    n = max(1, len(docs))
    common = {w for w, c in freq.items() if c / n > 0.25}

    edges = {}
    for a, row in co.items():
        if a in common:
            continue
        for b, c in row.items():
            if b in common or c < MIN_LINK or a >= b:
                continue
            # 함께 나온 정도를 각자의 흔함으로 나눈다 (PMI 비슷하게)
            w = c / math.sqrt(freq[a] * freq[b])
            edges[(a, b)] = round(w, 3)

    nodes = sorted({x for e in edges for x in e},
                   key=lambda w: -freq[w])[:keep]
    keepset = set(nodes)
    edges = {k: v for k, v in edges.items()
             if k[0] in keepset and k[1] in keepset}
    return {"freq": {w: freq[w] for w in nodes}, "edges": edges,
            "built_at": time.time(), "docs": len(docs)}


def neighbors(gmap: dict, word: str, k=8) -> list:
    """한 마디에 딸린 것들 — 목록을 훑지 않고 가지만 따라간다."""
    out = []
    for (a, b), w in (gmap.get("edges") or {}).items():
        if a == word:
            out.append((b, w))
        elif b == word:
            out.append((a, w))
    out.sort(key=lambda x: -x[1])
    return out[:k]


# ── 2·3단계: 뭉치와 이름 ─────────────────────────────────────
def clusters(gmap: dict, min_size=MIN_CLUSTER) -> list:
    """
    굵게 이어진 것끼리 묶는다. (라벨 전파 — 가볍고 결정적)
    그리고 그 뭉치가 함께 지니는 낱말을 이름으로 삼는다.
    """
    edges = gmap.get("edges") or {}
    adj = defaultdict(list)
    for (a, b), w in edges.items():
        adj[a].append((b, w))
        adj[b].append((a, w))
    if not adj:
        return []

    label = {n: i for i, n in enumerate(sorted(adj))}
    for _ in range(12):
        changed = False
        for n in sorted(adj, key=lambda x: -len(adj[x])):
            score = Counter()
            for m, w in adj[n]:
                score[label[m]] += w
            if score:
                best = max(score.items(), key=lambda kv: (kv[1], -kv[0]))[0]
                if label[n] != best:
                    label[n] = best
                    changed = True
        if not changed:
            break

    groups = defaultdict(list)
    for n, l in label.items():
        groups[l].append(n)

    out = []
    for members in groups.values():
        if len(members) < min_size:
            continue
        members.sort(key=lambda w: -gmap["freq"].get(w, 0))
        # 갈래 이름: 뭉치 안에서 가장 많은 이웃을 거느린 낱말
        inner = Counter()
        for m in members:
            inner[m] = sum(1 for x, _ in adj[m] if x in members)
        name = inner.most_common(1)[0][0] if inner else members[0]
        out.append({"name": name, "members": members[:20],
                    "size": len(members),
                    "density": round(
                        sum(w for (a, b), w in edges.items()
                            if a in members and b in members)
                        / max(1, len(members)), 3)})
    out.sort(key=lambda c: -c["size"])
    return out


# ── 4단계: 새 자료가 갈래로 ──────────────────────────────────
def place(gmap: dict, cls: list, text: str) -> dict:
    """새 자료가 어느 갈래에 붙나. 어디에도 안 붙으면 새 갈래 후보."""
    ws = set(_words(text))
    if not ws or not cls:
        return {"branch": None, "new": bool(ws)}
    best, score = None, 0
    for c in cls:
        hit = len(ws & set(c["members"]))
        if hit > score:
            best, score = c["name"], hit
    return {"branch": best, "hits": score,
            "new": best is None}


def gaps(gmap: dict, cls: list, word: str) -> dict:
    """
    이 마디에 무엇이 비어 있나.
    같은 갈래의 다른 마디들은 가진 이웃인데 이 마디엔 없는 것.
    → '모른다'를 드러내는 자리.
    """
    mine = {w for w, _ in neighbors(gmap, word, k=30)}
    for c in cls:
        if word in c["members"]:
            theirs = Counter()
            for m in c["members"]:
                if m == word:
                    continue
                for x, _ in neighbors(gmap, m, k=20):
                    if x not in mine and x != word:
                        theirs[x] += 1
            return {"branch": c["name"],
                    "missing": [w for w, _ in theirs.most_common(6)]}
    return {"branch": None, "missing": []}


# ── 확신이 낮으면 갈래를 다시 쪼갠다 ────────────────────────
def confidence(gmap: dict, cls: dict) -> float:
    """
    이 갈래를 얼마나 믿을 수 있나.
      촘촘함  안쪽이 실제로 서로 이어져 있나
      순수함  바깥으로 새는 실이 적은가
    둘 다 낮으면 '한 갈래'라고 부를 근거가 약하다.
    """
    edges = gmap.get("edges") or {}
    mem = set(cls["members"])
    inner = outer = 0.0
    for (a, b), w in edges.items():
        ia, ib = a in mem, b in mem
        if ia and ib:
            inner += w
        elif ia or ib:
            outer += w
    if inner <= 0:
        return 0.0
    purity = inner / (inner + outer)
    density = inner / max(1, len(mem))
    return round(min(1.0, purity * min(1.0, density)), 3)


def resplit(gmap: dict, cls: dict, parts: int = 2) -> list:
    """
    확신이 낮은 갈래를 **다시 나눠 본다.**
    안에서 가장 약한 실을 끊어 두 덩어리로 가른 뒤, 각각이 더 나은지 본다.
    (사람도 뭉뚱그린 게 미심쩍으면 갈라서 다시 본다)
    """
    mem = list(cls["members"])
    if len(mem) < 4:
        return []
    edges = {k: v for k, v in (gmap.get("edges") or {}).items()
             if k[0] in mem and k[1] in mem}
    if not edges:
        return []

    # 갈래 안에 실이 성글면 이어 붙이기로는 조각이 다 흩어진다.
    # 그래서 **서로 가장 먼 두 마디를 씨앗으로 잡고** 나머지를 가까운 쪽에 붙인다.
    # (사람도 뭉뚱그린 걸 가를 땐 양 끝을 먼저 잡는다)
    link = {}
    for (a, b), w in edges.items():
        link[(a, b)] = w
        link[(b, a)] = w

    def tie(x, y):
        return link.get((x, y), 0.0)

    seeds = None
    worst = 1e9
    top = mem[:8]                          # 굵은 마디들 중에서 고른다
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            t = tie(top[i], top[j])
            if t < worst:
                worst, seeds = t, (top[i], top[j])
    if not seeds:
        return []

    groups = {seeds[0]: [seeds[0]], seeds[1]: [seeds[1]]}
    for m in mem:
        if m in seeds:
            continue
        a = sum(tie(m, x) for x in groups[seeds[0]])
        b = sum(tie(m, x) for x in groups[seeds[1]])
        groups[seeds[0] if a >= b else seeds[1]].append(m)

    # 한쪽이 작아도 버리지 않는다. 작은 쪽이 오히려 또렷한 갈래일 때가 있다
    # ('고대'에서 '마인크래프트'가 갈라져 나오는 것처럼).
    pieces = [v for v in groups.values() if len(v) >= 2]
    if len(pieces) < 2:
        return []

    out = []
    for p in pieces:
        p.sort(key=lambda w: -gmap["freq"].get(w, 0))
        sub = {"name": p[0], "members": p, "size": len(p),
               "density": cls.get("density", 0)}
        sub["confidence"] = confidence(gmap, sub)
        out.append(sub)
    return out


def review(gmap: dict, cls: list, thr: float = 0.35, log=print) -> dict:
    """
    갈래를 훑고, 확신이 낮은 것은 쪼개 본다.
    쪼갠 쪽이 더 확실하면 그걸 쓴다. 아니면 그대로 둔다 — 억지로 가르지 않는다.
    """
    kept, split = [], []
    for c in cls:
        c = dict(c)
        c["confidence"] = confidence(gmap, c)
        if c["confidence"] >= thr:
            kept.append(c)
            continue
        subs = resplit(gmap, c)
        # 쪼갠 쪽을 '평균'으로 견주면 작은 부스러기 하나가 끌어내려 늘 실패한다.
        # 큰 조각들이 실제로 더 또렷해졌는지를 본다.
        if subs:
            big = [s for s in subs if s["size"] >= 3] or subs
            gain = max(s["confidence"] for s in big)
        else:
            gain = 0.0
        if subs and gain > c["confidence"] + 0.05:
            for s in subs:
                s["from"] = c["name"]
            split.append({"was": c["name"], "into": [s["name"] for s in subs],
                          "before": c["confidence"],
                          "after": round(gain, 3)})
            kept.extend(subs)
        else:
            c["unsure"] = True          # 미심쩍지만 가를 근거도 없다
            kept.append(c)
    if split:
        log("  갈래 다시 나눔: " + " · ".join(
            f"{s['was']}→{'+'.join(s['into'])}({s['before']}→{s['after']})"
            for s in split[:3]))
    kept.sort(key=lambda c: -c["size"])
    return {"clusters": kept, "split": split,
            "unsure": [c["name"] for c in kept if c.get("unsure")]}


# ── 저장·갱신 ────────────────────────────────────────────────
def load(sb) -> tuple:
    try:
        rows = (sb.table("molang_map").select("graph,clusters")
                .eq("id", 1).limit(1).execute().data) or []
        if rows:
            g = rows[0].get("graph") or {}
            if g.get("edges"):      # jsonb 는 튜플 키를 못 담아 문자열로 저장한다
                g["edges"] = {tuple(k.split("\t")): v
                              for k, v in g["edges"].items()}
            return g, (rows[0].get("clusters") or [])
    except Exception:
        pass
    return {}, []


def save(sb, gmap: dict, cls: list) -> bool:
    try:
        g = dict(gmap)
        g["edges"] = {f"{a}\t{b}": w for (a, b), w in (gmap.get("edges") or {}).items()}
        sb.table("molang_map").upsert(
            {"id": 1, "graph": g, "clusters": cls}, on_conflict="id").execute()
        return True
    except Exception:
        return False


def rebuild(sb, limit=800, log=print) -> dict:
    """관측과 사실로 지도를 다시 그린다. 확신 낮은 갈래는 쪼개 본다."""
    docs = []
    try:
        rows = (sb.table("organism_observations")
                .select("topic,title,text").order("id", desc=True)
                .limit(limit).execute().data) or []
        docs += [f"{r.get('topic','')} {r.get('title') or ''} "
                 f"{(r.get('text') or '')[:200]}" for r in rows]
    except Exception:
        pass
    try:
        rows = (sb.table("molang_facts_active").select("text")
                .limit(400).execute().data) or []
        docs += [r.get("text", "") for r in rows]
    except Exception:
        pass
    docs = [d for d in docs if d and d.strip()]
    if len(docs) < 20:
        return {"skip": f"자료가 {len(docs)}건뿐"}

    g = build(docs)
    cls = clusters(g)
    r = review(g, cls, log=log)

    # 낱말 질량(친숙도)도 함께 — 같은 실이라도 어디로 끌리는지가 갈린다
    try:
        import word_gravity as _wg
        facts = (sb.table("molang_facts_active").select("text")
                 .limit(400).execute().data) or []
        g["mass"] = _wg.masses(g, facts)
        unset = _wg.unsettled(g, g["mass"], r["clusters"], 10)
        if unset:
            log("  아직 자리를 못 잡은 낱말: " + ", ".join(
                f"{u['word']}({'/'.join(u['between'][:2])})" for u in unset[:4]))
        r["unsettled"] = unset
    except Exception as e:
        log(f"  끌림 계산 건너뜀: {str(e)[:60]}")

    save(sb, g, r["clusters"])
    log(f"  의미 지도: {summary(g, r['clusters'])}")
    return {"nodes": len(g.get("freq") or {}), "edges": len(g.get("edges") or {}),
            "clusters": len(r["clusters"]), "split": r["split"],
            "unsure": r["unsure"][:6],
            "unsettled": [u["word"] for u in (r.get("unsettled") or [])][:6]}


def summary(gmap: dict, cls: list) -> str:
    return (f"마디 {len(gmap.get('freq') or {})}개 · 실 "
            f"{len(gmap.get('edges') or {})}개 · 갈래 {len(cls)}개 "
            f"(자료 {gmap.get('docs')}건)")
