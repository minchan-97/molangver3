"""
registry_store.py — 사고 트리(판단 구조)를 Supabase에 보관한다.

왜 필요한가
  molang_store 는 '무엇을 아는가'(사실·기억)를 서버로 옮겼지만,
  '어떻게 판단하는가'(유형별 트리와 전이 확률)는 여전히 메모리에만 있었다.
  그러면 앱을 새로고침할 때마다 대화로 자란 구조가 사라진다.
  전이 확률이 대화로 조금씩 바뀌는 것이 이 시스템의 핵심이므로,
  그 변화가 남지 않으면 나머지도 의미가 옅어진다.

저장 형태
  molang_registry(id=1, blob bytea) 에 트리 전체를 한 덩어리로.
  트리는 노드·전이 확률·기억이라 pickle 이 자연스럽다.
  (사실/에피소드처럼 행 단위로 볼 일이 없다)

쓰는 법
  registry_store.load_into(sb, u.registry)     # 앱 시작할 때
  registry_store.save(sb, u.registry)          # 대화 한 번 끝날 때마다
"""
from __future__ import annotations
import base64
import pickle

from tree_registry import TreeRegistry
from thought_structure import ThoughtStructure, JudgmentNode, PathRecord


def _blob(registry: TreeRegistry) -> bytes:
    return pickle.dumps({
        "trees": {tid: TreeRegistry._tree_blob(t)
                  for tid, t in registry.trees.items()},
        "type_examples": getattr(registry, "type_examples", {}),
        "usage_count": getattr(registry, "usage_count", {}),
        # 생성 기록이 빠지면 '무엇이 자동으로 생긴 유형인지'를 잊는다.
        # 그러면 시들기가 고를 대상이 없어 영원히 아무것도 안 줄어든다.
        "creation_log": getattr(registry, "creation_log", []),
        # 구조 판정기도 함께 — 배운 것이 남아야 다음 판정이 나아진다
        "logic_scorer": (registry.logic_scorer.blob()
                         if getattr(registry, "logic_scorer", None) else None),
    })


def save(sb, registry: TreeRegistry):
    """
    트리를 서버에 저장.

    molang_registry.blob 은 bytea 다. REST 로 보낼 때는 base64 가 아니라
    Postgres 의 hex 표기('\\x' + hex)여야 한다. base64 를 보내면 거부당하는데,
    예전 판은 그 실패를 조용히 삼켜서 **트리가 한 번도 저장되지 않았다.**
    (사고유형 사용 횟수가 계속 0이던 원인)

    반환: {"ok": bool, "error": str|None, "bytes": int}
    """
    try:
        raw = _blob(registry)
        data = "\\x" + raw.hex()
        sb.table("molang_registry").upsert(
            {"id": 1, "blob": data}, on_conflict="id").execute()
        return {"ok": True, "error": None, "bytes": len(raw)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "bytes": 0}


def load_into(sb, registry: TreeRegistry) -> int:
    """
    서버에 저장된 트리를 registry 에 복원. 돌려주는 값은 복원된 유형 수.
    서버가 비어 있으면 0 (처음 실행 — logic_db 기본 유형만 있는 상태).
    """
    try:
        res = sb.table("molang_registry").select("blob").eq("id", 1) \
                .limit(1).execute()
        rows = getattr(res, "data", None) or []
        if not rows or not rows[0].get("blob"):
            return 0
        raw = rows[0]["blob"]
        if isinstance(raw, str):
            if raw.startswith("\\x"):          # postgres bytea hex 표기
                raw = bytes.fromhex(raw[2:])
            else:
                raw = base64.b64decode(raw)
        blob = pickle.loads(raw)
    except Exception:
        return 0

    # 필드가 안 맞아도 트리를 통째로 버리지 않는다.
    #
    # PathRecord 에 at_probs·seed 를 더한 뒤, 그 필드가 없는 옛 기록에서
    # PathRecord(**r) 이 터지면서 **트리 18개가 조용히 사라진 일**이 있었다
    # (41개 → 23개. 남은 23개는 logic_db 기본형뿐이었다).
    # 기록 하나가 깨졌다고 그 트리의 사고 구조까지 버릴 이유는 없다.
    import dataclasses as _dc
    _fields = {f.name for f in _dc.fields(PathRecord)}

    def _rec(d):
        try:
            return PathRecord(**{k: v for k, v in d.items() if k in _fields})
        except Exception:
            return None

    n = 0
    skipped_hist = 0
    for tid, tb in (blob.get("trees") or {}).items():
        try:                      # TreeRegistry.load() 의 복원 절차와 같게
            t = ThoughtStructure(learning_rate=tb.get("lr", 0.1),
                                 continuity=tb.get("continuity", 0.5))
            for k, v in (tb.get("nodes") or {}).items():
                try:
                    t.nodes[k] = JudgmentNode(**v)
                except Exception:
                    continue
            t.transitions = tb.get("transitions") or {}
            t.root_id = tb.get("root_id")
            hist = [_rec(x) for x in (tb.get("history") or [])]
            skipped_hist += sum(1 for x in hist if x is None)
            t.history = [x for x in hist if x is not None]
            t.memory = tb.get("memory", [])
            if not t.nodes:          # 노드가 하나도 없으면 트리가 아니다
                continue
            registry.trees[tid] = t
            n += 1
        except Exception as e:
            print(f"  ⚠️ 트리 '{tid}' 복원 실패: {str(e)[:60]}")
            continue
    if skipped_hist:
        print(f"  (옛 형식 경로 기록 {skipped_hist}건은 건너뜀 — 트리는 살림)")
    if blob.get("type_examples"):
        registry.type_examples = blob["type_examples"]
    if blob.get("usage_count"):
        registry.usage_count = blob["usage_count"]
    if blob.get("creation_log"):
        registry.creation_log = blob["creation_log"]
    if blob.get("logic_scorer"):
        try:
            from logic_check import TinyScorer
            registry.logic_scorer = TinyScorer.load(blob["logic_scorer"])
        except Exception:
            pass
    return n

