"""
curiosity_growth.py — 호기심이 '아는 것'만 늘리지 않고 '판단하는 방식'을 바꾼다.

지금까지의 끊긴 고리
  호기심 루프 → 관측 저장(organism_observations) → 끝.
  사고 트리는 대화로만 바뀌었다. 검색으로 아무리 많이 알아도
  판단 구조는 그대로였다. 지식 축적이지 진화가 아니다.

여기서 잇는 세 갈래

  1. 근거 기억 (feed_tree_memory)
     승인된 관측을 그 주제와 맞는 트리의 기억으로 넣는다.
     다음에 같은 주제를 판단할 때 그 트리가 이 근거를 맥락으로 쓴다.
     → 같은 질문이라도 아는 게 늘면 답이 달라진다.

  2. 판단 단계 깊어지기 (deepen)
     한 주제를 여러 번 파고들어 근거가 쌓이면, 그 트리에 판단 단계를
     하나 더 붙인다. "그냥 답한다" → "무엇이 알려졌나 → 무엇이 아직 모르나
     → 답한다" 처럼 구조가 깊어진다.
     기준: 그 트리의 기억이 임계치를 넘고, 최근 경로가 늘 같을 때
     (같은 길만 반복한다 = 더 나눌 여지가 있다)

  3. 새 사고 유형 (propose_type)
     기존 어느 유형으로도 잘 안 풀리는 주제 무리가 쌓이면,
     LLM에게 새 사고 단계를 설계하게 하고 트리를 만든다.
     tree_registry 의 과생성 방지(상한 12개, 화제성 이름 거부)를 그대로 따른다.

원칙
  · 구조 변경은 드물어야 한다. 매번 바뀌면 그건 구조가 아니다.
  · 변경은 기록에 남는다 (registry.creation_log / 감사 로그).
  · 사람이 승인한 관측만 근거가 된다. 격리된 것은 들어가지 않는다.
"""
from __future__ import annotations
import os

MEM_TO_DEEPEN = 8          # 트리 기억이 이만큼 쌓이면 단계 하나 더
SAME_PATH_RUNS = 5         # 최근 경로가 이만큼 연속 같으면 나눌 여지가 있다
MAX_DEPTH_ADD = 3          # 한 트리에 이 이상은 안 깊어진다


def _topic_tree(registry, topic: str, embed_fn=None, classify_fn=None):
    """주제에 가장 가까운 트리. 없으면 None."""
    try:
        tid = registry.classify_type(topic, embed_fn=embed_fn,
                                     classify_fn=classify_fn)
    except Exception:
        tid = None
    if not tid or tid not in registry.trees:
        return None, None
    return tid, registry.trees[tid]


def feed_tree_memory(sb, registry, limit=20, embed_fn=None, classify_fn=None,
                     log=print):
    """
    1) 승인된 관측(status='candidate')을 주제에 맞는 트리의 기억으로.
    반환: {'fed': n, 'trees': [...]}
    """
    try:
        rows = (sb.table("organism_observations")
                .select("id,topic,title,text,url,status,fed")
                .eq("status", "candidate")
                .order("id", desc=True).limit(limit).execute().data) or []
    except Exception as e:
        return {"fed": 0, "error": str(e)}

    fed, touched = 0, set()
    for r in rows:
        if r.get("fed"):
            continue
        topic = r.get("topic") or ""
        tid, tree = _topic_tree(registry, topic, embed_fn, classify_fn)
        if tree is None:
            continue
        body = f"[{topic}] {(r.get('title') or '')} — {(r.get('text') or '')[:300]}"
        try:
            ok = tree.remember(body, trust=0.6, context=topic)
        except Exception:
            ok = False
        if ok:
            fed += 1
            touched.add(tid)
            try:                      # 같은 관측을 두 번 먹이지 않는다
                sb.table("organism_observations").update(
                    {"fed": True}).eq("id", r["id"]).execute()
            except Exception:
                pass
    if fed:
        log(f"  근거 → 사고 기억 {fed}건 ({', '.join(sorted(touched))})")
    return {"fed": fed, "trees": sorted(touched)}


def deepen(registry, log=print):
    """
    2) 근거가 쌓였는데 늘 같은 길만 지나는 트리에 판단 단계를 하나 더 붙인다.
    반환: 깊어진 트리 목록
    """
    from thought_structure import JudgmentNode
    grown = []
    for tid, t in list(registry.trees.items()):
        if len(getattr(t, "memory", [])) < MEM_TO_DEEPEN:
            continue
        added = sum(1 for n in t.nodes if str(n).startswith("grown_"))
        if added >= MAX_DEPTH_ADD:
            continue
        hist = [tuple(r.path) for r in getattr(t, "history", [])[-SAME_PATH_RUNS:]]
        if len(hist) < SAME_PATH_RUNS or len(set(hist)) != 1:
            continue          # 길이 갈리고 있으면 아직 나눌 필요 없다

        # 마지막 판단 앞에 '아직 모르는 것을 짚는' 단계를 끼운다
        path = list(hist[0])
        if len(path) < 2:
            continue
        before, last = path[-2], path[-1]
        nid = f"grown_{tid}_{added + 1}"
        node = JudgmentNode(
            id=nid,
            prompt="아는 것과 모르는 것 가르기",
            directive=("지금까지 알아낸 근거로 말할 수 있는 것과, 아직 근거가 "
                       "없어 모른다고 해야 하는 것을 먼저 나눈 뒤 답한다."))
        try:
            t.add_node(node)
            t.add_branch(before, nid, prob=0.5)
            t.add_branch(nid, last, prob=1.0)
            t._normalize(before)
            grown.append(tid)
            log(f"  사고 단계 추가: {tid} (기억 {len(t.memory)}건)")
        except Exception:
            continue
    return grown


NEW_TYPE_SYSTEM = """너는 한 존재의 사고 구조를 설계한다.
아래 주제들을 다룰 때 필요한 '사고 방식'을 3~4단계로 설계하라.
주제 이름이 아니라 사고 방식이어야 한다 (예: '비교하기'는 되고 '음식'은 안 됨).
JSON 하나만: {"type_id":"영문_소문자_사고방식", "steps":[{"name":"단계 이름","directive":"이 단계에서 실제로 할 일"}]}"""


def propose_type(registry, topics, api_key=None, model=None, log=print):
    """
    3) 기존 유형으로 안 풀리는 주제 무리 → 새 사고 유형 설계.
    registry.create_from_design 의 안전장치(상한·화제성 거부)를 그대로 탄다.
    """
    if not topics or not api_key:
        return None
    try:
        from openai import OpenAI
        import json
        c = OpenAI(api_key=api_key)
        r = c.chat.completions.create(
            model=model or os.environ.get("OPENAI_CURIOSITY_MODEL", "gpt-4o-mini"),
            temperature=0.5, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": NEW_TYPE_SYSTEM},
                      {"role": "user", "content": "주제들: " + ", ".join(topics[:8])}])
        design = json.loads(r.choices[0].message.content)
    except Exception as e:
        log(f"  새 사고 유형 설계 실패: {e}")
        return None
    tid = registry.create_from_design(design, ", ".join(topics[:3]),
                                      reason="호기심이 모은 주제 무리")
    if tid:
        log(f"  새 사고 유형: {tid}")
    return tid


def run(sb, registry, state=None, api_key=None, embed_fn=None, classify_fn=None,
        log=print):
    """세 갈래를 한 번에. 워커가 호출한다."""
    out = {}
    out["memory"] = feed_tree_memory(sb, registry, embed_fn=embed_fn,
                                     classify_fn=classify_fn, log=log)
    out["deepened"] = deepen(registry, log=log)
    # 관심은 큰데 어느 트리로도 안 잡히는 주제들 → 새 유형 후보
    if state is not None:
        orphan = []
        for t, w in sorted((state.interests or {}).items(),
                           key=lambda kv: -kv[1])[:12]:
            tid, tree = _topic_tree(registry, t, embed_fn, classify_fn)
            if tree is None and w >= 0.3:
                orphan.append(t)
        if len(orphan) >= 3:
            out["new_type"] = propose_type(registry, orphan, api_key, log=log)
    return out
