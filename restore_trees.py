#!/usr/bin/env python3
"""
사라진 사고 유형을 성장 기록(pkl)에서 되살린다.

왜 필요했나
  PathRecord 에 필드를 더한 뒤, 그 필드가 없는 옛 경로 기록에서
  PathRecord(**r) 이 터지면서 **트리가 통째로 버려졌다.**
  41개가 23개로 줄었고, 남은 23개는 전부 logic_db 기본형이었다.
  대화에서 자란 18개(inquiry, response, recommendation, storytelling …)가
  사라진 것이다.

무엇을 하나
  pkl 에 남아 있는 트리 중 **지금 서버에 없는 것만** 되살린다.
  이미 있는 것은 건드리지 않는다 (지금 것이 더 최신이므로).

쓰는 법
  python scripts/restore_trees.py /path/몰랑이57.pkl          # 미리보기
  python scripts/restore_trees.py /path/몰랑이57.pkl --write  # 실제 복원
"""
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from thought_structure import ThoughtStructure, JudgmentNode, PathRecord
from tree_registry import TreeRegistry, load_logic_db_types
import registry_store


def tree_from_blob(tb: dict):
    """pkl 안의 트리 하나를 되살린다. 깨진 기록은 건너뛰되 트리는 살린다."""
    import dataclasses as dc
    fields = {f.name for f in dc.fields(PathRecord)}
    t = ThoughtStructure(learning_rate=tb.get("lr", 0.1),
                         continuity=tb.get("continuity", 0.5))
    for k, v in (tb.get("nodes") or {}).items():
        try:
            t.nodes[k] = JudgmentNode(**v)
        except Exception:
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
    return t if t.nodes else None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    write = "--write" in sys.argv

    with open(path, "rb") as fp:
        snap = pickle.load(fp)
    saved = {k: v for k, v in (snap.get("trees") or {}).items()
             if isinstance(v, dict)}
    print(f"기록에 든 사고 유형: {len(saved)}개  ({os.path.basename(path)})")

    from molang_store import SupabaseIdentity
    sb = SupabaseIdentity(None).sb if hasattr(SupabaseIdentity, "sb") else None
    if sb is None:
        from supabase import create_client
        sb = create_client(os.environ["SUPABASE_URL"],
                           os.environ["SUPABASE_SERVICE_KEY"])

    reg = TreeRegistry()
    load_logic_db_types(reg, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "logic_db.json"))
    n = registry_store.load_into(sb, reg)
    print(f"지금 서버에 있는 유형: {len(reg.trees)}개 (복원 {n}개)")

    missing = [k for k in saved if k not in reg.trees]
    print(f"\n되살릴 유형 {len(missing)}개:")
    for k in missing:
        tb = saved[k]
        print(f"   {k:28} 노드 {len(tb.get('nodes') or {}):>2} · "
              f"기억 {len(tb.get('memory') or []):>3} · "
              f"경로 {len(tb.get('history') or []):>3}")

    if not missing:
        print("\n되살릴 것이 없습니다.")
        return
    if not write:
        print("\n(미리보기입니다. 실제로 복원하려면 --write 를 붙이세요)")
        return

    ok = 0
    for k in missing:
        t = tree_from_blob(saved[k])
        if t:
            reg.trees[k] = t
            ok += 1
    res = registry_store.save(sb, reg)
    print(f"\n{ok}개를 되살려 저장했습니다 → 총 {len(reg.trees)}개"
          + ("" if res.get("ok") else f"  ⚠️ 저장 실패: {res.get('error')}"))


if __name__ == "__main__":
    main()
