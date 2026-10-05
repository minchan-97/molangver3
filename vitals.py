"""
vitals.py — 무너지고 있는지 **지켜보는** 지표.

규칙과 무엇이 다른가
  규칙(curiosity 의 필터, groundcheck)은 **들어오는 것을 막는다.**
  그런데 이상한 입력을 미리 다 적어둘 수는 없다 —
  '아무래' 를 막으면 '하고' 가, 그걸 막으면 '가지고' 가 올라온다.

  그래서 막는 일과 **번지고 있는지 재는 일**을 나눈다.
  규칙은 계속 쓰되, 여기서는 "오류가 퍼지는가, 고치면 돌아오는가" 를 본다.

무엇을 보나
  조각 점유   상위 관심에서 말 토막이 차지하는 가중치 비율
  되풀이      같은 검색·같은 알림이 반복되는 비율
  순환 출처   **같은 근원이 돌아와 다시 세어지는** 사실의 수
  회복        고친 것이 이후에도 유지되는가

언제 움직이나
  한 번의 이상은 이상이 아니다. **여러 회차에 걸쳐 높아질 때** 본다.
  그리고 전체를 되돌리는 대신 **문제가 된 항목만** 격리한다.
  원본은 남긴다 — 안 그러면 왜 그랬는지 영영 모른다.
"""
from __future__ import annotations
import re
import time

# 이 선을 여러 번 넘으면 들여다볼 때다
LIMITS = {
    "fragment_share": 0.25,   # 상위 관심의 1/4이 조각이면
    "repeat_rate": 0.5,       # 절반이 같은 것의 되풀이면
    "echo_facts": 5,          # 돌아온 사실이 이만큼이면
}
TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")


def fragment_share(interests: dict, top: int = 15) -> dict:
    """
    상위 관심에서 **말 토막**이 차지하는 비율.
    조각 하나가 생긴 건 이상이 아니다. 상위를 차지하기 시작하면 이상이다.
    """
    if not interests:
        return {"share": 0.0, "items": []}
    try:
        from organism.curiosity import _is_topic_like
    except Exception:
        return {"share": 0.0, "items": [], "skip": "필터 없음"}
    rows = sorted(interests.items(), key=lambda kv: -kv[1])[:top]
    total = sum(v for _, v in rows) or 1.0
    bad = [(k, v) for k, v in rows if not _is_topic_like(k)]
    return {"share": round(sum(v for _, v in bad) / total, 3),
            "items": [k for k, _ in bad][:6]}


def repeat_rate(sb, hours: int = 24) -> dict:
    """
    같은 것을 되풀이하고 있나.
    같은 검색어, 같은 알림이 반복되면 **갇힌 것**이다.
    """
    out = {"search": 0.0, "nudge": 0.0}
    try:
        from datetime import datetime, timezone, timedelta
        since = (datetime.now(timezone.utc)
                 - timedelta(hours=hours)).isoformat()
        rows = (sb.table("molang_outbox").select("rule,body")
                .gte("created_at", since).limit(100).execute().data) or []
        if rows:
            bodies = [r.get("body") or "" for r in rows]
            out["nudge"] = round(1 - len(set(bodies)) / len(bodies), 3)
            rules = [r.get("rule") or "" for r in rows]
            out["same_rule"] = round(
                max((rules.count(x) for x in set(rules)), default=0)
                / len(rules), 3)
    except Exception:
        pass
    try:
        from datetime import datetime, timezone, timedelta
        since = (datetime.now(timezone.utc)
                 - timedelta(hours=hours)).isoformat()
        obs = (sb.table("organism_observations").select("topic")
               .gte("seen_at", since).limit(200).execute().data) or []
        if obs:
            ts = [o.get("topic") or "" for o in obs]
            out["search"] = round(1 - len(set(ts)) / len(ts), 3)
    except Exception:
        pass
    return out


def echo_facts(sb, limit: int = 300) -> dict:
    """
    **같은 근원이 돌아와 다시 세어진 사실.**

    몰랑이가 잘못 안 것을 피우피우에게 말하고, 피우피우가 나중에
    되말하면 — 근원은 같은데 두 번 센 것이 된다. 마을까지 돌면 더 심해진다.
    독립된 확인이 아닌데 확신만 올라간다.

    지금은 출처(source)만 있고 **전달 경로**가 없어서, 글이 겹치는 것으로
    짐작한다. 완전하지는 않지만 번지는 것은 잡힌다.
    """
    try:
        rows = (sb.table("molang_facts")
                .select("id,text,source,strength,created_at")
                .order("id", desc=True).limit(limit).execute().data) or []
    except Exception:
        return {"n": 0}
    seen, echoes = {}, []
    for r in rows:
        t = (r.get("text") or "")
        core = " ".join(sorted(TOKEN.findall(t))[:5])
        if not core:
            continue
        if core in seen:
            a, b = seen[core], r
            # 출처가 다르면 '돌아온 것' 일 수 있다
            if (a.get("source") or "") != (b.get("source") or ""):
                echoes.append({
                    "text": t[:50],
                    "sources": [a.get("source"), b.get("source")],
                    "ids": [a.get("id"), b.get("id")],
                    "strength": [a.get("strength"), b.get("strength")]})
        else:
            seen[core] = r
    return {"n": len(echoes), "items": echoes[:5]}


def recovery(sb, hours: int = 72) -> dict:
    """
    고친 것이 **그 뒤에도 유지되는가.**
    사람이 '아니야' 라고 한 사실이 다시 올라오면, 고쳐도 안 돌아오는 것이다.
    """
    try:
        rows = (sb.table("molang_facts")
                .select("id,text,strength,updated_at")
                .lte("strength", 0.1).limit(50).execute().data) or []
        back = [r for r in rows if float(r.get("strength") or 0) > 0.3]
        return {"corrected": len(rows), "reverted": len(back)}
    except Exception:
        return {"corrected": 0, "reverted": 0}


def check(sb, state, log=print) -> dict:
    """한 회차의 생체 신호. 선을 넘은 것만 알린다."""
    v = {
        "fragment": fragment_share(getattr(state, "interests", {}) or {}),
        "repeat": repeat_rate(sb),
        "echo": echo_facts(sb),
        "recovery": recovery(sb),
    }
    warn = []
    if v["fragment"]["share"] >= LIMITS["fragment_share"]:
        warn.append(f"관심의 {v['fragment']['share']*100:.0f}%가 말 토막 "
                    f"({', '.join(v['fragment']['items'][:3])})")
    if v["repeat"].get("nudge", 0) >= LIMITS["repeat_rate"]:
        warn.append(f"같은 말 되풀이 {v['repeat']['nudge']*100:.0f}%")
    if v["echo"]["n"] >= LIMITS["echo_facts"]:
        warn.append(f"돌아온 사실 {v['echo']['n']}건")
    if v["recovery"]["reverted"]:
        warn.append(f"고친 것이 되살아남 {v['recovery']['reverted']}건")
    v["warn"] = warn
    for w in warn:
        log(f"  ⚠️ {w}")
    return v


def history_append(sb, v: dict) -> bool:
    """여러 회차에 걸쳐 봐야 한다 — 한 번의 이상은 이상이 아니다."""
    try:
        sb.table("molang_vitals").insert({
            "at": time.time(),
            "fragment": v["fragment"]["share"],
            "repeat": v["repeat"].get("nudge", 0),
            "echo": v["echo"]["n"],
            "reverted": v["recovery"]["reverted"],
            "warn": v.get("warn") or [],
        }).execute()
        return True
    except Exception:
        return False
