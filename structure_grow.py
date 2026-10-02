"""
structure_grow.py — 사고 틀을 **로컬에서** 만든다. LLM은 이름만 다듬는다.

왜 바꿨나
  새 사고 유형의 단계와 갈래를 LLM이 설계하고 있었다. 그러면 판단 틀을
  만드는 일 자체가 바깥 모델에 있게 된다. 원칙은 반대다 —
  **로컬이 주인이고 LLM은 말하기 부품**이다.

무엇으로 만드나 (이미 있는 것들만 쓴다)
  · 관측과 사고 기억이 SOM 위에 얹혀 있다. 지도에서 **함께 모이는 묶음**이
    곧 "이런 것들을 함께 다루는 사고"다. 그 묶음의 결이 단계가 된다.
  · 갈래는 지어내지 않는다. 이미 판정이 세 갈래로 갈리고 있다
    (후보 / 격리 / 거부). 그 분포를 그대로 갈림길로 쓴다.
  · 이름은 묶음의 대표 낱말에서 뽑는다.

어떻게 단계를 정하나
  한 묶음 안에서 기록들이 실제로 어떤 순서로 들어왔는지를 본다.
  먼저 들어온 것 = 살피는 단계, 나중 = 가르는 단계.
  억지로 3단을 채우지 않는다. 자료가 두 층이면 두 단계다.

LLM이 하는 일
  만들어진 구조에 **읽기 좋은 이름과 한 줄 설명**을 붙이는 것뿐.
  실패해도 구조는 그대로 산다 (낱말로 된 이름을 쓴다).
"""
from __future__ import annotations
import math
import re
from collections import Counter

import numpy as np

MIN_ITEMS = 6            # 묶음이 이만큼은 돼야 사고 하나로 본다
MIN_SPREAD = 0.15        # 갈래가 이만큼은 갈려 있어야 갈림길
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")


def _vec(text: str):
    from organism.embedder import hashed_embedding
    return hashed_embedding(text or "", dim=64)


def _words(texts) -> Counter:
    c = Counter()
    for t in texts:
        for w in TOKEN.findall(t or ""):
            c[w] += 1
    try:
        from organism.curiosity import _is_topic_like, strip_josa
        out = Counter()
        for w, n in c.items():
            w = strip_josa(w)
            if not _is_topic_like(w):
                continue
            # 출처 이름이 사고 단계가 되면 안 된다.
            # ('한국민족문화대백과사전 견주기' 같은 단계가 실제로 나왔다)
            try:
                import reader
                if reader.is_medium(w) or len(w) > 8:
                    continue
            except Exception:
                pass
            out[w] += n
        return out
    except Exception:
        return c


def find_cluster(sb, limit=400):
    """
    지도 위에서 함께 모이는 묶음 하나를 찾는다.
    (SOM 을 새로 학습하지 않는다 — 이미 있는 관측을 그 자리에서 군집한다)
    """
    try:
        rows = (sb.table("organism_observations")
                .select("id,topic,title,text,status,seen_at")
                .order("id", desc=True).limit(limit).execute().data) or []
    except Exception:
        return None
    if len(rows) < MIN_ITEMS * 2:
        return None

    texts = [f"{r.get('topic','')} {r.get('title','') or ''}" for r in rows]
    X = np.array([_vec(t) for t in texts])

    # 가장 촘촘한 자리 찾기: 서로 가까운 것끼리 묶인 곳
    S = X @ X.T
    np.fill_diagonal(S, -1)
    dens = S.max(axis=1) + np.sort(S, axis=1)[:, -3:].mean(axis=1)
    seed = int(np.argmax(dens))
    sims = X @ X[seed]
    idx = np.argsort(-sims)[:max(MIN_ITEMS, int(len(rows) * 0.12))]
    if len(idx) < MIN_ITEMS:
        return None

    picked = [rows[i] for i in idx]
    return {"rows": picked,
            "texts": [texts[i] for i in idx],
            "cohesion": float(sims[idx].mean())}


def design_from_cluster(cluster: dict) -> dict | None:
    """
    묶음 → 사고 구조. LLM 없이.
      단계  : 묶음에서 먼저 들어온 결 / 나중에 들어온 결
      갈래  : 이미 갈리고 있는 판정 분포 (후보/격리/거부)
      이름  : 대표 낱말
    """
    rows, texts = cluster["rows"], cluster["texts"]

    # 갈래 — 지어내지 않고 실제 분포를 쓴다
    dist = Counter(r.get("status") for r in rows)
    total = sum(dist.values()) or 1
    share = {k: v / total for k, v in dist.items()}
    spread = max(share.values()) - min(share.values()) if len(share) > 1 else 0.0
    if len(share) < 2 or spread < MIN_SPREAD:
        return None            # 갈리지 않는다면 사고가 아니라 절차다

    # 단계 — 들어온 순서로 앞/뒤를 가른다
    order = sorted(range(len(rows)), key=lambda i: str(rows[i].get("seen_at") or ""))
    half = max(1, len(order) // 2)
    early = _words([texts[i] for i in order[:half]])
    late = _words([texts[i] for i in order[half:]])
    if not early or not late:
        return None

    head = [w for w, _ in early.most_common(3)]
    # 뒤 단계는 앞과 다른 낱말로. 같은 말이면 두 단계가 한 일이 된다.
    tail = [w for w, _ in late.most_common(6) if w not in head[:1]][:3] \
        or [w for w, _ in late.most_common(3)]
    name_word = (early + late).most_common(1)[0][0]

    label = {"candidate": "받아들임", "quarantine": "미뤄둠", "reject": "물리침"}
    branches = []
    for st, sh in sorted(share.items(), key=lambda kv: -kv[1])[:3]:
        branches.append({
            "name": label.get(st, st),
            "directive": (f"{name_word} 쪽 이야기를 {label.get(st, st)}. "
                          f"지금까지 이 묶음의 {sh:.0%}가 이 길로 갔다."),
            "weight": round(sh, 3)})

    return {
        "type_id": f"local_{_slug(name_word)}",
        "name_word": name_word,
        "steps": [
            {"name": f"{head[0]} 살피기",
             "directive": f"{', '.join(head)} 쪽에서 무엇이 걸리는지 먼저 본다."},
            {"name": f"{tail[0]} 견주기",
             "directive": f"살핀 것을 {', '.join(tail)} 와 견주어 어느 쪽인지 가른다."},
        ],
        "branches": branches,
        "evidence": {"n": len(rows), "cohesion": round(cluster["cohesion"], 3),
                     "spread": round(spread, 3)},
    }


def _slug(w: str) -> str:
    import hashlib
    if re.fullmatch(r"[A-Za-z0-9_]+", w or ""):
        return w.lower()
    return "t" + hashlib.sha1((w or "").encode()).hexdigest()[:6]


NAME_SYSTEM = """아래는 이미 만들어진 사고 구조다. 구조는 바꾸지 마라.
읽기 좋은 이름 하나와, 한 줄 설명만 붙여라.

- 이름은 영문 소문자 사고방식 (예: source_weighing). 주제 이름 금지.
- 설명은 한국어 한 문장.

JSON 하나만: {"type_id":"...", "summary":"..."}"""


def name_it(design: dict, api_key=None, log=print) -> dict:
    """LLM 은 여기서만 쓴다 — 이름 짓기. 실패해도 구조는 그대로 산다."""
    if not api_key:
        return design
    try:
        import json
        import os
        from openai import OpenAI
        c = OpenAI(api_key=api_key)
        body = ("단계: " + " → ".join(s["name"] for s in design["steps"])
                + "\n갈래: " + ", ".join(b["name"] for b in design["branches"])
                + f"\n중심 낱말: {design.get('name_word')}")
        r = c.chat.completions.create(
            model=os.environ.get("OPENAI_NAME_MODEL", "gpt-4o-mini"),
            temperature=0.3, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": NAME_SYSTEM},
                      {"role": "user", "content": body}])
        d = json.loads(r.choices[0].message.content)
        tid = str(d.get("type_id", "")).strip()
        if re.fullmatch(r"[a-z][a-z0-9_]{2,30}", tid):
            design["type_id"] = tid
        design["summary"] = d.get("summary", "")
    except Exception as e:
        log(f"  이름 짓기 실패(구조는 그대로): {str(e)[:60]}")
    return design


def grow(sb, registry, api_key=None, log=print):
    """묶음 하나 → 구조 → (이름) → 등록. 조건이 안 되면 아무것도 안 한다."""
    cluster = find_cluster(sb)
    if not cluster:
        return {"made": None, "why": "묶음이 아직 안 모임"}
    design = design_from_cluster(cluster)
    if not design:
        return {"made": None, "why": "갈래가 갈리지 않음"}
    design = name_it(design, api_key, log=log)

    tid = registry.create_from_design(
        design, design.get("name_word", ""),
        reason=f"지도에서 모인 묶음 {design['evidence']['n']}건")
    if not tid:
        why = ""
        for c in reversed(getattr(registry, "creation_log", []) or []):
            if c.get("skipped"):
                why = c.get("reason") or c.get("merged_into") or ""
                break
        log(f"  사고 틀 거부됨: {why or '까닭 미기록'}")
        return {"made": None, "why": why or "거부됨", "design": design}
    if tid:
        # 갈래 확률을 실제 분포로 (지어낸 값이 아니라 지금까지의 경험)
        try:
            t = registry.trees[tid]
            last = f"{tid}_{len(design['steps']) - 1}"
            for j, b in enumerate(design["branches"][:3]):
                t.transitions.setdefault(last, {})[f"{tid}_b{j}"] = b["weight"]
            t._normalize(last)
        except Exception:
            pass
        log(f"  사고 틀 자생: {tid} "
            f"({' → '.join(s['name'] for s in design['steps'])} → "
            f"{'/'.join(b['name'] for b in design['branches'])})")
    return {"made": tid, "design": design}
