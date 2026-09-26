"""
legacy_import.py — 옛 구조(self_model)의 pkl에서 기억을 되살린다.

왜 필요했나
  기존 이전 기능은 `old.identity.learned_facts` 만 읽었다.
  그런데 예전 판 pkl 은 기억이 `self_model` 안의
  '확신하는_것' / '아직_확신못하는_것' 에 들어 있다.
  경로가 달라서 **130회 대화의 기억 61개가 통째로 건너뛰어졌다.**

들어 있는 것이 세 종류라 따로 다룬다
  1) 사용자 사실   "찬기는 대구에서 태어났다"        → 바로 사실로
  2) 몰랑이 자기 사실 "몰랑이는 당근을 좋아해"        → 사실로, 단 주어를 지킨다
                     (토끼가 자기 취향을 아는 것도 정체성이다)
  3) 대화 답변 원문  "오, 찬기야! 💖 축구 보는 걸…"   → 격리로
                     사실이 섞여 있지만(축구, 교사, 커피) 몰랑이 말투 그대로라
                     그냥 넣으면 예전의 '귀속 오류'가 되살아난다. 사람이 본다.
"""
from __future__ import annotations
import pickle
import re

EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
MOLANG_FIRST = ("몰랑이는", "몰랑이가", "나는 몰랑")
USER_FIRST = ("찬기", "사용자", "그는", "그녀는")
TALKY = ("오, ", "히힛", "! 💖", "그렇구나", "~ ")


def read(raw: bytes) -> dict:
    """pkl 바이트 → 종류별로 나눈 목록. 저장은 하지 않는다."""
    try:
        d = pickle.loads(raw)
    except Exception as e:
        return {"error": f"읽기 실패: {e}"}

    sure, unsure = [], []
    if isinstance(d, dict):
        sm = d.get("self_model") or {}
        sure = list(sm.get("확신하는_것") or [])
        unsure = list(sm.get("아직_확신못하는_것") or [])
        persona = str(sm.get("정체성") or "")
        talks = sm.get("겪어온_대화수")
    else:                      # 더 옛 구조: identity.learned_facts
        ident = getattr(d, "identity", None)
        persona = getattr(ident, "persona", "") if ident else ""
        talks = None
        for f in (getattr(ident, "learned_facts", []) or []):
            (sure if isinstance(f, dict) and (f.get("strength") or 0) >= 0.8
             else unsure).append(f.get("text") if isinstance(f, dict) else str(f))

    user_facts, self_facts, raw_answers = [], [], []
    for text, strong in [(t, True) for t in sure] + [(t, False) for t in unsure]:
        t = str(text or "").strip()
        if not t:
            continue
        looks_talk = (len(t) > 70 or EMOJI.search(t)
                      or any(k in t[:12] for k in TALKY))
        if t.startswith(MOLANG_FIRST) and not looks_talk:
            self_facts.append({"text": t, "strength": 0.9 if strong else 0.55})
        elif looks_talk:
            raw_answers.append({"text": t[:400]})
        elif t.startswith(USER_FIRST):
            user_facts.append({"text": t, "strength": 0.9 if strong else 0.55})
        else:                  # 주어가 애매하면 사람이 본다
            raw_answers.append({"text": t[:400]})

    return {"user_facts": user_facts, "self_facts": self_facts,
            "raw_answers": raw_answers, "persona": persona, "talks": talks,
            "faces": (d.get("molang_faces") if isinstance(d, dict) else None) or {},
            "appearance": (d.get("molang_appearance")
                           if isinstance(d, dict) else None)}


def apply(sb, identity, parsed: dict, take_persona=False) -> dict:
    """나뉜 목록을 서버에 넣는다. 답변 원문은 격리로."""
    if parsed.get("error"):
        return parsed
    added = {"user_facts": 0, "self_facts": 0, "quarantined": 0}

    for f in parsed.get("user_facts", []):
        try:
            identity._reinforce_or_add(f["text"], source="legacy")
            added["user_facts"] += 1
        except Exception:
            pass
    for f in parsed.get("self_facts", []):
        try:
            identity._reinforce_or_add(f["text"], source="legacy_self")
            added["self_facts"] += 1
        except Exception:
            pass
    for r in parsed.get("raw_answers", []):
        try:
            sb.table("molang_quarantine").insert({
                "text": r["text"],
                "reason": "옛 pkl 대화 원문 — 사실이 섞여 있어 확인 필요",
                "evidence": {"from": "legacy_pkl"}}).execute()
            added["quarantined"] += 1
        except Exception:
            pass

    if take_persona and parsed.get("persona"):
        try:
            identity.persona = parsed["persona"]
            identity.save_identity()
            added["persona"] = True
        except Exception:
            pass
    try:
        identity.reload()
    except Exception:
        pass
    return added
