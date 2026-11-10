"""
internalize.py — 사람의 승인/거절을 '판단 축(judgment_rules)'으로 굳힌다.

왜 필요했나
  scaffold 리포트가 계속 지적한 것: approved_in_axis=0, rejected_used_as_rule=0.
  몰랑이는 사람의 승인/거절을 '그 순간의 사실'로만 쌓고, '앞으로의 판단 기준'으로
  내면화하지 못했다. 그래서 비슷한 걸 자꾸 다시 물었다(distinct_questions 계속 증가).

철학 (몰랑이의 '축은 함부로 안 바뀐다'를 지킨다)
  · 한 번의 승인/거절로 축을 바꾸지 않는다. 그건 표류다.
  · 같은 '주제'의 승인/거절이 CONFIRM_AT 번 쌓이면, 그제야 규칙으로 굳힌다.
    = 한 경험이 아니라 반복된 경험이 신념이 되는, 사람의 방식.
  · 규칙은 judgment_rules 에 들어가 system prompt 의 '[너의 판단 기준]'이 된다.
  · 이미 있는 축과 부딪히면 굳히지 않는다(conscience 의 안정성 유지).

저장
  molang_axis_log: 승인/거절 하나하나의 기록 (주제·방향)
  judgment_rules(molang_identity.rules): 굳어진 판단 축
"""
from __future__ import annotations
import re
from collections import Counter

CONFIRM_AT = 3          # 같은 주제가 이만큼 확인되면 규칙으로 굳힌다
MAX_RULES = 40          # 판단 축이 너무 불어나지 않게
_STOP = {"그리고", "하지만", "그것", "이것", "저것", "에서", "으로", "하는",
         "있는", "같은", "너무", "정말", "그냥", "약간"}


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[가-힣a-zA-Z0-9]{2,}", text or "")
    return [w for w in words if w not in _STOP]


def _topic(text: str) -> str:
    """승인/거절된 내용의 대표 주제(가장 뜻 있는 명사류 1~2개)."""
    kw = _keywords(text)
    if not kw:
        return ""
    # 긴 낱말을 주제로 (짧은 조사·접속보다 내용어일 확률이 높다)
    kw.sort(key=len, reverse=True)
    return " ".join(kw[:2])


def record(sb, text: str, direction: str):
    """승인('approve') 또는 거절('reject') 하나를 축 로그에 남긴다."""
    topic = _topic(text)
    if not topic:
        return
    try:
        sb.table("molang_axis_log").insert({
            "topic": topic, "direction": direction,
            "sample": (text or "")[:200]}).execute()
    except Exception:
        pass


def _existing_rule_topics(rules: list[str]) -> set[str]:
    out = set()
    for r in rules:
        out |= set(_keywords(r))
    return out


def consolidate(sb, identity) -> dict:
    """
    축 로그를 보고, 같은 주제가 CONFIRM_AT 번 이상 같은 방향으로 확인됐으면
    판단 규칙으로 굳힌다. 돌려주는 값: {added: [...], note}.
    """
    try:
        logs = (sb.table("molang_axis_log").select("topic,direction,used")
                .execute().data) or []
    except Exception:
        return {"added": [], "note": "로그 없음"}

    # 아직 규칙이 안 된 것만, 주제+방향으로 센다
    pending = [r for r in logs if not r.get("used")]
    counts = Counter((r["topic"], r["direction"]) for r in pending if r.get("topic"))

    rules = list(getattr(identity, "judgment_rules", []) or [])
    have = _existing_rule_topics(rules)
    added = []

    for (topic, direction), n in counts.most_common():
        if n < CONFIRM_AT:
            continue
        if len(rules) >= MAX_RULES:
            break
        tkw = set(_keywords(topic))
        if tkw & have:                 # 이미 그 주제의 축이 있으면 건드리지 않는다
            continue
        if direction == "approve":
            rule = f"'{topic}'에 관한 것은 받아들이는 편이다 (사람이 여러 번 그렇게 확인함)."
        else:
            rule = f"'{topic}'에 관한 것은 받아들이지 않는 편이다 (사람이 여러 번 그렇게 확인함)."
        rules.append(rule)
        have |= tkw
        added.append(rule)

    if not added:
        return {"added": [], "note": "아직 굳을 만큼 반복되지 않음"}

    # 판단 축에 반영하고 저장
    identity.judgment_rules = rules
    try:
        sb.table("molang_identity").update(
            {"rules": rules}).eq("owner", getattr(identity, "owner", "molang")).execute()
    except Exception:
        pass
    # 굳힌 로그는 used 로 표시 (다시 세지 않게)
    try:
        for (topic, direction), n in counts.most_common():
            if n >= CONFIRM_AT:
                sb.table("molang_axis_log").update({"used": True}) \
                  .eq("topic", topic).eq("direction", direction).execute()
    except Exception:
        pass
    return {"added": added, "note": f"{len(added)}개의 판단 축이 새로 굳음"}
