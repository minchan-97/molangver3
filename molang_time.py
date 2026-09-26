"""
molang_time.py — 시간을 맥락으로. (한국 시간 KST 기준)

몰랑이가 "오랜만이야", "밤늦게 왔네", "좋은 아침" 같은 걸
실제 시간 흐름에 맞춰 자연스럽게 말하도록 시간 맥락을 만든다.
"""
import time
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))   # 한국 표준시


def now_kst():
    return datetime.now(KST)


def time_context(last_talk_ts):
    """
    마지막 대화 시각(epoch초)과 지금(KST)을 비교해 시간 맥락 문장을 만든다.
    반환: 프롬프트에 주입할 한 줄 (없으면 "")
    """
    now = now_kst()
    hour = now.hour
    parts = []

    # 1. 시간대 (아침/낮/저녁/밤/새벽)
    if 5 <= hour < 9:
        parts.append(f"지금은 이른 아침({hour}시)이야")
    elif 9 <= hour < 12:
        parts.append(f"지금은 오전({hour}시)이야")
    elif 12 <= hour < 14:
        parts.append(f"지금은 점심때({hour}시)야")
    elif 14 <= hour < 18:
        parts.append(f"지금은 오후({hour}시)야")
    elif 18 <= hour < 22:
        parts.append(f"지금은 저녁({hour}시)이야")
    elif 22 <= hour < 24:
        parts.append(f"지금은 밤늦은 시간({hour}시)이야")
    else:  # 0~5시
        parts.append(f"지금은 새벽({hour}시)이야")

    # 2. 마지막 대화로부터 경과
    if last_talk_ts:
        gap = time.time() - last_talk_ts
        if gap < 60 * 10:
            pass  # 방금 대화 중 → 언급 안 함 (자연스럽게)
        elif gap < 60 * 60:
            parts.append("조금 전에 얘기했었어")
        elif gap < 60 * 60 * 6:
            parts.append("몇 시간 만에 다시 왔어")
        elif gap < 60 * 60 * 24:
            parts.append("오늘 안에 다시 왔네")
        elif gap < 60 * 60 * 24 * 3:
            days = int(gap // (60 * 60 * 24))
            parts.append(f"{days}일 만에 다시 만났어")
        elif gap < 60 * 60 * 24 * 14:
            days = int(gap // (60 * 60 * 24))
            parts.append(f"오랜만이야, {days}일 만이야")
        else:
            parts.append("아주 오랜만에 다시 만났어")

    ctx = ", ".join(parts)
    # 시간은 '배경 정보'로만. 인사를 강요하지 않음 (대화가 우선).
    return f"(참고: {ctx}.)" if ctx else ""


def greeting_hint(last_talk_ts):
    """첫 화면 인사말용 힌트 (짧게)."""
    now = now_kst()
    h = now.hour
    if last_talk_ts and (time.time() - last_talk_ts) > 60 * 60 * 24 * 2:
        return "오랜만"
    if 5 <= h < 11:
        return "아침"
    if 22 <= h or h < 5:
        return "밤"
    return "보통"
