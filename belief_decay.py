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
    if used_recently or days < 7:
        return float(strength)
    # 반감기 곡선. 바닥까지만 내려간다.
    k = 0.5 ** ((days - 7) / half)
    return round(max(floor, floor + (float(strength) - floor) * k), 3)


def conflicts(new_text: str, facts: list, min_overlap=2) -> list:
    """
    새로 들어온 것과 부딪히는 기존 사실들.
    같은 것을 말하는데 **끝이 다르면** 부딪힌 것으로 본다.
    (완벽한 판정은 못 한다. 그래서 지우지 않고 '양쪽 다 깎는다'.)
    """
    nw = set(TOKEN.findall(new_text or ""))
    if len(nw) < min_overlap:
        return []
    out = []
    for f in facts:
        t = f.get("text", "")
        fw = set(TOKEN.findall(t))
        shared = nw & fw
        if len(shared) < min_overlap:
            continue
        # 주어·주제는 겹치는데 서술이 다르다 → 부딪힘
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
