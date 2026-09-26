"""
molang_persist.py — 몰랑이 통째로 저장/복원.

Arcogit(UnifiedIdentity) + 몰랑이 표정/외형을 하나의 pkl 번들로 묶는다.
UnifiedIdentity 원본 save/load를 건드리지 않고 감싸는 방식.
"""
import pickle
import tempfile
import os
from unified_identity import UnifiedIdentity
import molang_skin as skin


def save_molang_bytes(unified) -> bytes:
    """몰랑이 전체(Arcogit + 표정)를 bytes로. 다운로드용."""
    # 1. Arcogit 부분을 임시 파일로 저장 후 읽기
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pkl")
    tmp.close()
    unified.save(tmp.name)
    with open(tmp.name, "rb") as f:
        arcogit_blob = f.read()
    os.unlink(tmp.name)

    # 2. 몰랑이 껍데기 부분
    bundle = {
        "arcogit": arcogit_blob,
        "molang_faces": getattr(unified, "molang_faces", {}),
        "molang_appearance": getattr(unified, "molang_appearance", None),
        "last_talk_ts": getattr(unified, "last_talk_ts", None),
        "self_model": getattr(unified, "self_model", None),
    }
    return pickle.dumps(bundle)


def load_molang_bytes(raw: bytes) -> UnifiedIdentity:
    """다운로드된 bytes에서 몰랑이 전체 복원."""
    bundle = pickle.loads(raw)

    # 하위호환: 예전 순수 Arcogit pkl이면 그대로 로드
    if not isinstance(bundle, dict) or "arcogit" not in bundle:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pkl")
        tmp.write(raw); tmp.close()
        u = UnifiedIdentity.load(tmp.name)
        os.unlink(tmp.name)
        skin.install_molang_persona(u)
        return u

    # 1. Arcogit 복원
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pkl")
    tmp.write(bundle["arcogit"]); tmp.close()
    u = UnifiedIdentity.load(tmp.name)
    os.unlink(tmp.name)

    # 2. 몰랑이 껍데기 복원
    skin.install_molang_persona(u)
    u.molang_faces = bundle.get("molang_faces", {})
    u.molang_appearance = bundle.get("molang_appearance", None)
    u.last_talk_ts = bundle.get("last_talk_ts", None)
    u.self_model = bundle.get("self_model", None)
    import molang_self as _ms
    _ms.ensure_self_model(u)   # 없으면 기존 데이터로 자동생성 (하위호환)
    return u
