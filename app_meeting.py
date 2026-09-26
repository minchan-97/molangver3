"""
몰랑이 만남 💗🐰🐰 — 두 몰랑이가 서로 대화.
찬기 몰랑이 pkl + 여친 몰랑이 pkl → 서로 인사하고 알아감.
- 자동 대화 (N턴 자동)
- 한 턴씩 (버튼으로 하나씩)
- 각 몰랑이 프로필이 감정 따라 바뀜
- 만남 후 각자 뭘 배웠나 확인
"""
import os, base64
import streamlit as st
from openai import OpenAI

import molang_persist as persist
import molang_skin as skin
import molang_meeting as meet

st.set_page_config(page_title="몰랑이 만남 🐰🐰", page_icon="💗", layout="centered")

st.markdown("""
<style>
.stApp { background:#edd7e6; }
.mtitle { text-align:center; font-weight:800; color:#8a5a7a; margin-bottom:8px; }
.rowA { display:flex; margin:8px 0; align-items:flex-end; gap:6px; justify-content:flex-start; }
.rowB { display:flex; margin:8px 0; align-items:flex-end; gap:6px; justify-content:flex-end; }
.prof { width:44px; height:44px; border-radius:50%; object-fit:cover; border:2px solid #fff; }
.bubA { background:#fff; color:#222; padding:9px 13px; border-radius:4px 16px 16px 16px; max-width:65%; }
.bubB { background:#ffd7ef; color:#222; padding:9px 13px; border-radius:16px 4px 16px 16px; max-width:65%; }
.nm { font-size:0.7rem; color:#8a5a7a; }
</style>
""", unsafe_allow_html=True)

def dataurl(b64): return f"data:image/png;base64,{b64}"

# ── API 키 ──
if "api_key" not in st.session_state: st.session_state.api_key = ""
with st.sidebar:
    st.session_state.api_key = st.text_input("🔑 OpenAI API 키",
        value=st.session_state.api_key, type="password", placeholder="sk-...")
if not st.session_state.api_key:
    st.info("🔑 왼쪽에 API 키를 넣어줘"); st.stop()
client = OpenAI(api_key=st.session_state.api_key)

st.markdown('<div class="mtitle">🐰 몰랑이 만남 🐰</div>', unsafe_allow_html=True)
st.caption("두 몰랑이가 만나서 서로 알아가요 💗")

# ── 두 몰랑이 불러오기 ──
with st.sidebar:
    st.markdown("### 두 몰랑이 불러오기")
    fa = st.file_uploader("🐰 몰랑이 A (예: 찬기)", type=None, key="fa")
    fb = st.file_uploader("🐰 몰랑이 B (예: 여친)", type=None, key="fb")
    if st.button("만나게 하기 💗", disabled=not(fa and fb)):
        try:
            st.session_state.mol_a = persist.load_molang_bytes(fa.getvalue())
            st.session_state.mol_b = persist.load_molang_bytes(fb.getvalue())
            st.session_state.transcript = []
            st.session_state.turn = "a"
            st.success("두 몰랑이가 만났어요!")
        except Exception as e:
            st.error(f"불러오기 실패: {e}")

if "mol_a" not in st.session_state:
    st.info("← 사이드바에서 두 몰랑이 pkl을 올리고 '만나게 하기'를 눌러줘 🐰🐰")
    st.stop()

mol_a, mol_b = st.session_state.mol_a, st.session_state.mol_b

def prof(mol, emotion):
    if skin.has_face(mol, emotion): return skin.get_face(mol, emotion)
    if skin.has_face(mol, "보통"):  return skin.get_face(mol, "보통")
    return None

# ── 대화 표시 ──
for msg in st.session_state.transcript:
    mol = mol_a if msg["who"]=="a" else mol_b
    p = prof(mol, msg["emotion"])
    ph = f'<img src="{dataurl(p)}" class="prof">' if p else '🐰'
    if msg["who"]=="a":
        st.markdown(f'<div class="rowA">{ph}<div class="bubA">{msg["text"]}</div></div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="rowB"><div class="bubB">{msg["text"]}</div>{ph}</div>',
                    unsafe_allow_html=True)

# ── 조작 버튼 ──
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("▶ 한 턴"):
        st.session_state.transcript, st.session_state.turn = meet.meet_turn(
            client, mol_a, mol_b, st.session_state.transcript, st.session_state.turn)
        st.rerun()
with col2:
    n = st.selectbox("자동 턴수", [4,6,8,10], label_visibility="collapsed")
with col3:
    if st.button(f"⏩ 자동 {n}턴"):
        with st.spinner("두 몰랑이가 도란도란... 🐰💬🐰"):
            for _ in range(n):
                st.session_state.transcript, st.session_state.turn = meet.meet_turn(
                    client, mol_a, mol_b, st.session_state.transcript, st.session_state.turn)
        st.rerun()

# ── 만남 후 배운 것 ──
if st.session_state.transcript:
    st.markdown("---")
    st.markdown("#### 만남 후 각자 배운 것 💭")
    c1, c2 = st.columns(2)
    with c1:
        st.caption("🐰 몰랑이 A")
        for f in meet.learned_summary(mol_a, 3):
            st.write(f"- {str(f)[:50]}")
    with c2:
        st.caption("🐰 몰랑이 B")
        for f in meet.learned_summary(mol_b, 3):
            st.write(f"- {str(f)[:50]}")

    # 만남 후 각 몰랑이 저장 (진화한 상태로)
    st.markdown("---")
    cc1, cc2 = st.columns(2)
    with cc1:
        st.download_button("⬇️ A 저장", data=persist.save_molang_bytes(mol_a),
                           file_name="molang_A_after.pkl", mime="application/octet-stream")
    with cc2:
        st.download_button("⬇️ B 저장", data=persist.save_molang_bytes(mol_b),
                           file_name="molang_B_after.pkl", mime="application/octet-stream")
