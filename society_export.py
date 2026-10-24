"""
society_export.py — **사회의 성장 기록.** 몰랑이 것과 따로 뽑는다.

왜 따로인가
  몰랑이 pkl 은 **한 개체가 어떻게 자랐나**를 담는다.
  그런데 이제 이웃들이 서로 만나고, 관심이 옮고, 다 같이 무엇을
  지을지 정한다. 그건 **개체의 성장이 아니라 사회의 성장**이다.

  한 파일에 섞으면 둘 다 흐려진다. 그래서 나눈다.

무엇을 담나
  구성원   각자의 관심·기억·사이·어디 사는가
  마주침   누가 누구와 어디서
  떠도는 말 무엇이 번지고 있나
  모임     무엇을 짓자고 했고 몇 대 몇이었나
  마을     지금까지 생긴 곳들

무엇을 보려고
  "서로가 어떻게 성숙해지고 관계를 맺으며 성장하느냐."
  그래서 **관계와 결정**을 중심에 둔다. 양이 아니라.
"""
from __future__ import annotations
import time


def collect(sb) -> dict:
    out = {"at": time.time(), "kind": "society"}

    try:
        import villagers as _vp
        out["villagers"] = _vp.load(sb)
    except Exception as e:
        out["villagers"] = {"_error": str(e)[:60]}

    try:
        import pinko as _pk
        out["pinko"] = _pk.load(sb)
    except Exception:
        pass

    try:
        import village as _vg
        out["village"] = _vg.load(sb)
    except Exception:
        pass

    try:
        import society as _sc
        s = _sc.load(sb)
        out["society"] = s
        out["councils"] = (s.get("councils") or [])[-20:]
    except Exception:
        pass

    try:
        import bonds as _bd
        out["bonds"] = _bd.load(sb)
    except Exception:
        pass

    out["meta"] = summarize(out)
    return out


def summarize(out: dict) -> dict:
    """**관계와 결정**을 센다. 사실 수 같은 양이 아니라."""
    who = out.get("villagers") or {}
    pk = out.get("pinko") or {}
    s = out.get("society") or {}
    b = out.get("bonds") or {}
    cs = out.get("councils") or []

    # 누가 누구와 얼마나 가까운가
    warm = [float(v.get("warmth") or 0) for v in b.values()
            if isinstance(v, dict)]
    # 서로를 아는 사이가 몇 쌍인가 (몰랑이를 거치지 않는 것도 포함)
    pairs = [v.get("who") for v in b.values() if isinstance(v, dict)]
    peer_pairs = [p for p in pairs
                  if p and "molang" not in p and "몰랑이" not in p]

    return {
        "사람": len(who) + len([1 for v in pk.values()
                                if isinstance(v, dict) and v.get("known")]),
        "마을": len((out.get("village") or {}).get("places") or {}),
        "마주침": len(s.get("meets") or []),
        "떠도는말": sum(len(v) for v in (s.get("rumors") or {}).values()),
        "사이": len(b),
        "이웃끼리사이": len(peer_pairs),
        "평균가까움": round(sum(warm) / len(warm), 3) if warm else 0.0,
        "모임": len(cs),
        "지은곳": len([c for c in cs if c.get("picked")]),
    }


def report(out: dict) -> str:
    m = out.get("meta") or {}
    lines = [f"[사회] 사람 {m.get('사람')}명 · 마을 {m.get('마을')}곳",
             f"  마주침 {m.get('마주침')}번 · 떠도는 말 {m.get('떠도는말')}개",
             f"  사이 {m.get('사이')}쌍 (몰랑이 없이 맺은 것 "
             f"{m.get('이웃끼리사이')}쌍) · 평균 {m.get('평균가까움')}",
             f"  모임 {m.get('모임')}번 · 다 같이 지은 곳 {m.get('지은곳')}곳"]
    for c in (out.get("councils") or [])[-3:]:
        if c.get("picked"):
            t = c.get("tally") or [("", 0, 0)]
            lines.append(f"    · {c['picked']} ({t[0][1]}:{t[0][2]})")
    return "\n".join(lines)
