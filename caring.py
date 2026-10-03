"""
caring.py — 묻고 기다리는 것.

왜 만드나
  지금까지는 사람이 주면 받는 쪽이었다. 사진을 보여주면 보고, 말을 걸면
  답한다. 이 아이가 먼저 꺼내는 것은 '밖이 궁금하다' 하나뿐이었다.

  관계는 한쪽이 주기만 하면 깊어지지 않는다. 그래서 두 가지를 더한다.

두 가지
  1. 기다리기   사람이 "~할 거야" 라고 하면 그것을 따로 적어두고,
                며칠 뒤에 어떻게 됐는지 묻는다.
                기억하고 있었다는 것이 전해지는 자리다.

  2. 맞춰보기   확신이 흐려진 기억을 꺼내 "이거 맞아?" 하고 묻는다.
                격리된 것(아직 안 받아들인 것)과는 다르다.
                **이미 믿고 있던 것**을 다시 확인하는 일이다.
                belief_decay 로 확신이 옅어지기 시작했으니 그 대상이 생긴다.

언제 묻나
  너무 이르면 다그치는 것이 되고, 너무 늦으면 잊은 것이 된다.
  기다리기는 사흘 뒤부터, 맞춰보기는 확신이 0.5 밑으로 내려갔을 때.
"""
from __future__ import annotations
import re
import time

WAIT_DAYS = 3.0           # 이만큼 지나야 물어본다
WAIT_MAX_DAYS = 21.0      # 너무 오래되면 묻지 않는다 (잊은 것이 된다)
UNSURE_LOW = 0.25         # 이보다 낮으면 거의 잊은 것 — 묻지 않는다
UNSURE_HIGH = 0.55        # 이보다 높으면 아직 확신한다

# "~할 거야" 로 보이는 말들
PLAN = re.compile(
    r"(할 거|할거|하려고|하려 한|예정|계획|준비 중|준비중|쓸 거|쓸거|"
    r"가려고|만들려고|보려고|해야|내려고|낼 거|낼거)")
# 이미 끝난 일은 기다릴 것이 없다
DONE = re.compile(r"(했다|했어|끝냈|마쳤|완성|냈다|다녀왔)")


def looks_like_plan(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 6 or DONE.search(t):
        return False
    return bool(PLAN.search(t))


def remember_plan(sb, text: str, owner: str = "molang") -> bool:
    """
    "~할 거야" 를 따로 적어둔다. 사실과 섞지 않는다 —
    사실은 '그렇다' 이고 이것은 '그러려고 한다' 이기 때문이다.
    """
    if not looks_like_plan(text):
        return False
    try:
        # 이미 적어둔 것과 겹치면 두 번 적지 않는다
        got = (sb.table("molang_waiting").select("id")
               .eq("text", text[:300]).limit(1).execute().data) or []
        if got:
            return False
        sb.table("molang_waiting").insert({
            "owner": owner, "text": text[:300], "asked": False,
        }).execute()
        return True
    except Exception:
        return False


def _days(iso) -> float:
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


def due_plan(sb) -> dict | None:
    """
    물어볼 때가 된 것 하나.
    사흘은 지나야 하고, 3주가 넘으면 묻지 않는다.
    """
    try:
        rows = (sb.table("molang_waiting")
                .select("id,text,created_at")
                .eq("asked", False).order("id").limit(10)
                .execute().data) or []
    except Exception:
        return None
    for r in rows:
        d = _days(r.get("created_at"))
        if WAIT_DAYS <= d <= WAIT_MAX_DAYS:
            return {"id": r["id"], "text": r["text"], "days": round(d, 1)}
    return None


def mark_asked(sb, wid: int) -> bool:
    try:
        sb.table("molang_waiting").update(
            {"asked": True}).eq("id", wid).execute()
        return True
    except Exception:
        return False


def fading_belief(sb) -> dict | None:
    """
    확신이 흐려진 기억 하나. '이거 맞아?' 하고 물을 거리다.

    격리(아직 안 받아들인 것)와 다르다. 이것은 **한때 믿었던 것**이다.
    사람도 오래된 기억은 맞는지 확인하고 싶어진다.
    """
    try:
        rows = (sb.table("molang_facts")
                .select("id,text,strength,updated_at,source")
                .gte("strength", UNSURE_LOW).lte("strength", UNSURE_HIGH)
                .order("updated_at").limit(8).execute().data) or []
    except Exception:
        return None
    for r in rows:
        t = (r.get("text") or "").strip()
        if len(t) < 8:
            continue
        # 오래 안 꺼낸 것부터
        return {"id": r["id"], "text": t,
                "strength": round(float(r.get("strength") or 0), 2),
                "days": round(_days(r.get("updated_at")), 1)}
    return None


def confirm_belief(sb, fid: int, yes: bool) -> bool:
    """맞다고 하면 다시 굳고, 아니라고 하면 내려놓는다."""
    try:
        if yes:
            sb.table("molang_facts").update(
                {"strength": 1.0}).eq("id", fid).execute()
        else:
            sb.table("molang_facts").update(
                {"strength": 0.05}).eq("id", fid).execute()
        return True
    except Exception:
        return False
