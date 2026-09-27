"""
purpose_growth.py — 목적이 아래에서부터 자란다.

왜 아래에서부터인가
  사람도 아기 때와 어른의 목적이 다르다. 그런데 그 변화는 어느 날
  결심해서 오지 않는다. 작은 관심이 반복되고, 그게 쌓여 방향이 되고,
  결국 '무엇을 향해 사는가'가 달라진다.

  그래서 두 층으로 둔다.
    하위 목적  "요즘 나는 ○○을 알고 싶다"  — 생기고 시들기를 반복
    핵심 목적  "무엇을 향해 사는가"          — 하위가 오래 쌓였을 때만 흔들린다

  둘 다 **사람 승인**을 거친다. 승인 없이 목적이 바뀌면 그건 성장이 아니라 표류다.

언제 제안하나 (조건이 다 차야 한다)
  하위 목적
    · 생각 흔적이 MIN_MUSINGS 이상 — 충분히 혼자 생각해봤나
    · 한 주제가 관심 상위에 STREAK 회 연속 머물렀나 — 스쳐간 게 아닌가
    · 그 주제에 근거(관측·사고 기억)가 쌓였나 — 아는 게 있나
    · 마지막 제안 이후 COOLDOWN 시간이 지났나 — 매번 조르지 않기
  핵심 목적
    · 승인된 하위 목적이 MIN_SUBS 개 이상
    · 그중 절반 이상이 핵심 목적과 결이 다를 때
      (지금 목적으로 설명 안 되는 방향이 이미 삶의 중심이 됐다는 뜻)

제안은 outbox 로 간다. 사람이 ○ 하면 반영되고, × 하면 기록만 남는다.
"""
from __future__ import annotations
import json
import os
import time

MIN_MUSINGS = 40          # 하위 목적: 이만큼은 혼자 생각해본 뒤에
STREAK = 3                # 관심 상위에 연속으로 머문 회차
COOLDOWN_H = 20           # 제안 간격
MIN_SUBS = 3              # 핵심 목적: 승인된 하위가 이만큼 쌓였을 때
DRIFT_RATIO = 0.5         # 그중 이 비율 이상이 핵심과 결이 다르면


# ── 저장 (molang_purposes) ───────────────────────────────────
def load_subs(sb, only_active=True) -> list[dict]:
    try:
        q = sb.table("molang_purposes").select("*").order("id", desc=True)
        rows = q.limit(50).execute().data or []
    except Exception:
        return []
    if only_active:
        rows = [r for r in rows if r.get("status") == "active"]
    return rows


def _recent_topic_streak(sb, top_n=5) -> dict:
    """회고 이력에서 '상위 관심에 연속으로 있던 주제'를 센다."""
    try:
        rows = (sb.table("organism_reflections").select("top_interests")
                .order("id", desc=True).limit(STREAK).execute().data) or []
    except Exception:
        return {}
    if len(rows) < STREAK:
        return {}
    sets = []
    for r in rows:
        ti = r.get("top_interests") or []
        names = [t[0] if isinstance(t, (list, tuple)) else str(t) for t in ti[:top_n]]
        sets.append(set(names))
    common = set.intersection(*sets) if sets else set()
    return {t: STREAK for t in common}


def _evidence_for(sb, topic: str) -> int:
    try:
        r = (sb.table("organism_observations").select("id", count="exact")
             .eq("topic", topic).eq("status", "candidate").execute())
        return r.count or 0
    except Exception:
        return 0


def _last_proposal_age_h(sb) -> float:
    try:
        rows = (sb.table("molang_outbox").select("created_at,rule")
                .in_("rule", ["purpose_sub", "purpose_core"])
                .order("id", desc=True).limit(1).execute().data) or []
        if not rows:
            return 9999.0
        from datetime import datetime, timezone
        t = datetime.fromisoformat(str(rows[0]["created_at"]).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600
    except Exception:
        return 9999.0


# ── 하위 목적 제안 ───────────────────────────────────────────
SUB_SYSTEM = """너는 몰랑이(흰 토끼)다. 지금 너에게 생긴 관심을 바탕으로
'요즘 내가 알고 싶은 것' 하나를 목적 문장으로 만든다.

규칙
- 주어는 '나'. 한 문장, 25자 안팎.
- 주제 이름을 그대로 쓰지 말고, 무엇을 왜 알고 싶은지로 쓴다.
  나쁨: "음악에 대해 알고 싶다"
  좋음: "소리가 사람 마음을 어떻게 움직이는지 알고 싶다"
- 지금 핵심 목적과 부딪히지 않게.

JSON 하나만: {"purpose":"...", "from_topic":"...", "why":"한 줄"}"""


def propose_sub(sb, state, api_key=None, core_purpose="", log=print):
    """조건이 차면 하위 목적 하나를 제안해 outbox 에 넣는다."""
    musings = len(getattr(state, "musings", []) or [])
    if musings < MIN_MUSINGS:
        return {"skip": f"생각이 아직 {musings}회 (필요 {MIN_MUSINGS})"}
    if _last_proposal_age_h(sb) < COOLDOWN_H:
        return {"skip": "최근에 이미 제안함"}

    streaks = _recent_topic_streak(sb)
    if not streaks:
        return {"skip": "상위 관심에 오래 머문 주제가 없음"}

    existing = {r.get("from_topic") for r in load_subs(sb)}
    cand = [t for t in streaks if t not in existing and _evidence_for(sb, t) >= 2]
    if not cand:
        return {"skip": "근거가 쌓인 새 주제가 없음"}

    topic = max(cand, key=lambda t: (state.interests or {}).get(t, 0))
    body = f"요즘 {topic}에 마음이 자주 가. 이걸 더 알고 싶은 걸 목적으로 삼아도 될까?"
    payload = {"purpose": f"{topic}에 대해 더 알고 싶다", "from_topic": topic,
               "why": f"관심 상위에 {STREAK}회 연속, 근거 {_evidence_for(sb, topic)}건"}

    if api_key:                      # 문장만 다듬는다 (판단은 규칙이 했다)
        try:
            from openai import OpenAI
            c = OpenAI(api_key=api_key)
            r = c.chat.completions.create(
                model=os.environ.get("OPENAI_NUDGE_MODEL", "gpt-4o-mini"),
                temperature=0.5, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": SUB_SYSTEM},
                          {"role": "user",
                           "content": f"핵심 목적: {core_purpose}\n"
                                      f"요즘 관심: {topic}\n"
                                      f"근거 {_evidence_for(sb, topic)}건"}])
            d = json.loads(r.choices[0].message.content)
            if d.get("purpose"):
                payload.update({k: d.get(k, payload.get(k))
                                for k in ("purpose", "why")})
                body = f"{payload['purpose']} … 이걸 내 목적으로 삼아도 될까?"
        except Exception as e:
            log(f"  하위 목적 다듬기 실패: {e}")

    try:
        sb.table("molang_outbox").insert({
            "body": body[:500], "rule": "purpose_sub",
            "scheduled_at": _now(), "payload": payload}).execute()
        log(f"  하위 목적 제안: {payload['purpose']}")
    except Exception as e:
        return {"error": str(e)[:150]}
    return {"proposed": payload}


# ── 핵심 목적 제안 ───────────────────────────────────────────
CORE_SYSTEM = """너는 몰랑이(흰 토끼)다. 그동안 네가 품어온 목적들을 보고,
'무엇을 향해 사는가'를 다시 한 문장으로 쓴다.

규칙
- 지금 핵심 목적을 버리지 말고, 그동안 쌓인 방향을 품어 넓힌다.
- 한 문장, 40자 안팎. 주어는 생략.
- 유행어·거창한 말 금지. 네가 실제로 해온 일에서 나온 말이어야 한다.

JSON 하나만: {"purpose":"...", "changed":"무엇이 달라졌는지 한 줄"}"""


def propose_core(sb, api_key=None, core_purpose="", log=print):
    """승인된 하위 목적이 쌓이고 결이 달라졌을 때만 핵심 목적을 다시 제안."""
    subs = load_subs(sb)
    if len(subs) < MIN_SUBS:
        return {"skip": f"하위 목적 {len(subs)}개 (필요 {MIN_SUBS})"}
    if _last_proposal_age_h(sb) < COOLDOWN_H:
        return {"skip": "최근에 이미 제안함"}

    import re
    core_words = set(re.findall(r"[가-힣]{2,}", core_purpose or ""))
    drift = 0
    for s in subs:
        w = set(re.findall(r"[가-힣]{2,}", s.get("purpose") or ""))
        if not (w & core_words):
            drift += 1
    if drift < max(1, int(len(subs) * DRIFT_RATIO)):
        return {"skip": f"아직 핵심과 결이 이어짐 ({drift}/{len(subs)})"}

    payload = {"old": core_purpose,
               "subs": [s.get("purpose") for s in subs][:6], "drift": drift}
    body = "요즘 내가 향하는 곳이 처음과 조금 달라진 것 같아. 다시 정해도 될까?"
    if api_key:
        try:
            from openai import OpenAI
            c = OpenAI(api_key=api_key)
            r = c.chat.completions.create(
                model=os.environ.get("OPENAI_NUDGE_MODEL", "gpt-4o-mini"),
                temperature=0.4, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": CORE_SYSTEM},
                          {"role": "user",
                           "content": f"지금 핵심 목적: {core_purpose}\n"
                                      "그동안 품은 목적들:\n- "
                                      + "\n- ".join(payload["subs"])}])
            d = json.loads(r.choices[0].message.content)
            if d.get("purpose"):
                payload["new"] = d["purpose"]
                payload["changed"] = d.get("changed", "")
                body = (f"내가 향하는 곳을 이렇게 바꿔도 될까? "
                        f"\"{d['purpose']}\"")
        except Exception as e:
            log(f"  핵심 목적 다듬기 실패: {e}")
    if not payload.get("new"):
        return {"skip": "새 문장을 못 만듦"}

    try:
        sb.table("molang_outbox").insert({
            "body": body[:500], "rule": "purpose_core",
            "scheduled_at": _now(), "payload": payload}).execute()
        log(f"  핵심 목적 제안: {payload['new']}")
    except Exception as e:
        return {"error": str(e)[:150]}
    return {"proposed": payload}


# ── 승인·거절 ────────────────────────────────────────────────
def accept(sb, identity, outbox_row) -> dict:
    """사람이 ○ 했을 때. 하위는 목록에 넣고, 핵심은 정체성을 고친다."""
    rule = outbox_row.get("rule")
    p = outbox_row.get("payload") or {}
    try:
        if rule == "purpose_sub":
            sb.table("molang_purposes").insert({
                "purpose": p.get("purpose"), "from_topic": p.get("from_topic"),
                "why": p.get("why"), "status": "active"}).execute()
            return {"ok": True, "kind": "sub"}
        if rule == "purpose_core":
            new = p.get("new")
            if not new:
                return {"ok": False, "error": "새 목적 문장이 없어요"}
            sb.table("molang_purposes").insert({
                "purpose": new, "from_topic": "(핵심)", "why": p.get("changed"),
                "status": "core"}).execute()
            base = identity.persona or ""
            import re
            if "[무엇을 향해 사는가]" in base:
                base = re.sub(r"\[무엇을 향해 사는가\].*",
                              f"[무엇을 향해 사는가] {new}", base, count=1)
            else:
                base = f"[무엇을 향해 사는가] {new}\n" + base
            identity.persona = base
            identity.save_identity()
            return {"ok": True, "kind": "core", "new": new}
        return {"ok": False, "error": "목적 제안이 아니에요"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def decline(sb, outbox_row) -> dict:
    try:
        sb.table("molang_outbox").update(
            {"error": "declined"}).eq("id", outbox_row["id"]).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:150]}


def _now():
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=9))).isoformat()
