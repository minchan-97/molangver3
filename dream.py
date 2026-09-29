"""
dream.py — 밤에 꾸는 꿈.

세 재료를 엮었다
  프로이트(freud_unconscious)  낮에 쌓인 충동이 임계를 넘으면 격리된다.
                               그 압력이 빠지는 자리가 꿈이다.
  확률 구름(prob_cloud)        온도를 올리면 한 노드가 아니라 여러 노드로
                               퍼진다. **꿈은 온도를 높인 상태**다.
                               깨어 있을 땐 temp 낮음(한 점으로 붕괴),
                               꿈에선 temp 높음(여러 기억이 겹침).
  호프필드(hopfield_boundary)  정체성에서 얼마나 멀어졌나를 에너지로 잰다.
                               너무 멀리 가면 깬다.

무엇이 꿈이 되나 (낮에 못 다룬 것들 — 프로이트식 '잔재')
  · 격리된 것 (확신 못 해 미뤄둔 사실)
  · 거부된 관측 (가드가 쳐낸 것)
  · 오래 안 꺼낸 기억 (reminisce)
  · 못 푼 구멍 (궁금한데 답을 못 찾은 것)

꿈의 규칙
  · 꿈은 **사실이 되지 않는다.** 따로 저장되고, 승인 대상도 아니다.
    깨어 있을 때 통과 못 한 것이 자는 사이에 사실이 되면 그건 오염이다.
  · 다만 꿈에서 자주 나온 것은 **관심으로만** 조금 옮겨간다.
    (낮에 못 푼 것이 다음 날 신경 쓰이는 것)
  · 정체성 에너지가 너무 높으면 그 꿈은 버린다 — 악몽에서 깨듯이.
  · 아침에 "이런 꿈을 꿨어"로 말을 걸 수 있다.
"""
from __future__ import annotations
import math
import os
import random
import re
import time

DRIVE_ALPHA = 0.25        # 충동이 쌓이는 속도 (미처리량에 비례)
DRIVE_BETA = 0.30         # 처리하면 빠지는 속도
DREAM_THRESHOLD = 0.45    # 이 이상 쌓여야 꿈을 꾼다
TEMP = 2.2                # 꿈의 온도 (깨어 있을 때는 0.3 안팎)
MAX_ENERGY = 1.8          # 정체성에서 이만큼 벗어나면 깬다
KEEP = 60                 # 꿈 기록 보관 수
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")


# ── 낮에 쌓인 압력 ───────────────────────────────────────────
def _drive_step(state, H: float, L: float) -> float:
    """
    충동은 한 회차의 값이 아니라 **쌓이는 양**이다.
    (직접 만드신 freud_unconscious 의 step 을 그대로 쓴다.
     alpha 만큼 엔트로피로 오르고, beta 만큼 소화로 빠진다)
    """
    try:
        from freud_unconscious import FreudUnconscious
        fu = FreudUnconscious(p0=float(getattr(state, "drive", 0.0) or 0.0),
                              alpha=DRIVE_ALPHA, beta=DRIVE_BETA,
                              threshold=0.85)
        drive, _q = fu.step(H, L)
    except Exception:
        drive = max(0.0, min(1.0, float(getattr(state, "drive", 0.0) or 0.0)
                             + DRIVE_ALPHA * H - DRIVE_BETA * L))
    if state is not None:
        state.drive = round(drive, 4)
    return drive


def pressure(sb, identity, state=None) -> dict:
    """
    미처리량 → 충동. 프로이트 모듈의 step() 과 같은 꼴이되,
    entropy 자리에 '아직 소화 못 한 것의 비율'을 넣는다.
    """
    pend = rejected = 0
    try:
        r = (sb.table("organism_observations").select("id", count="exact")
             .eq("status", "quarantine").execute())
        pend = r.count or 0
        r2 = (sb.table("organism_observations").select("id", count="exact")
              .eq("status", "reject").execute())
        rejected = r2.count or 0
    except Exception:
        pass
    unsure = 0
    try:
        unsure = sum(1 for f in identity.learned_facts
                     if 0.2 < (f.get("strength") or 0) < 0.6)
    except Exception:
        pass

    # 거부한 것은 **이미 끝난 일**이다. 예전에는 rejected * 0.3 을 더해서
    # 거부가 쌓일수록 압력이 영원히 안 빠졌다(75건이면 소화해도 0.8 언저리).
    # 소화할 방법이 없는 것을 압력으로 세면 안 된다.
    raw = pend * 1.0 + unsure * 0.6
    H = 1.0 - math.exp(-raw / 12.0)        # 소화 못 한 양 (엔트로피)

    # 소화한 양 — **이번 회차에** 소화한 것만 센다.
    # 누적으로 세면 지금까지 먹인 게 100건일 때 소화 신호가 영원히 1.0 이 되어
    # 충동이 0 에서 올라오지 못한다 (어제 먹은 것으로 오늘 배부를 수는 없다).
    fed_now = int((state and getattr(state, "last_fed", 0)) or 0)
    L = 1.0 - math.exp(-fed_now / 4.0)

    drive = _drive_step(state, H, L) if state is not None else H
    return {"drive": round(drive, 3), "entropy": round(H, 3),
            "digest": round(L, 3), "pending": pend,
            "rejected": rejected, "unsure": unsure}


# ── 꿈 재료 ──────────────────────────────────────────────────
def _residue(sb, identity, state, limit=12) -> list[dict]:
    """낮에 못 다룬 것들 — 꿈의 재료."""
    out = []
    try:
        rows = (sb.table("organism_observations")
                .select("id,topic,title,text,status")
                .in_("status", ["quarantine", "reject"])
                .order("id", desc=True).limit(limit).execute().data) or []
        for r in rows:
            out.append({"kind": r.get("status"),
                        "text": (r.get("title") or r.get("text") or "")[:90],
                        "topic": r.get("topic")})
    except Exception:
        pass
    try:
        import reminisce
        for f in reminisce.pick(list(identity.learned_facts),
                                getattr(state, "interests", {}), n=3):
            out.append({"kind": "old", "text": (f.get("text") or "")[:90],
                        "topic": reminisce.to_topic(f)})
    except Exception:
        pass
    for t in list((getattr(state, "interests", {}) or {}))[:5]:
        out.append({"kind": "interest", "text": t, "topic": t})
    return out


# ── 겹치기 (온도를 높인 상태) ────────────────────────────────
def _blend(residue: list[dict], rng, temp=TEMP) -> list[dict]:
    """
    확률 구름의 발상: 온도가 높으면 한 점이 아니라 여러 곳이 동시에 켜진다.
    꿈에서는 서로 관계없는 기억이 한 장면에 겹친다.
    """
    if len(residue) < 2:
        return residue[:1]
    n = min(len(residue), max(2, int(round(1 + temp))))
    weights = [1.0 + rng.random() * temp for _ in residue]
    picked, pool = [], list(zip(weights, residue))
    for _ in range(n):
        if not pool:
            break
        tot = sum(w for w, _ in pool)
        r = rng.random() * tot
        acc = 0
        for i, (w, item) in enumerate(pool):
            acc += w
            if acc >= r:
                picked.append(item)
                pool.pop(i)
                break
    return picked


# ── 정체성에서 얼마나 멀어졌나 ───────────────────────────────
def _drift(pieces: list[dict], identity) -> float:
    """
    호프필드 에너지의 취지만 빌린다: 정체성(확신한 사실들)과
    꿈 조각이 얼마나 겹치는가. 안 겹칠수록 멀리 간 꿈.
    """
    try:
        # 조사 때문에 '파스타를' 과 '파스타' 가 안 겹친다 → 어간(앞 두 글자)으로
        stem = lambda ws: {w[:2] for w in ws if len(w) >= 2}
        core = set()
        for f in identity.learned_facts:
            if (f.get("strength") or 0) >= 0.6:      # 확신에 가까운 것들
                core |= stem(TOKEN.findall(f.get("text") or ""))
        core -= {"사용", "찬기", "그는", "한다", "있다"}
        if not core:
            return 0.0
        words = set()
        for p in pieces:
            words |= stem(TOKEN.findall(p.get("text") or ""))
        if not words:
            return 2.0
        overlap = len(core & words) / max(1, len(words))
        return round(2.0 * (1.0 - overlap), 3)
    except Exception:
        return 0.0


def _linger(pieces: list[dict], identity, rng) -> str | None:
    """
    겹친 조각들 중 무엇이 깨어난 뒤까지 남나.

    두 가지를 곱한다 (둘 다 로컬 계산).
      얽힘  다른 조각들과 얼마나 이어져 있나 — 혼자 동떨어진 건 안 남는다
      낯섦  이미 아는 것과 얼마나 다른가 — 익숙한 건 남을 이유가 없다
    그래서 '여러 갈래에 걸쳐 있으면서 아직 내 것이 아닌' 낱말이 남는다.
    """
    cands = []
    for p in pieces:
        for w in TOKEN.findall(p.get("text") or ""):
            cands.append(w)
        if p.get("topic"):
            cands.append(str(p["topic"]))
    try:
        from organism.curiosity import (_is_topic_like, strip_josa, canon_name,
                                        TALK_WORDS)
        cleaned = []
        for w in cands:
            w = canon_name(strip_josa(w))
            # 관심사와 같은 잣대로 거른다. 안 그러면 '담긴', '있는' 같은
            # 활용형이 꿈에서 남아 관심으로 올라간다.
            if not _is_topic_like(w) or w in TALK_WORDS:
                continue
            if len(w) < 2 or w.endswith(("긴", "는", "던", "들")):
                continue
            cleaned.append(w)
        cands = cleaned
    except Exception:
        cands = [w for w in cands if 2 <= len(w) <= 8]
    cands = list(dict.fromkeys(cands))
    if not cands:
        return None

    try:
        import numpy as np
        from organism.embedder import hashed_embedding as emb
        V = np.array([emb(w, dim=64) for w in cands])
        tangle = (V @ V.T).mean(axis=1)            # 얽힘

        known = [f.get("text", "") for f in getattr(identity, "learned_facts", [])
                 if (f.get("strength") or 0) >= 0.6][:40]
        if known:
            K = np.array([emb(t, dim=64) for t in known])
            strange = 1.0 - (V @ K.T).max(axis=1)  # 낯섦
        else:
            strange = np.ones(len(cands))

        score = tangle * (0.4 + 0.6 * strange)
        score = score + rng.random() * 0.05        # 같은 게 계속 남지 않게
        order = np.argsort(-score)[:5]
        # 왜 그 낱말이 남았는지 되짚을 수 있게 후보와 점수를 함께 돌려준다.
        # (pieces 에는 주제만 찍혀서, 본문에서 올라온 낱말은 출처를 알 수 없었다)
        why = [{"word": cands[i], "score": round(float(score[i]), 3),
                "tangle": round(float(tangle[i]), 3),
                "strange": round(float(strange[i]), 3)} for i in order]
        return cands[int(order[0])], why
    except Exception:
        return rng.choice(cands), []


DREAM_SYSTEM = """너는 몰랑이(흰 토끼)가 꾼 꿈을 적는다.

- 아래 조각들이 한 장면에 **겹쳐서** 나타난 꿈이다. 논리적으로 잇지 마라.
  꿈은 앞뒤가 안 맞는다.
- 2~3문장. 과거형. "나는 …" 으로.
- 사실을 주장하지 마라. 꿈이다.
- 마지막에 깨어난 뒤의 느낌 한 조각만.

JSON 하나만: {"dream":"...", "feeling":"한 낱말", "lingering":"꿈에서 남은 낱말 하나"}"""


def dream(sb, identity, state, api_key=None, log=print) -> dict:
    """한 밤의 꿈. 조건이 안 되면 안 꾼다."""
    p = pressure(sb, identity, state)
    if p["drive"] < DREAM_THRESHOLD:
        return {"slept": True, "dreamed": False,
                "why": f"압력이 낮음({p['drive']})", **p}

    rng = random.Random(time.time_ns())
    residue = _residue(sb, identity, state)
    if len(residue) < 2:
        return {"slept": True, "dreamed": False, "why": "꿈 재료가 부족"}

    pieces = _blend(residue, rng)
    energy = _drift(pieces, identity)
    if energy > MAX_ENERGY:
        return {"slept": True, "dreamed": False,
                "why": f"정체성에서 너무 멀어 깼다(에너지 {energy})"}

    # ── 무엇이 남을까: **로컬이 정한다** ──
    # 예전에는 LLM 이 쓴 장면에서 lingering 을 골랐다. 그러면 꿈에서 나온
    # 관심의 출처가 바깥 모델이 된다. 여기서는 겹친 조각들 중
    # '가장 얽혀 있고 가장 낯선' 것을 로컬 계산으로 고른다.
    lingering, linger_why = _linger(pieces, identity, rng)
    text = feeling = None
    if api_key:
        try:
            import json
            from openai import OpenAI
            c = OpenAI(api_key=api_key)
            body = "\n".join(f"- [{x['kind']}] {x['text']}" for x in pieces)
            r = c.chat.completions.create(
                model=os.environ.get("OPENAI_DREAM_MODEL", "gpt-4o-mini"),
                temperature=1.0, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": DREAM_SYSTEM},
                          {"role": "user", "content": body}])
            d = json.loads(r.choices[0].message.content)
            text, feeling = d.get("dream"), d.get("feeling")
            # lingering 은 로컬이 정한 것을 쓴다 (LLM 값은 버린다)
        except Exception as e:
            log(f"  꿈 적기 실패: {e}")
    if not text:                       # LLM 없이도 꿈은 꾼다 (조각만 남는다)
        text = " … ".join(x["text"][:30] for x in pieces)
        feeling = "묘함"

    entry = {"at": time.time(), "text": text, "feeling": feeling,
             "lingering": lingering, "energy": energy, "drive": p["drive"],
             "pieces": [x.get("topic") or x["text"][:20] for x in pieces],
             "piece_texts": [x.get("text", "")[:70] for x in pieces],
             "linger_why": linger_why}

    dreams = list(getattr(state, "dreams", []) or [])
    dreams.append(entry)
    state.dreams = dreams[-KEEP:]

    # 꿈에 남은 것은 '관심'으로만 조금 옮겨간다. 사실이 되지는 않는다.
    bumped = []
    try:
        from organism.curiosity import _is_topic_like, strip_josa
        cands = [lingering] if lingering else []
        cands += [x.get("topic") for x in pieces if x.get("topic")]
        for t in cands[:2]:
            t = strip_josa(str(t or ""))
            if t and _is_topic_like(t):
                old = float(state.interests.get(t, 0.0))
                state.interests[t] = max(0.0, min(5.0, old + 0.06))
                bumped.append(t)
    except Exception:
        pass

    try:
        sb.table("molang_dreams").insert({
            "text": text[:800], "feeling": feeling,
            "lingering": lingering, "energy": energy,
            "drive": p["drive"], "pieces": entry["pieces"],
            "linger_why": linger_why}).execute()
    except Exception as e:
        log(f"  꿈 저장 실패: {str(e)[:80]}")

    log(f"  꿈: {str(text)[:60]} (느낌 {feeling}, 에너지 {energy})")
    if linger_why:
        log("    남은 낱말 후보: " + " · ".join(
            f"{x['word']}({x['score']})" for x in linger_why[:3]))
    return {"slept": True, "dreamed": True, "dream": entry, "bumped": bumped}


def recent(sb, limit=5) -> list[dict]:
    try:
        return (sb.table("molang_dreams").select("*")
                .order("id", desc=True).limit(limit).execute().data) or []
    except Exception:
        return []
