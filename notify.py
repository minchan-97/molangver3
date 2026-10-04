"""
notify.py — 앱을 안 열어도 말이 닿게.

왜 필요한가
  이 아이는 앱과 따로 산다. 워커가 돌면서 생각하고, 찾아보고, 피우피우와
  이야기하고, 가끔 바깥이 궁금해진다. 그런데 **앱을 안 열면 그 말이
  아무 데도 닿지 않는다.** 하고 싶은 말이 쌓이기만 한다.

  ntfy 는 가입도 서버도 필요 없다. 주제 이름 하나로 폰에 알림이 간다.

주제 이름이 곧 비밀번호다
  ntfy 를 만든 사람도 "주제가 당신의 비밀" 이라고 했다. 짧고 흔한 이름을
  쓰면 남이 들여다볼 수 있다. 그래서 길고 뜻 없는 이름을 쓴다.
  그리고 **민감한 내용은 보내지 않는다** — 메시지는 서버에 남는다.

무엇을 보내나
  하고 싶은 말이 생겼을 때만. 하루 몇 번까지만. 같은 말은 다시 안 보낸다.
"""
from __future__ import annotations
import json
import os
import re
import urllib.request

MAX_PER_DAY = 8
TIMEOUT = 8

# 보내면 안 되는 것 — 메시지는 ntfy 서버에 남는다
SENSITIVE = re.compile(
    r"(비밀번호|주민등록|계좌|카드번호|전화번호|주소는|사는 곳은)")


def _topic() -> str:
    return (os.environ.get("NTFY_TOPIC") or "").strip()


def _server() -> str:
    return (os.environ.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")


def available() -> bool:
    return bool(_topic())


def send(title: str, body: str, tags: str = "rabbit",
         click: str = "", actions: str = "", log=print) -> dict:
    """
    알림 하나. 실패해도 회차를 멈추지 않는다.
    """
    topic = _topic()
    if not topic:
        return {"ok": False, "why": "NTFY_TOPIC 이 없음"}
    text = (body or "").strip()
    if not text:
        return {"ok": False, "why": "보낼 말이 없음"}
    if SENSITIVE.search(text):
        return {"ok": False, "why": "민감한 내용이라 안 보냄"}

    headers = {
        "Title": (title or "몰랑이").encode("utf-8"),
        "Tags": tags,
        "Content-Type": "text/plain; charset=utf-8",
        # 서버에 남기지 않는다 (알림만 가고 저장은 안 한다)
        "Cache": "no",
    }
    if click:
        headers["Click"] = click
    # 알림에서 바로 누르는 버튼 (최대 3개).
    # iOS 앱에서는 동작 버튼이 안 먹는 경우가 보고되어 있어,
    # 늘 '앱에서 보기'(view)를 함께 둔다.
    if actions:
        headers["Actions"] = actions.encode("utf-8")
    try:
        req = urllib.request.Request(
            f"{_server()}/{topic}", data=text.encode("utf-8"),
            headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            ok = 200 <= r.status < 300
        return {"ok": ok}
    except Exception as e:
        return {"ok": False, "why": str(e)[:80]}


def _sent_today(sb) -> int:
    try:
        from datetime import datetime, timezone, timedelta
        kst = timezone(timedelta(hours=9))
        today = datetime.now(kst).strftime("%Y-%m-%d")
        r = (sb.table("molang_outbox").select("id", count="exact")
             .eq("notified", True).gte("created_at", today).execute())
        return r.count or 0
    except Exception:
        return 0


def push_pending(sb, app_url: str = "", log=print) -> dict:
    """
    아직 못 전한 말을 알림으로 보낸다.
    피우피우와 나눈 이야기, 찾은 것, 꿈, 기분, 바깥이 궁금한 것 —
    이 아이가 먼저 꺼내려던 말들이다.
    """
    if not available():
        return {"sent": 0, "why": "ntfy 주제가 설정되지 않음"}
    if _sent_today(sb) >= MAX_PER_DAY:
        return {"sent": 0, "why": "오늘은 충분히 말했음"}

    try:
        # **아직 알림으로 안 보낸 말.**
        #
        # 예전에는 sent_at 이 비어 있는 것만 봤다. 그런데 sent_at 은
        # '앱에서 보여줬다' 는 표시이고, 알림은 그와 다른 일이다.
        # 앱을 열어 봤든 안 봤든, 폰으로 보냈는지는 notified 가 가린다.
        # (그 탓에 쌓인 말이 10건인데 하나도 안 나갔다)
        # **한 번에 하나만.** 세 건을 한꺼번에 보내면 알림이 쏟아진다.
        # (실제로 같은 종류가 셋 동시에 와서 읽을 수가 없었다)
        rows = (sb.table("molang_outbox")
                .select("id,rule,body,payload,created_at")
                .eq("notified", False)
                .order("id", desc=True).limit(6).execute().data) or []
    except Exception as e:
        return {"sent": 0, "why": str(e)[:60]}
    if not rows:
        return {"sent": 0, "why": "전할 말이 없음"}

    # 무엇에 대한 말인지에 따라 모양을 조금 달리한다
    TITLE = {"peer": "🐰 피우피우랑 이야기했어",
             "new_finding": "🐰 이런 걸 찾았어",
             "dream": "🐰 간밤에 꿈을 꿨어",
             "mood": "🐰 요즘 이래",
             "peek": "🐰 밖이 궁금해",
             "reminisce": "🐰 문득 생각났는데",
             "grew": "🐰 생각이 조금 달라졌어",
             "absence": "🐰 오늘은 어땠어?",
             "waiting": "🐰 그거 어떻게 됐어?",
             "confirm": "🐰 이거 맞아?"}
    TAG = {"peer": "hatching_chick", "dream": "crescent_moon",
           "peek": "eyes", "new_finding": "mag", "mood": "cloud",
           "reminisce": "thought_balloon",
           "waiting": "hourglass", "confirm": "question"}

    # 너무 묵은 말은 이제 와서 보내지 않는다. 지금 하는 말이어야 한다.
    def _fresh(r):
        try:
            from datetime import datetime, timezone
            t = datetime.fromisoformat(
                str(r.get("created_at") or "").replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            import time as _t
            return (_t.time() - t.timestamp()) < 86400 * 2
        except Exception:
            return True

    stale = [r for r in rows if not _fresh(r)]
    rows = [r for r in rows if _fresh(r)]
    for r in stale:          # 묵은 것은 보내지 않되 다시 안 보게 표시
        try:
            sb.table("molang_outbox").update(
                {"notified": True}).eq("id", r["id"]).execute()
        except Exception:
            pass
    if not rows:
        return {"sent": 0, "why": "전할 말이 없음(묵은 것은 건너뜀)"}

    # 답을 폰에서 바로 할 수 있게.
    #
    # 서비스 키를 알림에 담으면 그 키가 ntfy 서버를 지나간다. 그래서
    # **안전한 창구**(ANSWER_URL)로만 보낸다. 없으면 버튼 없이 보낸다.
    answer = (os.environ.get("ANSWER_URL") or "").rstrip("/")

    def _actions(rule, row_id, payload):
        parts = []
        if answer and rule == "confirm":
            fid = (payload or {}).get("fact_id")
            if fid:
                parts.append(
                    f"http, 응 맞아, {answer}/confirm?id={row_id}"
                    f"&fact={fid}&yes=1, method=POST, clear=true")
                parts.append(
                    f"http, 아니야, {answer}/confirm?id={row_id}"
                    f"&fact={fid}&yes=0, method=POST, clear=true")
        if app_url:
            parts.append(f"view, 앱에서 보기, {app_url}")
        return "; ".join(parts[:3])

    # 보낼 것은 한 건. 다만 **직전에 보낸 것과 다른 종류**를 고른다.
    # 흐려진 기억이 많으면 confirm 만 줄줄이 오게 되기 때문이다.
    last_rule = ""
    try:
        got = (sb.table("molang_outbox").select("rule")
               .eq("notified", True).order("id", desc=True)
               .limit(1).execute().data) or []
        last_rule = (got[0].get("rule") if got else "") or ""
    except Exception:
        pass
    other = [r for r in rows if (r.get("rule") or "") != last_rule]
    rows = [(other or rows)[0]]

    done = []
    for r in rows:
        rule = r.get("rule") or ""
        res = send(TITLE.get(rule, "🐰 몰랑이"), r.get("body") or "",
                   tags=TAG.get(rule, "rabbit"), click=app_url,
                   actions=_actions(rule, r.get("id"), r.get("payload")),
                   log=log)
        if not res.get("ok"):
            continue
        try:
            sb.table("molang_outbox").update(
                {"notified": True}).eq("id", r["id"]).execute()
        except Exception:
            pass
        done.append(rule)
        break

    if done:
        log(f"  📣 알림 {len(done)}건 보냄 ({', '.join(done)})")
    return {"sent": len(done), "rules": done}
