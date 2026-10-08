"""
rehome_memory.py — **안 걸어본 길에 쌓인 근거를 옮긴다.**

왜 필요했나
  해시 임베딩이 뜻이 아니라 글자를 보는 탓에, 지시문이 영어인 기본
  유형(syllogism 등)이 한국어 주제와 엉뚱하게 가까워 보였다.
  그래서 근거 236건이 **한 번도 걸어본 적 없는 길**에 쌓였고,
  그동안 169번 쓰인 emotion_analysis 는 근거가 11건뿐이었다.

  입구는 고쳤지만(curiosity_growth._is_live), 이미 쌓인 것은 그대로다.
  버리지 않고 **쓰이는 길로 옮긴다** — 애써 모은 근거이기 때문이다.

어디로 옮기나
  주제가 남아 있으면 그에 맞는 산 유형으로, 없으면 가장 덜 배운
  산 유형으로. 한 곳에 몰리지 않게 고루 나눈다.
"""
from __future__ import annotations


def rehome(registry, log=print, dry=False) -> dict:
    import curiosity_growth as CG

    live = [k for k in registry.trees if CG._is_live(registry, k)]
    dead = [k for k in registry.trees if not CG._is_live(registry, k)]
    if not live:
        return {"moved": 0, "why": "산 유형이 없음"}

    # 받은 수를 세어가며 고른다 — 안 그러면 한 곳에 다 쏠린다
    got = {k: len(getattr(registry.trees[k], "memory", []) or []) for k in live}

    moved, from_, to_ = 0, {}, {}
    for tid in dead:
        t = registry.trees[tid]
        mem = list(getattr(t, "memory", []) or [])
        if not mem:
            continue
        for m in mem:
            # 가장 덜 배운 산 유형으로 — 한 곳에 몰리지 않게
            dst = min(live, key=lambda k: got.get(k, 0))
            got[dst] = got.get(dst, 0) + 1
            if dry:
                moved += 1
                from_[tid] = from_.get(tid, 0) + 1
                to_[dst] = to_.get(dst, 0) + 1
                continue
            try:
                txt = m.get("text") if isinstance(m, dict) else str(m)
                ctx = m.get("context") if isinstance(m, dict) else ""
                tru = m.get("trust", 0.6) if isinstance(m, dict) else 0.6
                if not txt:
                    continue
                if registry.trees[dst].remember(txt, trust=tru, context=ctx):
                    moved += 1
                    from_[tid] = from_.get(tid, 0) + 1
                    to_[dst] = to_.get(dst, 0) + 1
            except Exception:
                pass
        if not dry:
            try:
                t.memory = []
            except Exception:
                pass

    log(f"  근거 {moved}건을 산 유형으로 옮겼다")
    return {"moved": moved, "from": from_, "to": to_,
            "live": len(live), "dead": len(dead)}
