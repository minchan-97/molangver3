"""
molang_auth.py — 비밀번호 게이트.

session_state로 시도 횟수를 세면 새로고침으로 리셋된다.
Supabase 테이블에 남겨야 실제 방어가 된다.

secrets.toml:
    MOLANG_PW_HASH = "<sha256 hex>"
    MOLANG_PW_SALT = "<임의 문자열>"

해시 생성:
    python -c "import hashlib;print(hashlib.sha256(('SALT'+'비밀번호').encode()).hexdigest())"
"""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import streamlit as st

KST = timezone(timedelta(hours=9))
MAX_FAILS = 5
WINDOW = timedelta(minutes=15)


def _hash(salt: str, pw: str) -> str:
    return hashlib.sha256((salt + pw).encode()).hexdigest()


def _recent_fails(sb) -> int:
    since = (datetime.now(KST) - WINDOW).isoformat()
    res = sb.table('molang_auth_attempts').select('id', count='exact') \
        .eq('ok', False).gte('created_at', since).execute()
    return res.count or 0


def gate(sb) -> bool:
    """통과하면 True. 아니면 화면을 잠그고 st.stop()."""
    if st.session_state.get('authed'):
        return True

    st.markdown('### 🔒')
    pw = st.text_input('비밀번호', type='password',
                       label_visibility='collapsed',
                       placeholder='비밀번호')

    if not pw:
        st.stop()

    fails = _recent_fails(sb)
    if fails >= MAX_FAILS:
        st.error('시도 횟수 초과. 15분 후 다시 시도하세요.')
        st.stop()

    expected = st.secrets['MOLANG_PW_HASH']
    salt = st.secrets['MOLANG_PW_SALT']
    ok = hmac.compare_digest(_hash(salt, pw), expected)

    sb.table('molang_auth_attempts').insert({'ok': ok}).execute()

    if not ok:
        st.error(f'틀렸습니다. ({fails + 1}/{MAX_FAILS})')
        st.stop()

    st.session_state.authed = True
    st.rerun()
    return True
