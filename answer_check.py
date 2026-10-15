"""
answer_check.py — **나온 말을 검사하고, 못 미더우면 다시 부른다.**

왜 필요했나
  피우피우 대화에서 "오늘 몰랑이의 생일이었대!" 가 나왔다. 몰랑이에게는
  생일이 없다. 주제가 '몰랑이' 였는데 할 말이 마땅치 않자 LLM 이
  빈칸을 메운 것이다. 그럴듯해서 그냥 지나갔고, 사실로 쌓일 뻔했다.

  프롬프트로 "지어내지 마라" 라고 적어두는 것만으로는 안 막힌다.
  **나온 뒤에 재는 자리**가 있어야 한다.

세 가지를 잰다
  근거   답에 나온 구체적인 것이 **꺼낸 근거 안에** 있나
  자리   답의 핵심 낱말이 **의미 지도에 자리**를 가졌나
  끌림   그 낱말들이 서로 **끌리는 사이**인가 (중력)

  셋을 곱해 확신으로 본다. 낮으면 **두 번까지 다시 부른다.**
  그래도 낮으면 쓰되 기록에 남긴다 — 숨기지 않는 쪽이 이 구조의 방식이다.

왜 곱하나
  하나만 봐도 되지만, 셋이 서로 다른 실패를 잡는다.
    근거만  → 지도에 없는 말을 놓친다
    자리만  → 아는 낱말로 지어낸 거짓을 놓친다
  곱하면 하나라도 크게 어긋날 때 전체가 내려간다.
"""
from __future__ import annotations
import re

# 이보다 낮으면 다시 부른다.
#
# 셋을 곱하므로 값이 작게 나온다. 0.45 로 두면 멀쩡한 말도 걸린다.
# 생일 건이 0.12, 근거 안에서 말한 것이 0.5 언저리였다.
RETRY_BELOW = 0.20
MAX_RETRY = 2             # 두 번까지
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")

# **구체적인 것** — 지어내면 바로 거짓이 되는 종류
CONCRETE = re.compile(
    r"(\d{1,4}[년월일시분초개번째]|\d+\.\d+|"
    r"생일|기념일|이름이|태어난|살았|죽었|결혼|졸업|출시|발매)")

# 말버릇은 내용이 아니다 — 재는 데 쓰지 않는다
FILLER = {"그래", "정말", "진짜", "너무", "아주", "조금", "그냥", "우와",
          "히힛", "그런데", "하지만", "그리고", "이렇게", "저렇게",
          "생각", "느낌", "같아", "있어", "없어", "좋아", "싶어"}


def _words(t: str) -> set:
    return {w for w in TOKEN.findall(t or "") if w not in FILLER}


def grounded(answer: str, sources: list) -> float:
    """
    답의 구체적인 것이 근거 안에 있나.

    모든 낱말을 따지지는 않는다. 말은 새로 지어내는 것이 당연하다.
    다만 **날짜·이름·사건** 같은 것은 근거에 없으면 지어낸 것이다.
    """
    text = answer or ""
    hits = CONCRETE.findall(text)
    if not hits:
        return 1.0                      # 구체적인 주장이 없으면 따질 것도 없다
    base = " ".join(str(s) for s in (sources or []))
    if not base:
        return 0.3                      # 근거 없이 구체적으로 말한다
    ok = sum(1 for h in hits if h in base)
    return round(0.3 + 0.7 * (ok / len(hits)), 3)


def placed(answer: str, gmap: dict) -> float:
    """답의 핵심 낱말이 의미 지도에 자리를 가졌나."""
    ws = list(_words(answer))[:12]
    if not ws or not gmap:
        return 1.0
    nodes = set((gmap.get("nodes") or {}))
    if not nodes:
        return 1.0
    # 말에는 지도에 없는 낱말이 섞이는 게 당연하다. 바닥을 둔다.
    known = sum(1 for w in ws if w in nodes)
    return round(0.6 + 0.4 * (known / len(ws)), 3)


def attracted(answer: str, gmap: dict, mass: dict) -> float:
    """
    답의 낱말들이 서로 끌리는 사이인가.
    멀리 떨어진 것들을 억지로 붙였으면 낮게 나온다.
    """
    ws = [w for w in _words(answer) if w in ((gmap or {}).get("nodes") or {})]
    if len(ws) < 2:
        return 1.0
    try:
        import word_gravity as WG
    except Exception:
        return 1.0
    pulls = []
    for i, a in enumerate(ws[:8]):
        for b in ws[i + 1:8]:
            try:
                pulls.append(WG.pull(gmap, mass or {}, a, b))
            except Exception:
                pass
    if not pulls:
        return 1.0
    # 중력 지도가 아직 성글면 끌림이 0 인 짝이 많다. 그걸 '억지로
    # 붙였다' 로 보면 멀쩡한 말도 걸린다. 바닥을 높게 둔다.
    near = sum(1 for p in pulls if p > 0)
    return round(0.7 + 0.3 * (near / len(pulls)), 3)


def score(answer: str, sources: list = None,
          gmap: dict = None, mass: dict = None) -> dict:
    g = grounded(answer, sources)
    p = placed(answer, gmap)
    a = attracted(answer, gmap, mass)
    conf = round(g * p * a, 3)
    why = []
    if g < 0.6:
        why.append("근거에 없는 것을 말함")
    if p < 0.6:
        why.append("모르는 낱말이 많음")
    if a < 0.6:
        why.append("서로 먼 것들을 붙임")
    return {"conf": conf, "grounded": g, "placed": p, "attracted": a,
            "why": why}


def ask_until_sure(call, sources: list = None, gmap: dict = None,
                   mass: dict = None, log=print) -> dict:
    """
    부르고, 재고, 못 미더우면 다시 부른다. **두 번까지.**

    call(hint) 은 답 문자열을 돌려주는 함수다. 두 번째부터는 무엇이
    문제였는지 hint 로 알려준다 — 같은 실수를 되풀이하지 않게.

    두 번 다시 불러도 낮으면 **그대로 쓰되 기록에 남긴다.**
    숨기고 고치는 것보다, 못 미덥다는 것을 아는 편이 낫다.
    """
    best, tries = None, []
    for n in range(MAX_RETRY + 1):
        hint = ""
        if n and best:
            hint = ("앞서 한 말에 문제가 있었다: "
                    + ", ".join(best["why"] or ["확신이 낮음"])
                    + ". 아는 것만 가지고 다시 말해라. "
                      "모르는 것은 모른다고 해라.")
        try:
            text = call(hint)
        except Exception as e:
            log(f"  답 생성 실패: {str(e)[:50]}")
            break
        if not text:
            break
        s = score(text, sources, gmap, mass)
        s["text"] = text
        tries.append(s["conf"])
        if best is None or s["conf"] > best["conf"]:
            best = s
        if s["conf"] >= RETRY_BELOW:
            if n:
                log(f"  🔁 {n}번 다시 물어 확신 {s['conf']}")
            return {**s, "retries": n, "tries": tries}

    if best:
        log(f"  ⚠️ 확신 낮은 채로 씀 ({best['conf']}) — "
            f"{', '.join(best['why']) or '이유 불명'}")
        return {**best, "retries": len(tries) - 1, "tries": tries,
                "low": True}
    return {"text": "", "conf": 0.0, "why": ["답을 못 만듦"], "low": True}
