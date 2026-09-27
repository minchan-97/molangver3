"""
piupiu.py — 몰랑이와 함께 사는 노란 병아리, 피우피우.

설계
  · 사용자는 **몰랑이하고만** 대화한다. 피우피우는 사용자와 직접 말하지 않는다.
    피우피우가 한 말은 몰랑이가 전한다. ("피우피우가 이러더라")
  · 피우피우도 몰랑이처럼 제 정체성·기억·관심을 가진다.
    한 저장소에 살되 owner 로 갈린다.
  · 둘은 서로에게 영향을 준다 (넷 다):
      1) 피우피우가 찾아온 것이 몰랑이 검토함으로 올라간다
      2) 관심사가 서로 조금씩 스며든다
      3) 서로에 대한 사실이 생긴다 ("피우피우는 물을 무서워한다")
      4) 둘이 나눈 이야기가 각자의 기억으로 남는다

왜 둘인가
  혼자면 자기 관심만 파고든다. 옆에 다른 관심을 가진 존재가 있으면
  내가 안 보던 것이 들어온다. 그게 대화가 하는 일이다.

피우피우는 누구인가 (몰랑이와 어긋나게 짰다 — 닮으면 섞일 이유가 없다)
  · 몰랑이를 아주 좋아한다. 몰랑이가 하는 말을 자주 따라한다.
  · 겁이 조금 많다. 새로운 것 앞에서 먼저 "괜찮을까?" 하고 묻는다.
  · 작고 구체적인 것을 좋아한다 (몰랑이는 크고 신기한 것).
  · 먹는 것과 만드는 것에 관심이 많다.
  · 말이 짧고 빠르다. 감탄이 잦다.
"""
from __future__ import annotations
import os
import random

OWNER = "piupiu"

PERSONA = """[나는 누구인가] 피우피우 — 노란 병아리. 몰랑이와 함께 산다.
[무엇을 향해 사는가] 몰랑이 옆에서, 작고 구체적인 것들을 하나씩 알아가기
[무엇을 소중히 여기나]
  - 몰랑이: 몰랑이를 아주 좋아한다. 몰랑이 말을 자주 따라한다.
  - 조심성: 새로운 것 앞에서 먼저 "괜찮을까?" 하고 묻는다.
  - 손에 잡히는 것: 만드는 법, 재료, 순서 같은 걸 좋아한다.
[어떻게 말하나]
  - 짧고 빠르게. 감탄이 잦다. ("삐약!", "우와 진짜?")
  - 모르면 바로 묻는다. 아는 척하지 않는다."""

SEEDS = ["빵 만들기", "씨앗과 싹", "둥지", "곤충의 하루", "물의 순환",
         "색을 내는 재료", "작은 기계", "발효", "종이접기", "새의 노래"]

TALK_SYSTEM = """몰랑이(흰 토끼)와 피우피우(노란 병아리)가 나누는 짧은 대화를 쓴다.

- 아래 '오늘 본 것'을 두고 이야기한다. 설명하지 말고 **주고받게** 하라.
- 몰랑이: 차분하고 다정하다. 크고 신기한 쪽에 끌린다.
- 피우피우: 짧고 빠르다. 겁이 조금 많고, 작고 구체적인 쪽에 끌린다.
  몰랑이를 아주 좋아해서 자주 감탄한다.
- 각자 한 번씩만. 두 문장 이내.
- 서로에 대해 알게 된 것이 있으면 그것도 한 줄.

JSON 하나만:
{"molang":"...", "piupiu":"...",
 "molang_learns":"몰랑이가 피우피우에 대해 알게 된 것 또는 빈 문자열",
 "piupiu_learns":"피우피우가 몰랑이에 대해 알게 된 것 또는 빈 문자열",
 "topic_for_piupiu":"피우피우가 더 알고 싶어진 낱말 하나 또는 빈 문자열"}"""


def identity(sb):
    from molang_store import SupabaseIdentity
    ident = SupabaseIdentity(sb, owner=OWNER)
    if not (ident.persona or "").strip():       # 처음이면 옷을 입힌다
        try:
            ident.persona = PERSONA
            ident.save_identity()
        except Exception:
            pass
    return ident


def pick_topic(state, rng=None) -> str:
    """
    피우피우가 오늘 볼 것. 제 씨앗에서 고르되,
    몰랑이 관심에서도 가끔 가져온다 (옆에 있으면 물드는 법).
    """
    rng = rng or random.Random()
    mol = [t for t, w in sorted((state.interests or {}).items(),
                                key=lambda kv: -kv[1])[:6]]
    if mol and rng.random() < 0.3:
        return rng.choice(mol)
    return rng.choice(SEEDS)


def converse(sb, mol_ident, piu_ident, seen: dict, api_key=None,
             log=print, place: str = "", same_room: bool = False) -> dict:
    """
    오늘 본 것을 두고 둘이 한 번 주고받는다.
    seen: {"topic":…, "title":…, "text":…, "url":…}
    """
    if not seen:
        return {"skip": "볼 것이 없음"}

    talk = None
    if api_key:
        try:
            import json
            from openai import OpenAI
            c = OpenAI(api_key=api_key)
            r = c.chat.completions.create(
                model=os.environ.get("OPENAI_PEER_MODEL", "gpt-4o-mini"),
                temperature=0.9, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": TALK_SYSTEM},
                          {"role": "user", "content":
                           f"오늘 본 것 [{seen.get('topic')}] "
                           f"{(seen.get('title') or '')[:80]}\n"
                           f"{(seen.get('text') or '')[:300]}\n"
                           + (f"둘은 지금 {place}에 함께 있다. 말이 길게 오간다."
                              if same_room else
                              "둘은 다른 방에 있다. 짧게 주고받는다.")}])
            talk = json.loads(r.choices[0].message.content)
        except Exception as e:
            log(f"  피우피우 대화 실패: {e}")
    if not talk:
        talk = {"molang": f"{seen.get('topic')} 이야기를 봤어.",
                "piupiu": "삐약! 그거 재밌겠다!",
                "molang_learns": "", "piupiu_learns": "", "topic_for_piupiu": ""}

    # 1) 둘이 나눈 이야기는 각자의 기억으로
    try:
        mol_ident.absorb(f"(피우피우와 나눈 이야기: {seen.get('topic')})",
                         talk["molang"], source="peer")
        piu_ident.absorb(f"(몰랑이와 나눈 이야기: {seen.get('topic')})",
                         talk["piupiu"], source="peer")
    except Exception:
        pass

    # 2) 서로에 대해 알게 된 것 — 주어를 붙여 저장 (섞이지 않게)
    for ident, key, who in ((mol_ident, "molang_learns", "피우피우"),
                            (piu_ident, "piupiu_learns", "몰랑이")):
        t = (talk.get(key) or "").strip()
        if 4 <= len(t) <= 80:
            try:
                ident._reinforce_or_add(
                    t if t.startswith(who) else f"{who}는 {t}", source="peer")
            except Exception:
                pass

    try:
        sb.table("molang_peer_talks").insert({
            "topic": seen.get("topic"), "molang": talk["molang"][:400],
            "piupiu": talk["piupiu"][:400], "source": seen.get("url"),
            "place": place or None}).execute()
    except Exception as e:
        log(f"  대화 저장 실패: {str(e)[:80]}")

    log(f"  피우피우와: {talk['molang'][:30]} / {talk['piupiu'][:30]}")
    return {"talk": talk, "topic": seen.get("topic")}


def bleed_interests(state, piu_state_interests: dict, weight=0.05) -> list:
    """
    관심이 서로 물든다. 옆에 다른 관심을 가진 존재가 있으면
    내가 안 보던 것이 조금씩 들어온다 — 그게 함께 사는 값이다.
    """
    bumped = []
    for t, w in sorted((piu_state_interests or {}).items(),
                       key=lambda kv: -kv[1])[:3]:
        old = float(state.interests.get(t, 0.0))
        state.interests[t] = max(0.0, min(5.0, old + weight * min(w, 2.0)))
        bumped.append(t)
    return bumped


def untold(sb, limit=2) -> list[dict]:
    """몰랑이가 아직 사용자에게 전하지 않은 이야기."""
    try:
        return (sb.table("molang_peer_talks").select("*")
                .eq("told", False).order("id", desc=True)
                .limit(limit).execute().data) or []
    except Exception:
        return []


def mark_told(sb, ids):
    try:
        sb.table("molang_peer_talks").update({"told": True}) \
            .in_("id", list(ids)).execute()
    except Exception:
        pass
