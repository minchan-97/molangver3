"""
heartbeat.py — **안 돌고 있는 것을 알아차린다.**

왜 필요했나
  하루에 세 가지를 찾았다. 셋 다 몇 주를 몰랐다.

    여행      `travel` 항목이 로그에 **아예 없었다**.
              떠나는 조건이 영영 참이 될 수 없는 자리에 있었다.
    목적 버튼  눌러도 **아무 일이 안 났다**. 키가 매번 바뀌어서였다.
    근거 먹이기 `fed: 0` 이 **몇 주째** 이어졌다.

  vitals 는 자료가 번지는지를 본다. 자료는 멀쩡했다.
  문제는 **기능이 멈춘 것**이었고, 그건 아무도 안 보고 있었다.

무엇을 보나
  세 가지 꼴이다.

    없음   나와야 할 항목이 로그에 없다
    영     며칠 내리 0 이다
    고정   값은 있는데 안 변한다

  기준을 **미리 적어둔다.** "여행은 열흘에 한 번", "fed 는 사흘에
  한 번". 그래야 안 도는 것을 느낌이 아니라 숫자로 안다.

고치지는 않는다
  알리기만 한다. 무엇을 어떻게 고칠지는 사람이 정한다.
  조용히 꺼져 있는 것보다 **시끄럽게 알려지는 편**이 낫다.
"""
from __future__ import annotations
import time

# 이름: (며칠 안에 한 번은 돌아야 하나, 무엇인가)
EXPECT = {
    "travel":      (12, "여행"),
    "village":     (2,  "마을"),
    "home":        (1,  "집"),
    "land":        (2,  "바깥"),
    "piupiu":      (1,  "피우피우와 이야기"),
    "curiosity":   (1,  "검색"),
    "map":         (2,  "의미 지도"),
    "dream":       (5,  "꿈"),
    "pinko":       (7,  "핀코"),
}

# 이름: (며칠 내리 0 이면 알릴까, 무엇인가)
NONZERO = {
    "growth.memory.fed": (4, "근거 먹이기"),
    "notify.sent":       (3, "알림"),
}

# 이름: (며칠 내리 같으면 알릴까, 무엇인가)
UNCHANGED = {
    "map.nodes":     (5, "지도 마디"),
    "resumed.cycle": (1, "회차"),
}


def _dig(d: dict, path: str):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def record(sb, out: dict) -> bool:
    """이번 회차에 무엇이 돌았는지 적어 둔다."""
    try:
        ran = {k: True for k in EXPECT
               if isinstance(out.get(k), (dict, str, list)) and out.get(k)}
        nums = {k: _dig(out, k) for k in list(NONZERO) + list(UNCHANGED)}
        sb.table("molang_heartbeat").insert({
            "at": time.time(), "mode": out.get("mode"),
            "ran": ran, "nums": nums}).execute()
        return True
    except Exception:
        return False


def check(sb, log=print) -> dict:
    """
    며칠치를 훑어 **멈춘 것**을 찾는다.
    고치지 않는다 — 알리기만 한다.
    """
    try:
        rows = (sb.table("molang_heartbeat")
                .select("at,mode,ran,nums").order("at", desc=True)
                .limit(400).execute().data) or []
    except Exception as e:
        return {"skip": str(e)[:50]}
    if len(rows) < 6:
        return {"skip": f"기록이 {len(rows)}회뿐"}

    now = time.time()
    warn = []

    # 1) 없음 — 나와야 할 것이 며칠째 안 보인다
    for key, (days, what) in EXPECT.items():
        last = None
        for r in rows:
            if (r.get("ran") or {}).get(key):
                last = float(r.get("at") or 0)
                break
        if last is None:
            span = (now - float(rows[-1].get("at") or now)) / 86400
            if span >= days:
                warn.append(f"{what}: 기록 내내 한 번도 안 돎 "
                            f"({span:.0f}일)")
        else:
            gap = (now - last) / 86400
            if gap >= days:
                warn.append(f"{what}: {gap:.0f}일째 안 돎 (기준 {days}일)")

    # 2) 영 — 며칠 내리 0
    for key, (days, what) in NONZERO.items():
        zeros, span = 0, 0.0
        for r in rows:
            v = (r.get("nums") or {}).get(key)
            if v in (None, 0, 0.0):
                zeros += 1
                span = (now - float(r.get("at") or now)) / 86400
            else:
                break
        if zeros >= 3 and span >= days:
            warn.append(f"{what}: {span:.0f}일째 0 (기준 {days}일)")

    # 3) 고정 — 값이 있는데 안 변한다
    for key, (days, what) in UNCHANGED.items():
        vals, span = [], 0.0
        for r in rows:
            v = (r.get("nums") or {}).get(key)
            if v is None:
                continue
            vals.append(v)
            span = (now - float(r.get("at") or now)) / 86400
            if len(set(vals)) > 1:
                break
        if len(vals) >= 4 and len(set(vals)) == 1 and span >= days:
            warn.append(f"{what}: {span:.0f}일째 {vals[0]} 그대로")

    for w in warn:
        log(f"  🔇 {w}")
    return {"warn": warn, "checked": len(rows)}
