"""
lived.py — **겪은 것을 자기 사실로 남긴다.**

왜 비어 있었나
  꿈을 일흔 번 꿨고, 바깥에 수십 번 다녀왔고, 방을 수백 번 옮겼다.
  그런데 "나는 이런 꿈을 꿨다", "나는 숲에 다녀왔다" 가 사실로는
  **한 건도 없었다.** 그 일들이 각자 자기 표에만 쌓이고,
  자기에 대한 앎으로는 이어지지 않았기 때문이다.

  그래서 자기 사실 중 겪은 것은 여행(travel) 뿐이었다.

무엇을 남기나
  **모든 순간을 남기지 않는다.** 방을 옮길 때마다 적으면 사실이
  이동 기록으로 뒤덮인다. 남길 만한 것은 이런 것이다.

    처음    처음 가본 곳, 처음 만난 이
    남은 것 꿈에서 깨어도 남은 낱말
    굳음    무언가를 알게 된 순간
    되풀이  자주 간 곳 (여러 번 쌓이면 '자주 가는 곳' 이 된다)

  한 번의 일은 에피소드고, **되풀이된 것이 자기 앎**이 된다.
  그래서 같은 일이 반복되면 사실이 굳고, 한 번뿐이면 옅어진다.
"""
from __future__ import annotations

MIN_VISITS_FOR_FACT = 3       # 이만큼 다녀야 '자주 가는 곳'이 된다


def _add(ident, text: str, source: str, log=None) -> bool:
    try:
        ident._reinforce_or_add(text, source=source, speaker="molang")
        if log:
            log(f"  🧠 겪은 것 → {text[:40]}")
        return True
    except Exception:
        return False


def from_dream(ident, d: dict, log=print) -> list:
    """
    꿈에서 **깨어도 남은 것**만 적는다.
    꿈 줄거리는 꿈 표에 있다. 여기 적을 것은 '무엇이 남았나' 다.
    """
    out = []
    if not d or not d.get("dreamed"):
        return out
    dr = d.get("dream") or {}
    linger = dr.get("lingering")
    feel = dr.get("feeling")
    if linger:
        if _add(ident, f"몰랑이는 꿈에서 깬 뒤에도 {linger} 생각이 남았다.",
                "dream", log):
            out.append(linger)
    if feel and dr.get("energy", 0) >= 1.0:
        _add(ident, f"몰랑이는 {feel} 느낌의 꿈을 꿨다.", "dream")
    return out


def from_outing(ident, land: dict, went, log=print) -> bool:
    """
    바깥에 다녀온 일.
    **처음 간 곳**과 **자주 간 곳**만 적는다. 매번 적으면 이동 기록이 된다.
    """
    kind = (went.get("kind") if isinstance(went, dict) else went)
    if not kind:
        return False
    for p in (land.get("places") or []):
        if p.get("kind") != kind:
            continue
        n = int(p.get("visits") or 0)
        if n == 1:
            return _add(ident, f"몰랑이는 {kind}에 처음 가봤다.", "land", log)
        if n == MIN_VISITS_FOR_FACT:
            return _add(ident, f"몰랑이는 {kind}에 자주 간다.", "land", log)
    return False


def from_home(ident, h: dict, out: dict, log=print) -> bool:
    """
    집에서 지낸 일.
    방을 옮길 때마다 적지 않는다 — **오래 머문 방**만 적는다.
    """
    room = (out or {}).get("molang")
    if not room:
        return False
    dwell = ((h.get("dwell") or {}).get(room) or 0)
    if dwell and int(dwell) in (10, 30, 60):
        return _add(ident, f"몰랑이는 {room}에 오래 머무는 편이다.",
                    "home", log)
    return False


def from_meeting(ident, who: str, place: str, log=print) -> bool:
    """처음 만난 이. 관계의 시작은 자기 앎이기도 하다."""
    if not who:
        return False
    return _add(ident, f"몰랑이는 {place}에서 {who}를 알게 됐다.",
                "village", log)


def from_growth(ident, grown: dict, log=print) -> bool:
    """무언가가 굳은 순간 — 아는 것이 단단해졌다는 앎."""
    trees = (grown or {}).get("trees") or []
    if not trees:
        return False
    return _add(ident, f"몰랑이는 {trees[0]} 쪽 생각이 깊어졌다.",
                "self", log)
