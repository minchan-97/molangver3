"""
mapsource.py — **어느 지도를 쓸지 여기서 하나로 정한다.**

왜 한 곳인가
  지도를 읽는 데가 여섯 군데다 (꺼내기·중력·피우피우·앱·내보내기·워커).
  거기를 하나씩 고치면, 되돌릴 때도 하나씩 고쳐야 한다.
  그러면 "문제가 생기면 되돌리면 된다" 가 말뿐이 된다.

  그래서 **읽는 곳은 전부 여기를 거친다.** 바꾸는 것도 되돌리는 것도
  이 파일의 한 줄이다.

두 지도는 계속 그려진다
  밤마다 둘 다 그린다. 쓰는 것만 고른다.
    molang_map    기존 — 함께 나온 횟수로만
    molang_map_v  벡터 — 뜻이 가까우면 겪지 않아도 잇는다

  그래야 벡터 쪽이 이상하면 USE 를 "old" 로 되돌리기만 하면 된다.
  지난 지도가 그대로 있으니 잃는 것이 없다.
"""
from __future__ import annotations
import os

# "vector" 또는 "old".  환경변수 MOLANG_MAP 으로도 바꿀 수 있다.
USE = os.environ.get("MOLANG_MAP", "vector")


def which() -> str:
    return "벡터 지도" if USE == "vector" else "기존 지도"


def load(sb) -> tuple:
    """
    지금 쓰기로 한 지도. 없으면 **조용히 기존 것으로 돌아간다.**
    (벡터 지도가 아직 안 그려진 밤이 있을 수 있다)
    """
    if USE == "vector":
        try:
            import semantic_map_v as SV
            g, c = SV.load(sb)
            if g and (g.get("edges") or g.get("freq")):
                return g, c
        except Exception:
            pass
    import semantic_map as SM
    return SM.load(sb)


def load_old(sb) -> tuple:
    """기존 지도를 그대로. 견줄 때 쓴다."""
    import semantic_map as SM
    return SM.load(sb)
