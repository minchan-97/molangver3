"""
molang_norm.py — 정규화/중복판정/종류분류 공용 모듈.

02_migrate.py와 molang_store.py가 반드시 같은 규칙을 써야 한다.
이관 때와 운영 때 norm_key 계산이 다르면 unique 인덱스가 무의미해진다.
"""
import re
from datetime import timedelta

_PARTICLES = r'(은|는|이|가|을|를|의|에|에서|로|으로|와|과|도|만|랑|이랑)'

ECHO_MARKERS = ['히힛', '💖', '💗', '✨', '🐰', '오, 찬기야', '몰랑이는', '고마워!']

# 주의: '있다.' 같은 넓은 패턴은 '여자친구가 있다'(영속 사실)까지
# 상태로 잡는다. 위치/시점 표지를 요구하도록 좁혔다.
STATE_PATTERNS = [
    '현재', '지금', '방금', '오늘',
    '에 있다', '에 누워', '누워있', '중이다', '중이야', '중인',
    '계획이다', '할 계획', '까지 해야', '까지 있어야',
]

# 신념 서술은 상태가 아니다. 이 어미가 있으면 상태 판정을 취소한다.
BELIEF_SUFFIXES = ['고 생각한다', '고 여긴다', '고 믿는다', '고 본다']

PREF_PATTERNS = ['좋아한다', '싫어한다', '선호', '중요하게 생각']

TTL = {
    'state': timedelta(hours=12),
    'fact': None,
    'preference': None,
}


def normalize(text: str) -> str:
    t = text.strip()
    t = re.sub(r'^(사용자|찬기|민찬기)', '찬기', t)
    t = re.sub(r'[^\w가-힣 ]', '', t)
    t = re.sub(r'\s+', ' ', t)
    t = re.sub(_PARTICLES + r'\b', '', t)
    return t.strip()


def tokens(text: str) -> set:
    return set(normalize(text).split())


def jaccard(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_assistant_echo(text: str) -> bool:
    """몰랑이 자기 답변이 사실로 저장되려는 것인지."""
    hits = sum(1 for m in ECHO_MARKERS if m in text)
    if hits >= 2:
        return True
    if text.startswith(('오,', '아,', '우와', '와,')) and hits >= 1:
        return True
    if len(text) > 55 and not text.rstrip().endswith(('다', '다.')):
        return True
    return False


def classify_kind(text: str) -> str:
    t = text.rstrip('. ')
    is_belief = any(t.endswith(b) or b in t for b in BELIEF_SUFFIXES)
    if not is_belief and any(p in text for p in STATE_PATTERNS):
        return 'state'
    if any(p in text for p in PREF_PATTERNS) or is_belief:
        return 'preference'
    return 'fact'
