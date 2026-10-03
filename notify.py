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

MAX_PER_DAY = 6
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
         click: str = "", log=print) -> dict:
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
        rows = (sb.table("molang_outbox")
                .select("id,rule,body,created_at")
                .eq("sent", False).eq("notified", False)
                .order("id", desc=True).limit(3).execute().data) or []
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
             "absence": "🐰 오늘은 어땠어?"}
    TAG = {"peer": "hatching_chick", "dream": "crescent_moon",
           "peek": "eyes", "new_finding": "mag", "mood": "cloud",
           "reminisce": "thought_balloon"}

    done = []
    for r in rows:
        rule = r.get("rule") or ""
        res = send(TITLE.get(rule, "🐰 몰랑이"), r.get("body") or "",
                   tags=TAG.get(rule, "rabbit"), click=app_url, log=log)
        if not res.get("ok"):
            continue
        try:
            sb.table("molang_outbox").update(
                {"notified": True}).eq("id", r["id"]).execute()
        except Exception:
            pass
        done.append(rule)
        if _sent_today(sb) >= MAX_PER_DAY:
            break

    if done:
        log(f"  📣 알림 {len(done)}건 보냄 ({', '.join(done)})")
    return {"sent": len(done), "rules": done}
