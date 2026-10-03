"""
legacy_import.py — 옛 구조(self_model)의 pkl에서 기억을 되살린다.

왜 필요했나
  기존 이전 기능은 `old.identity.learned_facts` 만 읽었다.
  그런데 예전 판 pkl 은 기억이 `self_model` 안의
  '확신하는_것' / '아직_확신못하는_것' 에 들어 있다.
  경로가 달라서 **130회 대화의 기억 61개가 통째로 건너뛰어졌다.**

들어 있는 것이 세 종류라 따로 다룬다
  1) 사용자 사실   "찬기는 대구에서 태어났다"        → 바로 사실로
  2) 몰랑이 자기 사실 "몰랑이는 당근을 좋아해"        → 사실로, 단 주어를 지킨다
                     (토끼가 자기 취향을 아는 것도 정체성이다)
  3) 대화 답변 원문  "오, 찬기야! 💖 축구 보는 걸…"   → 격리로
                     사실이 섞여 있지만(축구, 교사, 커피) 몰랑이 말투 그대로라
                     그냥 넣으면 예전의 '귀속 오류'가 되살아난다. 사람이 본다.
"""
from __future__ import annotations
import pickle
import re

EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
MOLANG_FIRST = ("몰랑이는", "몰랑이가", "나는 몰랑")
USER_FIRST = ("찬기", "사용자", "그는", "그녀는")
TALKY = ("오, ", "히힛", "! 💖", "그렇구나", "~ ")


def read(raw: bytes) -> dict:
    """pkl 바이트 → 종류별로 나눈 목록. 저장은 하지 않는다."""
    try:
        d = pickle.loads(raw)
    except Exception as e:
        return {"error": f"읽기 실패: {e}"}

    # 새 판 성장 기록(growth_export) — trees / facts 가 들어 있다.
    # 사고 유형이 유실됐을 때 **되돌리는 데 쓴다.**
    trees = {}
    if isinstance(d, dict) and isinstance(d.get("trees"), dict):
        trees = {k: v for k, v in d["trees"].items() if isinstance(v, dict)}

    sure, unsure = [], []
    if isinstance(d, dict) and d.get("facts") and not d.get("self_model"):
        # 새 판: facts 목록에서 바로
        for f in d["facts"]:
            if not isinstance(f, dict):
                continue
            (sure if (f.get("strength") or 0) >= 0.8
             else unsure).append(f.get("text") or "")
        persona = ""
        talks = (d.get("meta") or {}).get("cycle")
    elif isinstance(d, dict):
        sm = d.get("self_model") or {}
        sure = list(sm.get("확신하는_것") or [])
        unsure = list(sm.get("아직_확신못하는_것") or [])
        persona = str(sm.get("정체성") or "")
        talks = sm.get("겪어온_대화수")
    else:                      # 더 옛 구조: identity.learned_facts
        ident = getattr(d, "identity", None)
        persona = getattr(ident, "persona", "") if ident else ""
        talks = None
        for f in (getattr(ident, "learned_facts", []) or []):
            (sure if isinstance(f, dict) and (f.get("strength") or 0) >= 0.8
             else unsure).append(f.get("text") if isinstance(f, dict) else str(f))

    user_facts, self_facts, raw_answers = [], [], []
    for text, strong in [(t, True) for t in sure] + [(t, False) for t in unsure]:
        t = str(text or "").strip()
        if not t:
            continue
        looks_talk = (len(t) > 70 or EMOJI.search(t)
                      or any(k in t[:12] for k in TALKY))
        if t.startswith(MOLANG_FIRST) and not looks_talk:
            self_facts.append({"text": t, "strength": 0.9 if strong else 0.55})
        elif looks_talk:
            raw_answers.append({"text": t[:400]})
        elif t.startswith(USER_FIRST):
            user_facts.append({"text": t, "strength": 0.9 if strong else 0.55})
        else:                  # 주어가 애매하면 사람이 본다
            raw_answers.append({"text": t[:400]})

    return {"user_facts": user_facts, "self_facts": self_facts,
            "raw_answers": raw_answers, "persona": persona, "talks": talks,
            "trees": trees,
            "faces": (d.get("molang_faces") if isinstance(d, dict) else None) or {},
            "appearance": (d.get("molang_appearance")
                           if isinstance(d, dict) else None)}


def restore_trees(sb, parsed: dict, log=None) -> dict:
    """
    기록에 있는 사고 유형 중 **지금 서버에 없는 것만** 되돌린다.
    지금 있는 것은 건드리지 않는다 (서버 쪽이 더 최신이므로).

    되돌린 것에는 복구 표시를 남긴다 — 자란 것과 섞이면 안 된다.
    """
    saved = parsed.get("trees") or {}
    if not saved:
        return {"restored": 0, "why": "기록에 사고 유형이 없음"}

    import os
    import registry_store
    from tree_registry import TreeRegistry, load_logic_db_types
    from thought_structure import ThoughtStructure, JudgmentNode, PathRecord
    import dataclasses as dc

    reg = TreeRegistry()
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        load_logic_db_types(reg, os.path.join(here, "logic_db.json"))
    except Exception:
        pass
    # **서버에 실제로 있는 것**이 무엇인지 따로 센다.
    # logic_db 기본형을 깔고 나면 'general' 같은 것이 '이미 있다'로 보여
    # 서버에서 사라진 줄 모르고 건너뛴다. 그러면 거기 쌓였던 기억이
    # 영영 안 돌아온다 (실제로 10건을 잃을 뻔했다).
    probe = TreeRegistry()
    registry_store.load_into(sb, probe)
    on_server = set(probe.trees)

    registry_store.load_into(sb, reg)
    before = set(reg.trees)

    fields = {f.name for f in dc.fields(PathRecord)}
    done = []
    filled = []
    for tid, tb in saved.items():
        cur = reg.trees.get(tid)
        if cur is not None and tid in on_server:
            # 서버에 있는 것은 그대로 둔다. 다만 **기억이 비어 있고 기록에는
            # 있다면** 그 기억만 채운다 (기본형으로 다시 깔리면서 비는 경우).
            if not getattr(cur, "memory", None) and tb.get("memory"):
                cur.memory = tb["memory"]
                if not cur.history and tb.get("history"):
                    pass        # 경로는 아래 복원 절차와 같게 두지 않는다
                filled.append(tid)
            continue
        # 서버에 없으면 기본형이어도 기록에서 되살린다
        try:
            t = ThoughtStructure(learning_rate=tb.get("lr", 0.1),
                                 continuity=tb.get("continuity", 0.5))
            for k, v in (tb.get("nodes") or {}).items():
                try:
                    t.nodes[k] = JudgmentNode(**v)
                except Exception:
                    continue
            if not t.nodes:
                continue
            t.transitions = tb.get("transitions") or {}
            t.root_id = tb.get("root_id")
            hist = []
            for r in (tb.get("history") or []):
                try:
                    hist.append(PathRecord(**{k: v for k, v in r.items()
                                              if k in fields}))
                except Exception:
                    continue
            t.history = hist
            t.memory = tb.get("memory", [])
            reg.trees[tid] = t
            done.append(tid)
        except Exception:
            continue

    if not done and not filled:
        return {"restored": 0, "why": "되돌릴 것이 없음", "now": len(reg.trees)}

    # 복구 표시 — 자생과 구분되어야 한다
    import time
    try:
        reg.creation_log = list(getattr(reg, "creation_log", []) or [])
        reg.creation_log.append({
            "at": time.time(), "kind": "restored",
            "ids": done, "memory_filled": filled,
            "reason": "성장 기록에서 되돌림 (자생 아님)"})
    except Exception:
        pass

    res = registry_store.save(sb, reg)
    return {"restored": len(done), "ids": done,
            "filled": len(filled), "filled_ids": filled,
            "before": len(before), "now": len(reg.trees),
            "saved": bool(res.get("ok")), "error": res.get("error")}


def restore_paths(sb, parsed: dict) -> dict:
    """
    **지금 것을 버리지 않고** 빠진 경로 기록만 되돌린다.

    경로 기록은 '이 개체가 무엇을 어떻게 판단해왔는가' 의 흔적이다.
    자료 구조를 바꾸면서 옛 형식이 걸러져 75건이 사라졌다.
    트리·노드·기억·사실은 지금 것이 더 최신이므로 건드리지 않고,
    **기록에만 있고 지금 없는 경로**를 앞에 이어 붙인다.

    그래서 어느 쪽도 버리지 않는다.
    """
    saved = parsed.get("trees") or {}
    if not saved:
        return {"added": 0, "why": "기록에 사고 유형이 없음"}

    import os
    import dataclasses as dc
    import registry_store
    from tree_registry import TreeRegistry, load_logic_db_types
    from thought_structure import PathRecord

    reg = TreeRegistry()
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        load_logic_db_types(reg, os.path.join(here, "logic_db.json"))
    except Exception:
        pass
    registry_store.load_into(sb, reg)

    fields = {f.name for f in dc.fields(PathRecord)}

    def key(rec):
        """같은 판단인지 — 시각과 지나간 길로 본다."""
        p = rec.path if hasattr(rec, "path") else rec.get("path")
        t = rec.timestamp if hasattr(rec, "timestamp") else rec.get("timestamp")
        return (str(t), tuple(p or []))

    # 서버에 없는 트리는 기록에서 되살려서라도 경로를 지킨다.
    # (general 처럼 노드가 비어 복원에서 걸러진 트리의 경로 34건이
    #  이 때문에 안 돌아왔다)
    from thought_structure import ThoughtStructure, JudgmentNode

    added, detail = 0, {}
    for tid, tb in saved.items():
        t = reg.trees.get(tid)
        if t is None:
            try:
                t = ThoughtStructure(learning_rate=tb.get("lr", 0.1),
                                     continuity=tb.get("continuity", 0.5))
                for k, v in (tb.get("nodes") or {}).items():
                    try:
                        t.nodes[k] = JudgmentNode(**v)
                    except Exception:
                        continue
                t.transitions = tb.get("transitions") or {}
                t.root_id = tb.get("root_id")
                t.memory = tb.get("memory", [])
                t.history = []
                reg.trees[tid] = t
            except Exception:
                continue
        have = {key(r) for r in (t.history or [])}
        old = []
        for r in (tb.get("history") or []):
            try:
                rec = PathRecord(**{k: v for k, v in r.items() if k in fields})
            except Exception:
                continue
            if key(rec) in have:
                continue
            old.append(rec)
        if not old:
            continue
        # 옛 기록이 앞, 지금 기록이 뒤 — 시간 순서를 지킨다
        t.history = old + list(t.history or [])
        detail[tid] = len(old)
        added += len(old)

    if not added:
        return {"added": 0, "why": "빠진 경로가 없음"}

    import time
    try:
        reg.creation_log = list(getattr(reg, "creation_log", []) or [])
        reg.creation_log.append({
            "at": time.time(), "kind": "paths_restored",
            "detail": detail,
            "reason": "자료 구조 변경으로 걸러진 옛 경로 기록을 되돌림"})
    except Exception:
        pass

    res = registry_store.save(sb, reg)
    return {"added": added, "detail": detail,
            "saved": bool(res.get("ok")), "error": res.get("error")}


def apply(sb, identity, parsed: dict, take_persona=False) -> dict:
    """나뉜 목록을 서버에 넣는다. 답변 원문은 격리로."""
    if parsed.get("error"):
        return parsed
    added = {"user_facts": 0, "self_facts": 0, "quarantined": 0}

    for f in parsed.get("user_facts", []):
        try:
            identity._reinforce_or_add(f["text"], source="legacy")
            added["user_facts"] += 1
        except Exception:
            pass
    for f in parsed.get("self_facts", []):
        try:
            identity._reinforce_or_add(f["text"], source="legacy_self")
            added["self_facts"] += 1
        except Exception:
            pass
    for r in parsed.get("raw_answers", []):
        try:
            sb.table("molang_quarantine").insert({
                "text": r["text"],
                "reason": "옛 pkl 대화 원문 — 사실이 섞여 있어 확인 필요",
                "evidence": {"from": "legacy_pkl"}}).execute()
            added["quarantined"] += 1
        except Exception:
            pass

    if take_persona and parsed.get("persona"):
        try:
            identity.persona = parsed["persona"]
            identity.save_identity()
            added["persona"] = True
        except Exception:
            pass
    try:
        identity.reload()
    except Exception:
        pass
    return added
