"""
council.py — **다 같이 무엇을 만들지 정한다.** 밤에 한 번. LLM 없이.

왜 투표인가
  지금까지 마을에 무엇이 생길지는 **관심의 합**이 정했다. 빵 얘기가
  많이 쌓이면 빵집이 생기는 식이다. 그건 날씨 같은 것이지
  누가 정한 일이 아니다.

  투표는 다르다. **각자 찬성하거나 반대하고, 과반이면 만들어진다.**
  그리고 누가 어느 쪽에 섰는지가 남는다. 그게 사회의 시작이다.

어떻게 정하나 (LLM 없이)
  후보   village.CAN_GROW 중 **아직 없는 것**만 (이름을 새로 짓지 않는다)
  찬성   그 곳의 결 낱말에 자기 관심이 얼마나 걸리는가
  통과   과반

  이름을 스스로 짓게 하면 LLM 이 필요하고 이상한 것이 나올 수 있다.
  목록에서 고르면 결과가 예측 가능하고, **무엇이 왜 생겼는지** 남는다.

무엇이 남나
  누가 무엇에 찬성했는지, 몇 대 몇이었는지, 왜 그랬는지(걸린 낱말).
  그래서 나중에 "이 마을은 어떻게 이렇게 됐나" 를 되짚을 수 있다.
"""
from __future__ import annotations
import random
import time

# 이만큼 걸려야 찬성한다.
#
# 0.3 은 높았다. 결 낱말은 열 개 남짓인데 한 사람이 그중 하나라도
# 또렷이 아는 경우가 드물어, 아무것도 과반을 못 넘었다.
# 마을이 안 커지면 투표를 하는 뜻이 없다.
NEED_INTEREST = 0.1
EVERY_DAYS = 2            # 이만큼 지나야 다시 연다
MIN_VOTERS = 3            # 이보다 적으면 열지 않는다


def _candidates(vil: dict) -> dict:
    """아직 없는 곳들."""
    try:
        import village as V
    except Exception:
        return {}
    have = set((vil.get("places") or {}))
    return {k: w for k, w in V.CAN_GROW.items() if k not in have}


def _voice(interests: dict, words: list) -> float:
    """이 사람이 이 곳에 얼마나 끌리는가."""
    return sum(float((interests or {}).get(w, 0.0)) for w in words)


def due(s: dict) -> bool:
    last = float((s.get("council") or {}).get("at") or 0)
    return (time.time() - last) >= EVERY_DAYS * 86400


def hold(sb, vil: dict, who: dict, s: dict, rng=None, log=print) -> dict:
    """
    모임을 연다. 과반이면 만들어진다.

    who: {이름: {interests, where, …}} — 피우피우와 몰랑이도 넣어 보낸다.
    """
    rng = rng or random.Random(time.time_ns())
    voters = [n for n, v in (who or {}).items() if v]
    if len(voters) < MIN_VOTERS:
        return {"skip": f"모인 사람이 {len(voters)}명뿐"}

    cand = _candidates(vil)
    if not cand:
        return {"skip": "더 만들 것이 없음"}

    # 각 후보에 대해 **각자 얼마나 끌리는지**를 센다
    board = []
    for name, words in cand.items():
        votes, why = {}, {}
        for p in voters:
            pull = _voice((who[p] or {}).get("interests") or {}, words)
            # **자기가 끌리거나, 끌리는 사람이 있으면 따라준다.**
            #
            # 결 낱말을 세 사람이 함께 아는 일은 드물다. 엄격히 보면
            # 아무것도 과반을 못 넘고, 그러면 투표를 하는 뜻이 없다.
            # 마을 일은 혼자 쓰자고 짓는 게 아니다 — 누가 바라면
            # 반대할 이유가 없으면 따라주는 것이 사회다.
            votes[p] = pull >= NEED_INTEREST
            if votes[p]:
                hit = [w for w in words
                       if ((who[p] or {}).get("interests") or {}).get(w)]
                why[p] = hit[:3]
        yes = sum(1 for v in votes.values() if v)
        # 아무도 안 끌리는 곳은 후보로 두지 않는다
        if yes == 0:
            continue

        # **바라는 이가 있고 반대할 이유가 없으면 따라준다.**
        #
        # 관심이 아예 0 인 사람은 '상관없다' 지 '싫다' 가 아니다.
        # 넷 중 셋이 또렷이 바라야 짓는다면 아무것도 안 지어진다
        # (실제로 1:3 으로 계속 떨어졌다). 마을 일은 혼자 쓰자고
        # 짓는 게 아니다 — 바라는 이가 하나라도 있고 말리는 이가
        # 없으면 따라주는 것이 사회다.
        if yes >= 1:
            for p in voters:
                if not votes[p]:
                    opp = _voice((who[p] or {}).get("interests") or {},
                                 words)
                    if opp <= 0:            # 아무 생각 없음 → 따라준다
                        votes[p] = True
                        why.setdefault(p, ["따라줌"])
            yes = sum(1 for v in votes.values() if v)
        board.append({"place": name, "yes": yes, "no": len(voters) - yes,
                      "votes": votes, "why": why,
                      "pull": sum(_voice((who[p] or {}).get("interests") or {},
                                         words) for p in voters)})

    board.sort(key=lambda b: (-b["yes"], -b["pull"]))
    if not board:
        return {"skip": "아무도 끌리는 곳이 없음"}
    top = board[0]
    passed = top["yes"] * 2 > len(voters)

    rec = {"at": time.time(), "voters": voters,
           "picked": top["place"] if passed else None,
           "tally": [(b["place"], b["yes"], b["no"]) for b in board[:5]],
           "why": top["why"], "passed": passed}
    s.setdefault("councils", []).append(rec)
    s["council"] = {"at": rec["at"]}
    s["councils"] = s["councils"][-40:]

    if not passed:
        if log:
            log(f"  🗳️ 모임: 아무것도 과반을 못 넘음 "
                f"(가장 많았던 건 {top['place']} {top['yes']}표)")
        return rec

    # 과반이면 만든다.
    # **이미 있으면 짓지 않는다** — 후보를 추릴 때 걸렀어도,
    # 같은 모임에서 두 번 통과하는 일을 막는다.
    if top["place"] in (vil.get("places") or {}):
        rec["passed"] = False
        rec["skip"] = "이미 있음"
        return rec
    try:
        import village as V
        at = V._free_spot(vil, V.CAN_GROW[top["place"]])
        vil.setdefault("places", {})[top["place"]] = {
            "at": at, "born_at": time.time(), "by": "council"}
        rec["built"] = True
        if log:
            log(f"  🗳️ 모임: **{top['place']}** 을(를) 짓기로 했다 "
                f"({top['yes']}:{top['no']}) — "
                + ", ".join(f"{p}({','.join(w)})"
                            for p, w in list(top['why'].items())[:3]))
    except Exception as e:
        rec["error"] = str(e)[:60]
    return rec


def history(s: dict, n: int = 10) -> list:
    return (s.get("councils") or [])[-n:]


def describe(s: dict) -> str:
    cs = s.get("councils") or []
    built = [c["picked"] for c in cs if c.get("picked")]
    return (f"[모임] {len(cs)}번 열림 · 지은 것 {len(built)}곳"
            + (f" ({', '.join(built[-3:])})" if built else ""))
