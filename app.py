"""
몰랑이 💗 — 내부는 Arcogit, 외부만 몰랑이.
- 내부: UnifiedIdentity (사고계보·자기검증·양심·기억·유형생성이 다 돎)
- 외부: 몰랑이 껍데기 (표정·말투·카톡 UI)
- pkl: 다운로드/업로드로 정체성 보관·이어가기
"""
import os, base64, pickle, io
import streamlit as st
from openai import OpenAI

from unified_identity import UnifiedIdentity
from llm_bridge import (make_choose_fn, make_answer_fn, detect_feedback,
                        make_tree_designer, make_classifier, make_consolidator)
from tree_registry import load_logic_db_types
import molang_skin as skin
import molang_time as mtime
import molang_self as mself
import time as _time
import molang_persist as persist

st.set_page_config(page_title="몰랑이 💗", page_icon="🐰", layout="centered")

st.markdown("""
<style>
.stApp { background:#b2c7d9; }
.chat-head { background:#a9bdcf; padding:10px 14px; border-radius:12px;
  font-weight:700; color:#3d3d3d; margin-bottom:10px;
  display:flex; align-items:center; gap:10px; }
.head-pic { width:42px; height:42px; border-radius:50%; object-fit:cover; border:2px solid #fff; }
.row { display:flex; margin:8px 0; align-items:flex-end; gap:6px; }
.row.me { justify-content:flex-end; }
.prof { width:38px; height:38px; border-radius:50%; object-fit:cover; }
.bubble-you { background:#fff; color:#222; padding:9px 13px;
  border-radius:4px 16px 16px 16px; max-width:70%; font-size:0.95rem; }
.bubble-me { background:#fef01b; color:#222; padding:9px 13px;
  border-radius:16px 4px 16px 16px; max-width:70%; font-size:0.95rem; }
</style>
""", unsafe_allow_html=True)

# API 키: 매번 입력 (사이드바)
if "api_key" not in st.session_state:
    st.session_state.api_key = ""

with st.sidebar:
    st.session_state.api_key = st.text_input(
        "🔑 OpenAI API 키", value=st.session_state.api_key,
        type="password", placeholder="sk-...")

if not st.session_state.api_key:
    st.info("🔑 왼쪽에 OpenAI API 키를 넣으면 몰랑이가 깨어나요 🐰")
    st.stop()

client = OpenAI(api_key=st.session_state.api_key)

def dataurl(b64): return f"data:image/png;base64,{b64}"

# ── 정체성(Arcogit) 초기화 ──
if "unified" not in st.session_state:
    u = UnifiedIdentity()
    load_logic_db_types(u.registry)          # 20종 논리 유형 탑재
    skin.install_molang_persona(u)           # 몰랑이 옷 입힘
    st.session_state.unified = u
    st.session_state.chat = [("molang", "안녕! 나 몰랑이야 🐰💗 오늘 어땠어?", "기쁨")]

u = st.session_state.unified

# LLM 함수 (Arcogit이 쓰는 것)
choose_fn = make_choose_fn(client)
answer_fn = make_answer_fn(client, {})
designer = make_tree_designer(client)
classify_fn = make_classifier(client)
consolidate_fn = make_consolidator(client)

def profile_for(emotion):
    if skin.has_face(u, emotion): return skin.get_face(u, emotion)
    if skin.has_face(u, "보통"):  return skin.get_face(u, "보통")
    return None

# ── 사이드바: 세팅 + pkl 다운/업 ──
with st.sidebar:
    st.markdown("### 🐰 몰랑이 준비")

    # pkl 업로드 (이어가기)
    up = st.file_uploader("💾 저장된 몰랑이 불러오기", type=None)
    if up and st.button("불러오기"):
        try:
            st.session_state.unified = persist.load_molang_bytes(up.getvalue())
            st.session_state.chat = [("molang","다시 만나서 반가워! 🐰💗","기쁨")]
            st.success("몰랑이가 돌아왔어요!"); st.rerun()
        except Exception as e:
            st.error(f"불러오기 실패: {e} (몰랑이 pkl 파일이 맞는지 확인해줘)")

    st.markdown("---")
    st.caption("처음이면: 몰랑이 사진 → 외형학습 → 표정생성")
    base_img = st.file_uploader("기본 몰랑이 사진", type=["png","jpg","jpeg","webp","gif","bmp"])
    if base_img and st.button("① 외형 학습"):
        with st.spinner("얼굴 익히는 중..."):
            b64 = base64.b64encode(base_img.getvalue()).decode()
            feat = skin.extract_appearance(client, b64, base_img.type)
            if feat: skin.set_appearance(u, feat); st.success("외형 기억 완료!")
            else: st.error("실패 (API키 확인)")

    if skin.has_appearance(u) and st.button("② 표정 5종 생성"):
        prog = st.progress(0.0)
        fails = []
        last_err = None
        for i,emo in enumerate(skin.EMOTIONS):
            if not skin.has_face(u, emo):
                fb, err = skin.generate_face(client, skin.get_appearance(u), emo)
                if fb:
                    skin.store_face(u, emo, fb)
                else:
                    fails.append(emo); last_err = err
            prog.progress((i+1)/len(skin.EMOTIONS))
        if fails:
            st.error(f"표정 생성 실패: {', '.join(fails)}")
            if last_err:
                st.warning(f"이유: {last_err}")
        else:
            st.success("표정 완성! 💗")
            st.rerun()

    made = [e for e in skin.EMOTIONS if skin.has_face(u, e)]
    if made:
        st.caption(f"만든 표정: {', '.join(made)}")
        # 미리보기 (생성 확인)
        import base64 as _b64
        cols = st.columns(len(made))
        for c, emo in zip(cols, made):
            try:
                c.image(_b64.b64decode(skin.get_face(u, emo)),
                        caption=emo, width=60)
            except Exception:
                c.caption(f"{emo}?")

    st.markdown("---")
    # pkl 다운로드 (보관) — Arcogit + 표정 통째로
    pkl_bytes = persist.save_molang_bytes(u)
    st.download_button("⬇️ 몰랑이 저장 (.pkl)", data=pkl_bytes,
                       file_name="molang.pkl", mime="application/octet-stream")
    st.caption("대화할수록 몰랑이가 자라요.\n저장해서 다음에 불러오면 이어져요 💗")

# ── 헤더 (현재 감정 프로필) ──
last_emo = st.session_state.chat[-1][2] if st.session_state.chat else "기쁨"
hp = profile_for(last_emo)
head = f'<img src="{dataurl(hp)}" class="head-pic">' if hp else '🐰'
st.markdown(f'<div class="chat-head">{head}몰랑이 💗</div>', unsafe_allow_html=True)
st.caption("🔧 버전 v13 (말투 완급)")  # 이게 보이면 새 코드가 도는 것

# ── 대화 표시 ──
for role,text,emo in st.session_state.chat:
    if role=="me":
        st.markdown(f'<div class="row me"><div class="bubble-me">{text}</div></div>',
                    unsafe_allow_html=True)
    else:
        p = profile_for(emo)
        ph = f'<img src="{dataurl(p)}" class="prof">' if p else '🐰'
        st.markdown(f'<div class="row"><div>{ph}</div>'
                    f'<div class="bubble-you">{text}</div></div>', unsafe_allow_html=True)

# ── 입력 ──
if "photo_key" not in st.session_state:
    st.session_state.photo_key = 0
photo = st.file_uploader("📷 사진 보여주기",
    type=["png","jpg","jpeg","webp","gif","bmp"],
    key=f"ph_{st.session_state.photo_key}")
msg = st.chat_input("몰랑이한테 말 걸기...")

# 이미 처리한 입력인지 체크 (사진 무한 반응 방지)
if msg or photo:
    show = msg or "(사진을 보냈어요 📷)"
    st.session_state.chat.append(("me", show, "보통"))

    with st.spinner("몰랑이가 생각 중... 🐰"):
        # 시간 맥락 (한국시간 KST 기준)
        last_ts = getattr(u, "last_talk_ts", None)
        time_ctx = mtime.time_context(last_ts)
        self_ctx = mself.to_self_prompt(u)   # 자기 인식 (LLM 독립)
        # ── 내부: Arcogit이 생각 (유형판별→트리→기억주입→답) ──
        q = msg or "이 사진 보고 몰랑이답게 반응해줘"
        # 사진이면 answer_fn 대신 직접 vision 호출로 답 생성
        if photo:
            pb = base64.b64encode(photo.getvalue()).decode()
            try:
                r = client.chat.completions.create(model="gpt-4o",
                    messages=[{"role":"system","content":u.identity.to_system_prompt()+"\n"+self_ctx+"\n"+time_ctx},
                        {"role":"user","content":[
                            {"type":"text","text":"이 사진 보고 몰랑이답게 반응해줘!"},
                            {"type":"image_url","image_url":{"url":f"data:{photo.type};base64,{pb}"}}]}],
                    temperature=0.9, max_tokens=300)
                answer = r.choices[0].message.content
            except Exception: answer = "우와 사진이다! 🐰💗"
            result = None
        else:
            bg = self_ctx + ((" " + time_ctx) if time_ctx else "")
            q_with_time = f"사용자가 방금 한 말: \"{q}\"\n{bg}"
            result = u.think(q_with_time, choose_fn=choose_fn, answer_fn=answer_fn,
                             classify_fn=classify_fn, tree_factory=designer)
            answer = result["answer"] or "히힛 🐰"

        emotion = skin.detect_emotion(client, answer)
        # 표정 없으면 생성+캐시 (identity에 저장 → pkl에 같이 감)
        if not skin.has_face(u, emotion) and skin.has_appearance(u):
            fb, _err = skin.generate_face(client, skin.get_appearance(u), emotion)
            if fb: skin.store_face(u, emotion, fb)

        # ── 내부: Arcogit 진화 (피드백 학습 + 기억 흡수) ──
        if result is not None:
            fb_val = detect_feedback(msg or "") if msg else None
            u.react(result, fb_val if fb_val is not None else 0.5,
                    was_corrected=(fb_val is not None and fb_val>0))
        # 대화 맥락은 정체성 기억에 흡수
        u.identity.absorb(show, answer, consolidate_fn=consolidate_fn)
        u.last_talk_ts = _time.time()   # 시간 동기화용
        mself.build_self_model(u)   # 자기 인식 갱신

    st.session_state.chat.append(("molang", answer, emotion))
    if photo:
        st.session_state.photo_key += 1   # 업로더 리셋 → 같은 사진 재반응 방지
    st.rerun()
