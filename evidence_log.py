"""
evidence_log.py — **이번에 무엇을 꺼내 보고 말했나.** 점수는 안 매긴다.

왜 점수를 안 매기나
  처음에는 '꺼낸 근거가 답에 쓰였나' 를 낱말 겹침으로 쟀다.
  그런데 대놓고 정보를 묻지 않으면 근거가 아예 안 딸려 오고,
  와도 답과 글자가 겹칠 이유가 없다. 그걸 0 으로 세면 **없는
  결함을 있다고 말하는 셈**이다.

  앞서 단계의 지시문으로 쟀을 때도 같은 일을 겪었다. 지시문을
  일반화하자 점수가 0.26 에서 0.00 으로 떨어졌는데, 그건 개선을
  손해로 읽은 것이었다. **두 번 같은 실수를 할 이유가 없다.**

  그래서 재지 않는다. **보이게만 한다.**

무엇을 하나
  대화마다 "이번엔 이걸 꺼내 봤다" 를 남긴다.
  사람이 눈으로 보고 "이건 엉뚱한데" 를 알아채면 그것으로 족하다.

  숫자가 필요해지면 그때 **무엇을 셀지 먼저 정하고** 만든다.
  셀 것을 정하기 전에 세는 일은 하지 않는다.
"""
from __future__ import annotations
import time


def sources_of(result: dict) -> list:
    """이번에 꺼낸 근거들."""
    rec = (result or {}).get("record")
    src = list(getattr(rec, "sources", None) or [])
    if src:
        return src
    return list((result or {}).get("sources") or [])


def note(result: dict, answer: str = "") -> dict:
    """
    이번 대화에서 **무엇을 꺼내 봤나.** 화면에 그대로 보여줄 것.
    """
    srcs = [str(s).strip() for s in sources_of(result) if str(s).strip()]
    return {
        "type": (result or {}).get("type"),
        "path": list((result or {}).get("path") or []),
        "sources": srcs[:8],
        "n": len(srcs),
        "at": time.time(),
    }


def record(sb, result: dict, answer: str = "", log=None) -> dict:
    """남긴다. 나중에 되짚어 볼 수 있게."""
    n = note(result, answer)
    if not n.get("type"):
        return n
    try:
        sb.table("molang_evidence").insert({
            "type_id": n["type"],
            "path": n["path"],
            "sources": n["sources"],
            "n_sources": n["n"],
        }).execute()
    except Exception:
        pass
    if log and n["n"] == 0:
        log("  📎 꺼낸 근거 없이 답함")
    return n


def recent(sb, limit: int = 20) -> list:
    """최근 대화들이 무엇을 꺼내 봤나."""
    try:
        return (sb.table("molang_evidence")
                .select("type_id,path,sources,n_sources,created_at")
                .order("id", desc=True).limit(limit).execute().data) or []
    except Exception:
        return []


def describe(rows: list) -> str:
    """세지 않고, 있는 그대로."""
    if not rows:
        return "아직 기록이 없어요"
    with_src = sum(1 for r in rows if (r.get("n_sources") or 0) > 0)
    return (f"최근 {len(rows)}번 중 근거를 꺼낸 것 {with_src}번 "
            f"(나머지는 꺼낼 것이 없었어요)")
