"""
belief_decay.py — 확신은 굳기만 하지 않는다.

무엇이 문제였나
  27개 구간을 재 보니 확신이 약해진 사실이 **0건**이었다.
  연속성이 좋다는 뜻이기도 하지만, 뒤집으면 **한 번 1.0 이 되면 영영
  안 내려간다**는 뜻이다. 그건 기억이 아니라 고정이다.

  사람은 그렇지 않다. 오래 안 꺼낸 것은 흐려지고, 어긋나는 것을 만나면
  흔들리고, 다시 확인하면 또렷해진다.

어떻게 줄어드나 (셋)
  1. 묵힘    오래 안 쓰인 사실은 천천히 옅어진다. 다만 바닥이 있다 —
             아주 사라지지는 않는다.
  2. 어긋남  새로 들어온 것이 기존 사실과 부딪히면 **둘 다** 깎인다.
             어느 쪽이 맞는지 아직 모르는 상태이기 때문이다.
  3. 못 꺼냄 말해야 할 자리에서 못 꺼냈거나 틀리게 말했다면 깎인다.

무엇은 천천히 옅어지나 (출처가 무게를 정한다)
  사람이 직접 말한 것 > 승인된 관측 > 검색 자료 > 추론
  선생님이 말씀하신 것을 몰랑이가 잊어버리면 안 되므로,
  user 출처는 아주 느리게, 바닥도 높게 둔다.
"""
from __future__ import annotations
import math
import re
import time

# 출처별 (반감 일수, 바닥) — 클수록 오래 간다
BY_SOURCE = {
    "user":      (180.0, 0.55),   # 사람이 직접 말한 것 — 거의 안 지운다
    "peer":      (90.0, 0.35),    # 피우피우에게 들은 것
    "travel":    (120.0, 0.45),   # 직접 겪은 것
    "search":    (45.0, 0.20),    # 찾아본 자료
    "inference": (30.0, 0.15),    # 스스로 미룬 것
}
DEFAULT = (60.0, 0.25)

CONFLICT_CUT = 0.12       # 어긋났을 때 양쪽이 깎이는 폭
MISS_CUT = 0.08           # 꺼내야 할 자리에서 못 꺼냈을 때
USE_GAIN = 0.10           # 꺼내 쓰면 다시 굳는 폭
USE_MAX = 1.0
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")


def _days_since(iso: str) -> float:
    if not iso:
        return 0.0
    try:
        from datetime import datetime, timezone
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return max(0.0, (time.time() - t.timestamp()) / 86400)
    except Exception:
        return 0.0


def faded(strength: float, source: str, last_seen: str,
          used_recently: bool = False) -> float:
    """
    묵은 만큼 옅어진 확신. 최근에 쓰였으면 거의 안 옅어진다.
    바닥 아래로는 내려가지 않는다 — 한 번 안 것이 완전히 사라지진 않는다.
    """
    half, floor = BY_SOURCE.get(source or "", DEFAULT)
    days = _days_since(last_seen)
    # 최근에 쓰였거나 일주일 안쪽이면 그대로 둔다.
    # touch() 가 updated_at 을 갱신하므로, 자주 꺼내는 기억은 여기서 걸러진다.
    if used_recently or days < 7:
        return float(strength)
    # 반감기 곡선. 바닥까지만 내려간다.
    k = 0.5 ** ((days - 7) / half)
    return round(max(floor, floor + (float(strength) - floor) * k), 3)


# **여럿일 수 있는 것** — 하나로 정해지지 않는 서술.
# "바다를 무서워한다" 와 "곤충을 무서워한다" 는 둘 다 참일 수 있다.
# 예전에는 이런 것도 모순으로 보고 멀쩡한 기억을 깎았다.
MULTI = re.compile(
    r"(좋아한|싫어한|무서워한|관심|궁금|자주|가끔|때때로|보고 싶|"
    r"듣는다|먹는다|읽는다|만든다|한다|산다|다닌다)")

# **하나뿐인 것** — 바뀌면 앞의 것이 틀린 게 되는 서술.
SINGLE = re.compile(
    r"(이름은|나이는|사는 곳|산다|살고 있|주로|가장|제일|태어난|"
    r"직업은|전공은|다니는)")


# 서로 반대인 말 — 같은 대상에 대해 이러면 모순이다.
# "겁이 많다" 와 "겁이 많지 않다" 는 둘 다 참일 수 없다.
OPPOSITE = [
    (re.compile(r"(겁이 많|무서워하|두려워하)(?!지 않|지는 않)"),
     re.compile(r"(겁이 많지 않|무서워하지 않|안 무서워|두려워하지 않)")),
    (re.compile(r"좋아한(?!다고|지 않)"), re.compile(r"(좋아하지 않|싫어한)")),
    (re.compile(r"관심이 (많|있)"), re.compile(r"관심이 (없|적)")),
    (re.compile(r"(잘 안|모른)"), re.compile(r"(잘 알|안다)")),
]


def _subject(text: str) -> str:
    """누구에 대한 말인가 — 첫 이름."""
    m = re.match(r"\s*([가-힣A-Za-z]{2,10})(?:은|는|이|가|도)\s", text or "")
    return m.group(1) if m else ""


def _opposed(a: str, b: str) -> bool:
    """같은 대상에 대해 정반대로 말하는가."""
    if _subject(a) != _subject(b) or not _subject(a):
        return False
    for pos, neg in OPPOSITE:
        if (pos.search(a) and neg.search(b)) or (neg.search(a) and pos.search(b)):
            return True
    return False


def conflicts(new_text: str, facts: list, min_overlap=2) -> list:
    """
    새로 들어온 것과 **정말로** 부딪히는 기존 사실들.

    조심할 것: 여럿일 수 있는 것은 모순이 아니다.
      "바다를 무서워한다" + "곤충을 무서워한다"  → 둘 다 참일 수 있다
      "바다가 보이는 집에 산다" + "산이 보이는 집에 산다" → 하나만 참이다

    그래서 **하나뿐인 서술**일 때만 부딪힘으로 본다. 그래도 확실하지 않으니
    지우지 않고 양쪽 다 조금 깎는다.
    """
    nw = set(TOKEN.findall(new_text or ""))
    if len(nw) < min_overlap:
        return []

    out = []
    # 1) 같은 대상에 대해 **정반대로** 말하는 것은 언제나 모순이다.
    #    ("피우피우가 겁이 많다" ↔ "피우피우가 겁이 많지 않다")
    for f in facts:
        if _opposed(new_text or "", f.get("text", "")):
            out.append({"id": f.get("id"), "text": f.get("text", ""),
                        "shared": ["반대"], "strength": f.get("strength")})
    if out:
        return out

    # 2) 그 밖에는 **하나뿐인 서술**일 때만 따진다.
    #    "바다를 무서워한다" 와 "곤충을 무서워한다" 는 둘 다 참일 수 있다.
    if MULTI.search(new_text or "") and not SINGLE.search(new_text or ""):
        return []
    if not SINGLE.search(new_text or ""):
        return []

    for f in facts:
        t = f.get("text", "")
        if not SINGLE.search(t):
            continue
        if MULTI.search(t) and not SINGLE.search(t):
            continue
        fw = set(TOKEN.findall(t))
        shared = nw & fw
        if len(shared) < min_overlap:
            continue
        diff_new = nw - shared
        diff_old = fw - shared
        if diff_new and diff_old and not (diff_new & diff_old):
            out.append({"id": f.get("id"), "text": t,
                        "shared": sorted(shared)[:4],
                        "strength": f.get("strength")})
    return out


def apply_conflict(sb, new_text: str, facts: list, log=print) -> dict:
    """
    부딪힌 양쪽을 **둘 다** 깎는다. 어느 쪽이 맞는지 아직 모르니까.
    이렇게 두면 나중에 한쪽이 다시 확인될 때 자연히 갈린다.
    """
    hit = conflicts(new_text, facts)
    if not hit:
        return {"n": 0}
    done = []
    for h in hit[:3]:
        try:
            new_s = max(0.1, float(h.get("strength") or 0.6) - CONFLICT_CUT)
            sb.table("molang_facts").update(
                {"strength": new_s}).eq("id", h["id"]).execute()
            done.append((h["text"][:34], round(new_s, 2)))
        except Exception:
            pass
    if done:
        log("  어긋나서 확신이 내려감: "
            + " · ".join(f"{t}({s})" for t, s in done))
    return {"n": len(done), "lowered": done}


def touch(sb, facts: list, log=None) -> int:
    """
    **꺼내 쓰면 다시 굳는다.**

    옅어지기만 하고 굳는 길이 없으면 오래 둔 것은 모두 흐려진다.
    사람도 자주 꺼내는 기억은 또렷해진다 — 쓰임이 곧 되새김이다.
    (대화에 실제로 들어간 사실에만 적용한다)
    """
    n = 0
    for f in (facts or [])[:12]:
        fid = f.get("id")
        old = float(f.get("strength") or 0)
        if not fid or old >= USE_MAX:
            continue
        new = round(min(USE_MAX, old + USE_GAIN), 3)
        try:
            sb.table("molang_facts").update(
                {"strength": new}).eq("id", fid).execute()
            n += 1
        except Exception:
            pass
    if n and log:
        log(f"  꺼내 써서 다시 굳은 사실 {n}건")
    return n


# ── 아주 오래 잠든 것은 재운다 ──────────────────────────────
SLEEP_BELOW = 0.25        # 이보다 흐려졌고
SLEEP_DAYS = 90           # 이만큼 안 쓰였으면
SLEEP_MAX = 20            # 한 번에 이만큼까지만 (한꺼번에 비우지 않는다)


def sleep_old(sb, log=print) -> dict:
    """
    **흐려진 채로 오래 잊힌 것은 잠든다.**

    옅어지기(faded)에는 바닥이 있다. 완전히 사라지지 않게 하려고
    그렇게 두었다. 그런데 바닥에 닿은 채 몇 달이 지난 것까지 계속
    목록에 남으면, 읽어오는 자리만 차지하고 새 기억이 밀려난다.

    지우지는 않는다. strength 를 0 으로 두면 molang_facts_active
    뷰에서 빠질 뿐, 기록은 남는다. **무엇을 잊었는지** 나중에 볼 수 있다.

    사람이 승인한 것(trust='human')은 건드리지 않는다.
    그건 이 아이가 기댈 바닥이다.
    """
    try:
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc)
               - timedelta(days=SLEEP_DAYS)).isoformat()
        rows = (sb.table("molang_facts").select("id,text,strength,trust")
                .lt("strength", SLEEP_BELOW).lt("updated_at", old)
                .neq("trust", "human").gt("strength", 0)
                .limit(SLEEP_MAX).execute().data) or []
    except Exception as e:
        return {"slept": 0, "why": str(e)[:60]}

    slept = []
    for r in rows:
        try:
            sb.table("molang_facts").update(
                {"strength": 0.0}).eq("id", r["id"]).execute()
            slept.append((r.get("text") or "")[:40])
        except Exception:
            pass
    if slept:
        log(f"  🌙 오래 잊힌 기억 {len(slept)}건이 잠들었다")
    return {"slept": len(slept), "examples": slept[:3]}


def sweep(sb, limit=400, log=print) -> dict:
    """
    밤에 한 번. 묵은 사실의 확신을 옅게 한다.
    출처에 따라 속도가 다르다 — 사람이 말한 것은 거의 그대로 둔다.
    """
    try:
        rows = (sb.table("molang_facts")
                .select("id,text,strength,source,updated_at,seen")
                .gt("strength", 0.1).limit(limit).execute().data) or []
    except Exception as e:
        return {"error": str(e)[:80]}

    changed = 0
    examples = []
    for r in rows:
        old = float(r.get("strength") or 0)
        new = faded(old, r.get("source"), r.get("updated_at"))
        if new < old - 0.005:
            try:
                sb.table("molang_facts").update(
                    {"strength": new}).eq("id", r["id"]).execute()
                changed += 1
                if len(examples) < 3:
                    examples.append((r.get("text", "")[:30], old, new))
            except Exception:
                pass
    if changed:
        log(f"  묵어서 옅어진 사실 {changed}건"
            + ("  " + " · ".join(f"{t} {a:.2f}→{b:.2f}" for t, a, b in examples)
               if examples else ""))
    return {"faded": changed, "checked": len(rows), "examples": examples}


def describe(sb) -> str:
    """지금 확신 분포 — 한쪽에 몰려 있지 않은지 보려면."""
    try:
        rows = (sb.table("molang_facts").select("strength")
                .limit(500).execute().data) or []
    except Exception:
        return ""
    if not rows:
        return ""
    s = [float(r.get("strength") or 0) for r in rows]
    bands = {"확신(≥0.8)": 0, "보통(0.5~0.8)": 0, "흐릿(0.2~0.5)": 0,
             "거의 잊음(<0.2)": 0}
    for v in s:
        if v >= 0.8:
            bands["확신(≥0.8)"] += 1
        elif v >= 0.5:
            bands["보통(0.5~0.8)"] += 1
        elif v >= 0.2:
            bands["흐릿(0.2~0.5)"] += 1
        else:
            bands["거의 잊음(<0.2)"] += 1
    return " · ".join(f"{k} {v}" for k, v in bands.items())
