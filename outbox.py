"""
outbox.py — 몰랑이가 먼저 말을 건다.

왜 규칙이 먼저인가
  "무슨 말을 걸까"를 LLM에게 통째로 맡기면 매번 그럴듯한 말을 지어낸다.
  할 말이 없을 때도 말을 만들어낸다는 뜻이다. 그건 자율성이 아니라 수다다.

  그래서 **발화 여부와 이유는 규칙이 정하고, 문장만 LLM이 다듬는다.**
  임용 앱의 질문함과 같은 원리다 — 지어낸 궁금증이 아니라 측정된 상태에서만
  말이 나온다.

말을 거는 다섯 가지 계기
  new_finding   호기심 루프가 찾아온 것 중 아직 안 보여준 게 있다
  pending       검토 대기가 쌓였다 (사람 판단이 필요하다)
  unsure        확신 못 하는 사실이 오래 남아 있다 (물어보면 풀린다)
  grew          사고 구조가 스스로 바뀌었다 (알릴 만한 사건)
  absence       마지막 대화 이후 오래 지났다

규칙
  · 계기가 없으면 아무 말도 안 한다. 그게 정상이다.
  · 하루 상한이 있다 (MAX_PER_DAY). 말 많은 존재가 되지 않도록.
  · 같은 계기를 연달아 쓰지 않는다.
  · 보낸 것은 molang_outbox 에 남아 무엇이 왜 나왔는지 되짚을 수 있다.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
MAX_PER_DAY = 4
QUIET_HOURS = (0, 7)          # 이 시간대에는 만들지 않는다
ABSENCE_HOURS = 20            # 이만큼 조용하면 안부


def _now():
    return datetime.now(KST)


def _sent_today(sb) -> int:
    try:
        since = _now().replace(hour=0, minute=0, second=0).isoformat()
        r = (sb.table("molang_outbox").select("id", count="exact")
             .gte("created_at", since).execute())
        return r.count or 0
    except Exception:
        return 0


def _last_rule(sb):
    try:
        rows = (sb.table("molang_outbox").select("rule")
                .order("id", desc=True).limit(1).execute().data) or []
        return rows[0]["rule"] if rows else None
    except Exception:
        return None


def collect_signals(sb, identity=None, registry=None) -> list[dict]:
    """지금 말을 걸 만한 계기들. 없으면 빈 목록."""
    out = []

    # 1) 새로 찾은 것 (아직 안 보여준 후보)
    try:
        rows = (sb.table("organism_observations")
                .select("id,topic,title,url,status")
                .eq("status", "candidate").eq("fed", False)
                .order("id", desc=True).limit(3).execute().data) or []
        if rows:
            out.append({"rule": "new_finding", "weight": 3,
                        "topic": rows[0].get("topic"),
                        "detail": (rows[0].get("title") or "")[:60],
                        "n": len(rows)})
    except Exception:
        pass

    # 2) 검토 대기
    try:
        r = (sb.table("organism_observations").select("id", count="exact")
             .eq("status", "quarantine").execute())
        n = r.count or 0
        if n >= 3:
            out.append({"rule": "pending", "weight": 2, "n": n})
    except Exception:
        pass

    # 3) 오래 확신 못 한 것
    if identity is not None:
        try:
            weak = [f for f in identity.learned_facts
                    if 0.2 < (f.get("strength") or 0) < 0.6]
            if weak:
                out.append({"rule": "unsure", "weight": 2,
                            "detail": str(weak[0].get("text"))[:60],
                            "n": len(weak)})
        except Exception:
            pass

    # 4) 사고 구조가 자랐다
    if registry is not None:
        try:
            grown = [n for t in registry.trees.values() for n in t.nodes
                     if str(n).startswith("grown_")]
            if grown:
                out.append({"rule": "grew", "weight": 1, "n": len(grown)})
        except Exception:
            pass

    # 5) 오래 조용함
    try:
        rows = (sb.table("molang_episodes").select("created_at")
                .order("id", desc=True).limit(1).execute().data) or []
        if rows and rows[0].get("created_at"):
            last = datetime.fromisoformat(
                str(rows[0]["created_at"]).replace("Z", "+00:00"))
            if (_now() - last.astimezone(KST)) > timedelta(hours=ABSENCE_HOURS):
                out.append({"rule": "absence", "weight": 1})
    except Exception:
        pass

    return out


TEMPLATES = {
    "new_finding": "{topic} 알아보다가 재미있는 걸 찾았어. {detail} … 보여줄까?",
    "pending": "내가 찾아온 것 중에 {n}개가 아직 확실하지 않아. 같이 봐줄래?",
    "unsure": "이거 맞는지 아직 잘 모르겠어. \"{detail}\" 맞아?",
    "grew": "요즘 생각하는 방식이 조금 달라진 것 같아. 판단 단계가 {n}개 늘었어.",
    "absence": "오늘은 어땠어? 나는 혼자 이것저것 찾아봤어.",
}

POLISH = """너는 몰랑이(흰 토끼)다. 아래 '할 말'을 몰랑이 말투로 한 문장만 다듬어라.
내용을 더하거나 지어내지 말고, 짧고 다정하게. 이모지는 최대 1개."""


def _polish(body: str, api_key: str, persona: str = "") -> str:
    if not api_key:
        return body
    try:
        from openai import OpenAI
        c = OpenAI(api_key=api_key)
        r = c.chat.completions.create(
            model=os.environ.get("OPENAI_NUDGE_MODEL", "gpt-4o-mini"),
            temperature=0.7, max_tokens=80,
            messages=[{"role": "system", "content": POLISH + "\n" + persona[:600]},
                      {"role": "user", "content": body}])
        return (r.choices[0].message.content or body).strip()
    except Exception:
        return body


def make(sb, identity=None, registry=None, api_key=None, log=print):
    """계기가 있으면 한 마디를 만들어 outbox 에 넣는다. 없으면 None."""
    if QUIET_HOURS[0] <= _now().hour < QUIET_HOURS[1]:
        return None
    if _sent_today(sb) >= MAX_PER_DAY:
        return None

    signals = collect_signals(sb, identity, registry)
    if not signals:
        return None

    last = _last_rule(sb)
    signals = [s for s in signals if s["rule"] != last] or signals
    sig = max(signals, key=lambda s: s["weight"])

    body = TEMPLATES[sig["rule"]].format(
        topic=sig.get("topic", "그거"), detail=sig.get("detail", ""),
        n=sig.get("n", 0))
    persona = ""
    try:
        persona = identity.to_system_prompt() if identity else ""
    except Exception:
        pass
    body = _polish(body, api_key, persona)

    try:
        sb.table("molang_outbox").insert({
            "body": body[:500], "rule": sig["rule"],
            "scheduled_at": _now().isoformat()}).execute()
        log(f"  먼저 말 걸기 준비: [{sig['rule']}] {body[:40]}")
    except Exception as e:
        log(f"  outbox 저장 실패: {e}")
        return None
    return {"body": body, "rule": sig["rule"]}


def pending(sb, limit: int = 3) -> list[dict]:
    """앱이 열릴 때 아직 안 전한 말들."""
    try:
        return (sb.table("molang_outbox")
                .select("id,body,rule,created_at")
                .is_("sent_at", "null")
                .order("id", desc=False).limit(limit).execute().data) or []
    except Exception:
        return []


def mark_sent(sb, ids: list[int]):
    if not ids:
        return
    try:
        sb.table("molang_outbox").update(
            {"sent_at": _now().isoformat()}).in_("id", ids).execute()
    except Exception:
        pass
