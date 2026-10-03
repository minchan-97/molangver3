"""
listening.py — 소리를 들려주면 듣는다.

왜 소리인가
  이 아이들의 관심 윗자리에 늘 '노래'가 있다. 그런데 사진으로는 노래를
  보여줄 수 없다. 소리는 보여줄 수 있다.

어떻게 다루나
  1. 사람이 녹음 버튼을 누른다 (브라우저는 사람이 눌러야 마이크를 켠다)
  2. Whisper 로 글로 옮긴다
  3. 옮긴 글은 **사실로 바로 넣지 않는다** — 격리로 보낸다

왜 격리로 보내나
  녹음에는 곁에 있던 사람의 말이 섞여 들어올 수 있다. 사진보다 민감하다.
  들린 것을 그대로 '사용자가 말한 것' 으로 저장하면, 말한 적 없는 말이
  기억이 된다. 그래서 들은 것은 **확인 거리**로 둔다.
"""
from __future__ import annotations
import io
import re

MAX_SEC = 60
MODEL = "whisper-1"

# 들은 것에서 걸러낼 것 — 사람이 곁에서 한 말로 보이는 조각
PRIVATE = re.compile(r"(비밀번호|주민등록|계좌|카드번호|전화번호)")


def transcribe(raw: bytes, api_key: str, hint: str = "") -> dict:
    """
    소리 → 글. 실패해도 회차를 멈추지 않는다.
    반환: {"text", "ok", "why"}
    """
    if not raw:
        return {"ok": False, "why": "소리가 비었음", "text": ""}
    if not api_key:
        return {"ok": False, "why": "열쇠가 없어 못 들음", "text": ""}
    try:
        from openai import OpenAI
        f = io.BytesIO(raw)
        f.name = "sound.wav"
        cli = OpenAI(api_key=api_key)
        res = cli.audio.transcriptions.create(
            model=MODEL, file=f, language="ko",
            prompt=hint or "일상 대화, 음악, 주변 소리")
        text = (getattr(res, "text", "") or "").strip()
        if not text:
            return {"ok": False, "why": "들리는 말이 없었음", "text": ""}
        if PRIVATE.search(text):
            return {"ok": False, "why": "민감한 말이 섞여 있어 버림",
                    "text": ""}
        return {"ok": True, "text": text[:600], "why": ""}
    except Exception as e:
        return {"ok": False, "why": str(e)[:80], "text": ""}


def to_quarantine(sb, text: str, note: str = "") -> bool:
    """
    들은 것은 사실이 아니라 **확인 거리**로 둔다.
    곁에 있던 사람의 말이 섞일 수 있어, 사람이 보고 정해야 한다.
    """
    if not text:
        return False
    try:
        sb.table("molang_quarantine").insert({
            "text": text[:400],
            "reason": note or "소리로 들은 것 — 확인 필요",
        }).execute()
        return True
    except Exception:
        return False


def context_line(text: str) -> str:
    """대화 프롬프트에 넣을 줄."""
    if not text:
        return ""
    return ("[지금 들려준 소리] " + text[:300] +
            "\n(들은 대로만 말해라. 안 들린 것을 지어내지 마라.)\n")
