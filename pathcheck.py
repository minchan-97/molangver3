"""
pathcheck.py — **답이 그 길을 정말 걸었나.**

왜 필요했나
  사고 계보는 "어느 갈림길에서 어디로 갔는가" 를 남긴다. 그런데
  그걸 남긴 뒤에 LLM 이 말한다. **LLM 이 그 경로를 정말 따랐는지는
  아무도 확인하지 않았다.**

  그러면 계보가 '사고의 기록' 이 아니라 **'사고하는 척의 기록'** 이
  될 수 있다. 경로는 남았는데 답은 딴 데서 왔다면, 추적이 된다는
  말이 성립하지 않는다.

  이것이 지금 구조에서 가장 약한 자리다. 다른 것은 다 재면서
  **정작 계보가 참인지는 안 쟀다.**

무엇을 재나
  걸은 단계들의 **지시문과 답이 얼마나 닿아 있는가.**

    따름   단계가 다루라고 한 것을 답이 다루었다
    벗어남 단계와 상관없는 말을 했다

  LLM 에게 묻지 않는다. 물으면 "따랐습니다" 라고 할 테니,
  그건 또 한 겹의 자기 보고일 뿐이다. **낱말이 닿았는지를 센다.**

무엇을 못 재나
  이것은 **일치**를 재지 인과를 재지 못한다. 답이 우연히 비슷할
  수도 있다. 다만 **반대는 분명하다** — 닿는 데가 하나도 없으면
  그 경로를 따랐다고 보기 어렵다.
"""
from __future__ import annotations
import re

TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")

# 어느 지시문에나 나오는 말 — 닿았는지 세는 데 쓸모가 없다
_BLAND = {"무엇", "어떤", "그것", "이것", "먼저", "다음", "그리고",
          "본다", "보고", "한다", "하는", "있다", "없다", "것을", "것이",
          "답하", "말하", "생각", "살펴", "경우", "때는", "이를", "여기",
          "대해", "대한", "통해", "위해", "따라", "만약", "하지만"}


# 조사를 떼지 않으면 '감정' 과 '감정이' 가 다른 말이 되어,
# 같은 것을 다루었는데도 안 닿았다고 세어진다.
_JOSA = re.compile(r"(은|는|이|가|을|를|의|에|도|만|과|와|로|으로|에게|"
                   r"에서|부터|까지|라는|이라는|이나|든지)$")


def _stem(w: str) -> str:
    if len(w) <= 2:
        return w
    cut = _JOSA.sub("", w)
    return cut if len(cut) >= 2 else w


def _words(t: str) -> set:
    out = set()
    for w in TOKEN.findall(t or ""):
        s = _stem(w)
        if s not in _BLAND and len(s) >= 2:
            out.add(s)
    return out


def _step_texts(tree, path: list) -> list:
    """걸은 단계들의 이름과 지시문."""
    out = []
    nodes = getattr(tree, "nodes", {}) or {}
    for step in (path or []):
        key = step[0] if isinstance(step, (list, tuple)) else step
        node = nodes.get(key)
        if node is None:
            out.append(str(key))
            continue
        # JudgmentNode 는 prompt(판단의 이름)와 **directive**(실제
        # 강제되는 지시)를 가진다. 전에는 directive 를 안 읽어서,
        # 영어 id 만 남아 한국어 답과 영영 안 닿았다 (3건 전부 0.00).
        # 실제로 답을 통제하는 것은 directive 쪽이다.
        bits = []
        for attr in ("prompt", "directive", "name", "label",
                     "instruction", "desc", "text"):
            v = getattr(node, attr, None)
            if v is None and isinstance(node, dict):
                v = node.get(attr)
            if v:
                bits.append(str(v))
        # 한글이 하나도 없으면 id 라도 넣는다 (영어 유형)
        if not bits:
            bits = [str(key)]
        out.append(" ".join(bits))
    return out


def score(answer: str, tree, path: list) -> dict:
    """
    답이 걸은 길에 얼마나 닿아 있나. 0~1.

    단계마다 따로 본다. **한 단계라도 닿으면** 그 길을 걸은
    흔적이 있는 것이고, 전부 안 닿으면 딴 데서 온 답이다.
    """
    steps = _step_texts(tree, path)
    if not steps:
        return {"n": 0, "hit": 0, "score": None, "why": "걸은 길이 없다"}

    aw = _words(answer)
    if not aw:
        return {"n": len(steps), "hit": 0, "score": 0.0, "why": "답이 비었다"}

    hits, detail = 0, []
    for s in steps:
        sw = _words(s)
        if not sw:
            continue
        shared = aw & sw
        ok = bool(shared)
        hits += 1 if ok else 0
        detail.append({"step": s.split()[0], "touched": sorted(shared)[:4]})

    n = max(1, len([s for s in steps if _words(s)]))
    val = round(hits / n, 3)
    return {"n": n, "hit": hits, "score": val, "detail": detail,
            "why": ("길을 따랐다" if val >= 0.5
                    else "길과 답이 거의 안 닿는다" if val == 0
                    else "일부만 닿는다")}


def record(sb, result: dict, answer: str, log=None) -> dict:
    """
    재고 **남긴다.**

    고치지 않는다. 답을 다시 만들라고 하지 않는다.
    이것은 계보가 참인지를 재는 자리이지, 답을 손보는 자리가 아니다.
    남아야 나중에 "계보가 얼마나 믿을 만한가" 를 말할 수 있다.
    """
    if not result:
        return {}
    r = score(answer, result.get("tree"), result.get("path"))
    if r.get("score") is None:
        return r
    try:
        sb.table("molang_pathcheck").insert({
            "type_id": result.get("type"),
            "steps": r["n"], "touched": r["hit"],
            "score": r["score"],
            "detail": r.get("detail") or [],
        }).execute()
    except Exception:
        pass
    if log and r["score"] < 0.34:
        log(f"  🧭 답이 걸은 길과 거의 안 닿음 ({r['score']})")
    return r


def summary(sb, limit: int = 400) -> dict:
    """
    **계보가 얼마나 믿을 만한가.** 논문에 쓸 숫자다.

    경로 추적률 1.0 은 '경로가 남았나' 를 뜻할 뿐이다.
    이것은 '그 경로가 답과 닿아 있나' 를 뜻한다. 다른 질문이다.
    """
    try:
        rows = (sb.table("molang_pathcheck")
                .select("type_id,score").order("id", desc=True)
                .limit(limit).execute().data) or []
    except Exception:
        return {"n": 0}
    if not rows:
        return {"n": 0}
    vals = [float(r.get("score") or 0) for r in rows]
    by = {}
    for r in rows:
        by.setdefault(r.get("type_id") or "?", []).append(
            float(r.get("score") or 0))
    return {
        "n": len(vals),
        "평균": round(sum(vals) / len(vals), 3),
        "따름": round(sum(1 for v in vals if v >= 0.5) / len(vals), 3),
        "안닿음": round(sum(1 for v in vals if v == 0) / len(vals), 3),
        "유형별": {k: round(sum(v) / len(v), 3)
                  for k, v in sorted(by.items(),
                                     key=lambda kv: -len(kv[1]))[:6]},
    }


def describe(s: dict) -> str:
    if not s.get("n"):
        return "[계보] 아직 잰 것이 없다"
    return (f"[계보] {s['n']}건 · 길과 닿은 정도 {s['평균']} · "
            f"따른 것 {s['따름']:.0%} · 안 닿은 것 {s['안닿음']:.0%}")
