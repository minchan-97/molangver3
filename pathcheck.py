"""
pathcheck.py — **꺼낸 근거가 답에 쓰였나.**

왜 이렇게 바뀌었나
  처음에는 **단계의 지시문과 답이 닿는지**를 쟀다. 그게 틀렸다.

    단계: "관심 있는 주제에 대한 정보를 확인한다"   ← 절차를 말한다
    답:   "바다가 오렌지색이라 아름다워"            ← 내용을 말한다

  둘 다 멀쩡한데 낱말이 겹칠 이유가 없다. 지시문은 **어떻게 할지**
  를, 답은 **무엇을** 말하기 때문이다. 글자로는 못 잰다.

  더 나쁜 것은, 지시문을 일반화하자 점수가 **0.26 에서 0.00 으로
  떨어졌다**는 점이다. 소재가 박혀 있을 때는 "음악과 출근" 이 답에도
  나와 가끔 닿았는데, 일반화하니 절차 낱말만 남아 영영 안 닿았다.
  **측정이 개선을 손해로 읽은 것이다.**

무엇을 재나
  **꺼낸 근거가 답에 쓰였는가.**

    근거: "사용자는 바다를 보면 시원하거나 추억에 잠기는 편이다"
    답:   "바다 보면 시원하지? 나도 그래"
                   ↑ 닿는다

  둘 다 **내용**이라 견줄 수 있다. 그리고 이것이야말로 묻고 싶었던
  것에 가깝다 — "기억을 꺼내 놓고 정말 그걸 보고 말했나".

못 재는 것은 분명히
  이것은 **근거를 쓴 정도**이지 '절차를 따랐는가' 가 아니다.
  절차 준수는 글자로 잴 수 없다 — 그건 뜻의 문제다.
  그러니 이 숫자를 '사고 계보가 참이다' 의 증거로 쓰면 안 된다.
  쓸 수 있는 말은 **"꺼낸 근거가 답에 얼마나 반영되었나"** 다.
"""
from __future__ import annotations
import re

TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")

# 어디에나 나오는 말 — 닿았는지 세는 데 쓸모가 없다
_BLAND = {
    "사용자", "몰랑이", "피우피우", "그것", "이것", "저것", "무엇",
    "있다", "없다", "한다", "하는", "된다", "같다", "그런", "이런",
    "그리고", "하지만", "그래서", "지금", "요즘", "오늘", "정말",
    "너무", "조금", "아주", "그래", "것을", "것이", "것은", "거야",
    "대해", "대한", "통해", "위해", "따라", "라고", "라는", "알게",
}

_JOSA = re.compile(r"(은|는|이|가|을|를|의|에|도|만|과|와|로|으로|에게|"
                   r"에서|부터|까지|라는|이라는|에선|한테|께서|이나)$")


def _stem(w: str) -> str:
    if len(w) <= 2:
        return w
    c = _JOSA.sub("", w)
    return c if len(c) >= 2 else w


def _words(t: str) -> set:
    out = set()
    for w in TOKEN.findall(t or ""):
        s = _stem(w)
        if s not in _BLAND and len(s) >= 2:
            out.add(s)
    return out


def _sources_of(result: dict) -> list:
    """이번에 꺼낸 근거들."""
    rec = (result or {}).get("record")
    src = list(getattr(rec, "sources", None) or [])
    if src:
        return src
    return list((result or {}).get("sources") or [])


def score(answer: str, sources: list) -> dict:
    """
    **꺼낸 근거가 답에 얼마나 쓰였나.** 0~1.

    근거마다 따로 본다. 하나도 안 쓰였으면 기억을 꺼내 놓고
    딴 데서 답한 것이다.
    """
    srcs = [s for s in (sources or []) if str(s).strip()]
    if not srcs:
        return {"n": 0, "hit": 0, "score": None, "why": "꺼낸 근거가 없다"}

    aw = _words(answer)
    if not aw:
        return {"n": len(srcs), "hit": 0, "score": 0.0, "why": "답이 비었다"}

    hits, detail = 0, []
    for s in srcs[:8]:
        sw = _words(str(s))
        if not sw:
            continue
        shared = aw & sw
        # 한 낱말만 겹치는 것은 우연일 수 있다
        ok = len(shared) >= 2
        hits += 1 if ok else 0
        detail.append({"source": str(s)[:70],
                       "touched": sorted(shared)[:5]})

    n = max(1, len([s for s in srcs[:8] if _words(str(s))]))
    val = round(hits / n, 3)
    return {"n": n, "hit": hits, "score": val, "detail": detail,
            "answer_words": sorted(aw)[:12],
            "why": ("근거를 보고 말했다" if val >= 0.5
                    else "꺼낸 근거가 답에 안 보인다" if val == 0
                    else "일부만 쓰였다")}


def record(sb, result: dict, answer: str, log=None) -> dict:
    """
    재고 **남긴다.** 고치지 않는다.

    답을 다시 만들라고 하지 않는다. 재서 남겨야 나중에
    "꺼낸 근거가 얼마나 쓰이는가" 를 말할 수 있다.
    """
    if not result:
        return {}
    r = score(answer, _sources_of(result))
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
        log(f"  🧭 꺼낸 근거가 답에 거의 안 보임 ({r['score']})")
    return r


def summary(sb, limit: int = 400) -> dict:
    """**꺼낸 근거가 얼마나 쓰이는가.** 논문에 쓸 숫자다."""
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
        "썼음": round(sum(1 for v in vals if v >= 0.5) / len(vals), 3),
        "안씀": round(sum(1 for v in vals if v == 0) / len(vals), 3),
        "유형별": {k: round(sum(v) / len(v), 3)
                  for k, v in sorted(by.items(),
                                     key=lambda kv: -len(kv[1]))[:6]},
    }


def describe(s: dict) -> str:
    if not s.get("n"):
        return "[근거] 아직 잰 것이 없다"
    return (f"[근거] {s['n']}건 · 꺼낸 근거가 답에 쓰인 정도 {s['평균']} · "
            f"보고 말한 것 {s['썼음']:.0%} · 안 쓴 것 {s['안씀']:.0%}")
