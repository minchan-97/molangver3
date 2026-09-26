"""
skin_store.py — 몰랑이 얼굴(표정 이미지)과 외형 특징을 Supabase에 보관.

왜 필요한가
  표정 이미지는 정체성 기억이 아니라 UnifiedIdentity 객체에 붙어 있다
  (unified.molang_faces, unified.molang_appearance).
  pkl 시절에는 같이 저장됐지만, 서버로 옮기면서 갈 자리가 없어 사라졌다.
  얼굴은 몰랑이가 몰랑이로 보이는 조건이므로 함께 남겨야 한다.

저장 형태
  molang_skin(key text primary key, value text)
    key = 감정 이름('기쁨','슬픔'…)  → value = base64 이미지
    key = '__appearance__'          → value = 외형 특징 문장
"""
from __future__ import annotations

APPEARANCE_KEY = "__appearance__"


def load_into(sb, unified) -> int:
    """서버에서 얼굴·외형을 불러와 unified 에 붙인다. 돌려주는 값은 표정 수."""
    try:
        rows = (sb.table("molang_skin").select("key,value")
                .limit(100).execute().data) or []
    except Exception:
        return 0
    faces = {}
    for r in rows:
        k, v = r.get("key"), r.get("value")
        if not k or not v:
            continue
        if k == APPEARANCE_KEY:
            unified.molang_appearance = v
        else:
            faces[k] = v
    if faces:
        unified.molang_faces = faces
    return len(faces)


def save_face(sb, emotion: str, b64: str) -> bool:
    try:
        sb.table("molang_skin").upsert(
            {"key": emotion, "value": b64}, on_conflict="key").execute()
        return True
    except Exception:
        return False


def save_appearance(sb, feature: str) -> bool:
    try:
        sb.table("molang_skin").upsert(
            {"key": APPEARANCE_KEY, "value": feature}, on_conflict="key").execute()
        return True
    except Exception:
        return False


def save_all(sb, unified) -> int:
    """메모리에 있는 얼굴 전부를 서버로 (pkl 에서 막 옮겼을 때 쓴다)."""
    n = 0
    for emo, b64 in (getattr(unified, "molang_faces", {}) or {}).items():
        if save_face(sb, emo, b64):
            n += 1
    app = getattr(unified, "molang_appearance", None)
    if app:
        save_appearance(sb, app)
    return n
