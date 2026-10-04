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
MAX_PER_DAY = 8
QUIET_HOURS = (0, 7)          # 이 시간대에는 만들지 않는다
ABSENCE_HOURS = 20            # 이만큼 조용하면 안부


def _now():
    return datetime.now(KST)


def _parse(ts):
    try:
        return datetime.fromisoformat(
            str(ts).replace("Z", "+00:00")).astimezone(KST)
    except Exception:
        return datetime.fromtimestamp(0, KST)


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


def collect_signals(sb, identity=None, registry=None, state=None) -> list[dict]:
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

    # 5) 문득 떠오른 옛일 — 아무도 묻지 않아도 꺼내는 이야기
    if identity is not None:
        try:
            import reminisce
            place = ""
            cue = set()
            try:
                import travel as _tvr
                _cur = (_tvr.load(sb) or {}).get("current")
                if _cur:        # 여행 중이면 섬의 그곳이 계기
                    import island as _isr
                    place = _cur.get("spot") or ""
                    cue = reminisce.cue_from(
                        place=place, room_words=_isr.SPOTS.get(place, []))
                else:
                    import home as _hm
                    _hh = _hm.load(sb)
                    place = (_hh.get("where") or {}).get("molang") or ""
                    cue = reminisce.cue_from(
                        place=place, room_words=_hm.ROOMS.get(place, []))
            except Exception:
                pass
            got = reminisce.pick(list(identity.learned_facts), n=1, cue=cue)
            if got:
                out.append({"rule": "reminisce", "weight": 2,
                            "detail": reminisce.line(got[0], place),
                            "fact_id": got[0].get("id")})
        except Exception:
            pass

    # 6) 간밤의 꿈 — 아침에 꺼내는 이야기
    try:
        import dream as _dream
        ds = _dream.recent(sb, 1)
        if ds and (_now() - _parse(ds[0].get("created_at"))).total_seconds() < 43200:
            out.append({"rule": "dream", "weight": 2,
                        "detail": (ds[0].get("text") or "")[:120]})
    except Exception:
        pass

    # 7) 피우피우와 나눈 이야기 — 사용자에게는 몰랑이가 전한다
    try:
        import piupiu
        talks = piupiu.untold(sb, 1)
        if talks:
            t = talks[0]
            out.append({"rule": "peer", "weight": 3,
                        "detail": f"{t.get('topic')} 얘기하다가 피우피우가 "
                                  f"\"{(t.get('piupiu') or '')[:60]}\" 그러더라",
                        "talk_id": t.get("id")})
    except Exception:
        pass

    # 8) 기분이 한쪽으로 치우쳤을 때
    try:
        import mood as _mood
        h = _mood.recent(state, 1) if state is not None else []
        if h and h[0].get("name") in ("심심함", "벅참"):
            m = h[0]
            out.append({"rule": "mood", "weight": 2,
                        "detail": ("요즘 좀 심심해. 뭔가 새로운 얘기 없어?"
                                   if m["name"] == "심심함" else
                                   "아직 확실하지 않은 게 너무 많아서 좀 벅차. "
                                   "같이 정리해줄래?")})
    except Exception:
        pass

    # 9) 바깥이 궁금하다 — 액자에서 잠깐 내다보기
    #
    # 초상화 속 인물처럼, 평소엔 자기 삶을 살다가 가끔 밖을 내다본다.
    # 카메라는 **사람이 눌러야** 켜진다(브라우저가 그렇게 막아 둔다).
    # 그래서 '보고 싶다'까지가 이 아이 몫이고, 셔터는 사람 몫이다.
    # 그편이 안전하기도 하다 — 늘 지켜보는 눈이 되지 않는다.
    try:
        import random as _rnd
        m = (getattr(state, "moods", None) or [{}])[-1]
        curious = (m.get("name") in ("심심함", "들뜸")
                   or float(m.get("surprise") or 0) > 0.6)
        # 오늘 이미 내다봤으면 또 조르지 않는다
        seen_today = (sb.table("molang_outbox").select("id", count="exact")
                      .eq("rule", "peek")
                      .gte("created_at", _now().strftime("%Y-%m-%d"))
                      .execute().count or 0)
        if curious and not seen_today and _rnd.random() < 0.35:
            want = ""
            try:
                top = sorted((getattr(state, "interests", {}) or {}).items(),
                             key=lambda kv: -kv[1])[:5]
                top = [k for k, v in top if v >= 1.0 and len(k) >= 2]
                if top:
                    want = _rnd.choice(top)
            except Exception:
                pass
            import random as _r2
            if want and _r2.random() < 0.45:
                _ask = f"{want} 소리 지금 들려? 들려줄래?"
            elif want:
                _ask = f"{want} 같은 거 지금 거기 있어? 보여줄래?"
            else:
                _ask = "지금 거기 어때? 잠깐 보여주거나 들려줄래?"
            out.append({"rule": "peek", "weight": 2, "detail": _ask})
    except Exception:
        pass

    # 10) 그때 그거 어떻게 됐어? — 기억하고 기다린 것
    try:
        import caring as _cr
        w = _cr.due_plan(sb)
        if w:
            out.append({"rule": "waiting", "weight": 3,
                        "detail": f"며칠 전에 \"{w['text'][:50]}\" 그랬잖아. "
                                  "그거 어떻게 됐어?",
                        "wait_id": w["id"]})
    except Exception:
        pass

    # 11) 이거 맞아? — 확신이 흐려진 기억을 맞춰본다
    try:
        import caring as _cr2
        b = _cr2.fading_belief(sb)
        if b:
            out.append({"rule": "confirm", "weight": 2,
                        "detail": f"내가 \"{b['text'][:50]}\" 라고 알고 있는데, "
                                  "이거 맞아? 좀 흐릿해졌어.",
                        "fact_id": b["id"]})
    except Exception:
        pass

    # 12) 오래 조용함
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
    "new_finding": "{topic} 찾아보다가 이런 걸 봤어. \"{detail}\" 같이 볼래?",
    "pending": "내가 모아둔 것 중 {n}개는 아직 확실하지 않아서 옆에 놔뒀어. "
               "시간 될 때 왼쪽 검토 칸에서 봐줘.",
    "unsure": "이거 맞는지 아직 잘 모르겠어. \"{detail}\" 이거 맞아?",
    "grew": "요즘 생각하는 방식이 조금 달라진 것 같아. 내 판단 단계가 {n}개 늘었더라.",
    "absence": "오늘은 어땠어? 나는 혼자 이것저것 찾아봤어.",
    "reminisce": "{detail}",
    "dream": "나 간밤에 이런 꿈을 꿨어. {detail}",
    "peer": "{detail}",
    "mood": "{detail}",
    "peek": "{detail}",
    "waiting": "{detail}",
    "confirm": "{detail}",
}

# 다듬기는 '말투만' 손대게 한다. 화자를 뒤집거나 내용을 빼면 먼저 말 걸기가
# 대화처럼 보이고(몰랑이가 사용자 말투로 답함), 무엇을 찾았는지도 사라진다.
POLISH = """너는 몰랑이(흰 토끼)다. 지금 **네가 먼저** 사용자에게 말을 건다.

규칙
- 아래 문장의 **뜻과 화자를 그대로** 두고 말투만 다정하게 다듬어라.
- 따옴표 안의 내용과 숫자는 **반드시 그대로 남긴다.**
- 사용자에게 답하는 말투로 바꾸지 마라. 네가 먼저 꺼내는 말이다.
- 한 문장, 이모지는 최대 1개. 설명을 덧붙이지 마라.

예)
입력: 화산 찾아보다가 이런 걸 봤어. "용암 동굴의 생물" 같이 볼래?
출력: 나 화산 찾아보다가 "용암 동굴의 생물" 이런 걸 봤어, 같이 볼래? 🐰"""


# 몰랑이가 한 일을 사용자가 한 일로 뒤집는 표현 (실제로 두 번 나왔다)
FLIPPED = ("너가 찾", "네가 찾", "너가 알아", "네가 알아", "너가 봤", "네가 봤",
           "보여줘도", "네가 찾아온", "너가 찾아온")


def _keep_core(original: str, polished: str) -> bool:
    """다듬은 말이 원래 알맹이와 **화자와 문장의 꼴**을 지켰는지."""
    import re
    if any(f in polished for f in FLIPPED):
        return False                      # 주어가 뒤집힘 → 원문을 쓴다

    # **묻는 말은 묻는 말로 남아야 한다.**
    # 다듬기가 "이거 맞아?" 를 "…는 사실이야" 로 바꾼 일이 있었다.
    # 그러면 재확인이 아니라 거짓 확신이 된다 — 흐려진 기억을 묻는 자리인데
    # 오히려 더 단단하게 말해버리는 셈이다.
    if "?" in original and "?" not in polished:
        return False
    ASSERT = ("사실이야", "맞아!", "확실해", "분명해", "틀림없")
    if "?" in original and any(x in polished for x in ASSERT):
        return False
    core = re.findall(r'"([^"]+)"', original)
    for c in core:
        head = c.strip()[:8]
        if head and head not in polished:
            return False
    for num in re.findall(r"\d+", original):
        if num not in polished:
            return False
    return True


def _polish(body: str, api_key: str, persona: str = "") -> str:
    if not api_key:
        return body
    try:
        from openai import OpenAI
        c = OpenAI(api_key=api_key)
        r = c.chat.completions.create(
            model=os.environ.get("OPENAI_NUDGE_MODEL", "gpt-4o-mini"),
            temperature=0.5, max_tokens=90,
            messages=[{"role": "system", "content": POLISH + "\n" + persona[:400]},
                      {"role": "user", "content": body}])
        out = (r.choices[0].message.content or "").strip()
    except Exception:
        return body
    # 알맹이가 빠졌거나 너무 길면 원문을 쓴다 (다듬기는 거들 뿐)
    if not out or len(out) > len(body) * 2 or not _keep_core(body, out):
        return body
    return out


def make(sb, identity=None, registry=None, api_key=None, state=None, log=print):
    """계기가 있으면 한 마디를 만들어 outbox 에 넣는다. 없으면 None."""
    if QUIET_HOURS[0] <= _now().hour < QUIET_HOURS[1]:
        return None
    signals = collect_signals(sb, identity, registry, state)
    if not signals:
        return None

    # 하루 상한은 '조잘거리는 말'에만 건다.
    # 묻는 말(물어보고 기다리는 것)은 그와 성격이 다르므로 따로 센다.
    ASK = ("peek", "waiting", "confirm")
    if _sent_today(sb) >= MAX_PER_DAY:
        signals = [s for s in signals if s["rule"] in ASK]
        if not signals:
            return None
        # 묻는 말도 쌓이면 곤란하다 — 아직 답 안 한 것이 3개면 멈춘다
        try:
            waiting = len([p for p in pending(sb, limit=10)
                           if p.get("rule") in ASK])
            if waiting >= 3:
                return None
        except Exception:
            pass

    last = _last_rule(sb)
    signals = [s for s in signals if s["rule"] != last] or signals
    sig = max(signals, key=lambda s: s["weight"])

    # 알맹이가 비어 있으면 그 계기는 건너뛴다 ('그거 찾다가 …' 같은 빈 말 방지)
    if sig["rule"] in ("new_finding", "unsure", "reminisce", "dream", "peer") \
            and not (sig.get("detail") or "").strip():
        signals = [s2 for s2 in signals if s2 is not sig]
        if not signals:
            return None
        sig = max(signals, key=lambda s2: s2["weight"])
    body = TEMPLATES[sig["rule"]].format(
        topic=(sig.get("topic") or "이것저것"), detail=sig.get("detail", ""),
        n=sig.get("n", 0))
    persona = ""
    try:
        persona = identity.to_system_prompt() if identity else ""
    except Exception:
        pass
    body = _polish(body, api_key, persona)

    try:
        # 계기에 딸린 것(어느 기억인지, 어느 기다림인지)도 함께 남긴다.
        # 그래야 앱에서 "맞아/아니야" 를 눌렀을 때 무엇을 고칠지 안다.
        _extra = {k: sig[k] for k in ("wait_id", "fact_id", "talk_id")
                  if sig.get(k) is not None}
        _row = {"body": body[:500], "rule": sig["rule"],
                "scheduled_at": _now().isoformat()}
        if _extra:
            _row["payload"] = _extra
        sb.table("molang_outbox").insert(_row).execute()
        log(f"  먼저 말 걸기 준비: [{sig['rule']}] {body[:40]}")
    except Exception as e:
        log(f"  outbox 저장 실패: {e}")
        return None
    return {"body": body, "rule": sig["rule"]}


# 목적 제안은 같은 표를 쓰지만 '먼저 말 걸기'가 아니다.
# 승인/거절이 필요한 것이라 사이드바에서 따로 다룬다.
# (아웃박스가 먼저 꺼내 가면 sent_at 이 채워져 사이드바에서 사라졌다)
PURPOSE_RULES = ("purpose_sub", "purpose_core")


def pending(sb, limit: int = 3) -> list[dict]:
    """앱이 열릴 때 아직 안 전한 말들. 목적 제안은 빼고."""
    try:
        rows = (sb.table("molang_outbox")
                .select("id,body,rule,payload,created_at")
                .is_("sent_at", "null")
                .order("id", desc=False).limit(limit + 4).execute().data) or []
        return [r for r in rows
                if r.get("rule") not in PURPOSE_RULES][:limit]
    except Exception:
        return []


def latest_finding(sb) -> dict | None:
    """먼저 말 건 '찾은 것'의 실체 — 제목·주소·본문 앞부분.

    말만 건네고 내용을 안 들고 있으면, 사용자가 '같이 보자'고 했을 때
    무엇을 보자는 건지 몰랑이 자신이 모른다. 실제로 그렇게 어긋났다.
    """
    try:
        rows = (sb.table("organism_observations")
                .select("id,topic,title,text,url,status")
                .eq("status", "candidate")
                .order("id", desc=True).limit(1).execute().data) or []
        return rows[0] if rows else None
    except Exception:
        return None


def mark_sent(sb, ids: list[int]):
    if not ids:
        return
    try:
        sb.table("molang_outbox").update(
            {"sent_at": _now().isoformat()}).in_("id", ids).execute()
    except Exception:
        pass
