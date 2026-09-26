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

# ── Supabase 연결 + 비밀번호 게이트 (어떤 데이터 접근보다 앞) ──
from supabase import create_client
import molang_auth
from molang_store import SupabaseIdentity

@st.cache_resource
def _sb():
    return create_client(st.secrets["SUPABASE_URL"],
                         st.secrets["SUPABASE_SERVICE_KEY"])

sb = _sb()
molang_auth.gate(sb)          # 통과 못 하면 여기서 멈춤

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

# API 키: secrets 에 있으면 그걸 쓰고, 없을 때만 물어본다
if "api_key" not in st.session_state:
    st.session_state.api_key = st.secrets.get("OPENAI_API_KEY", "")

if not st.session_state.api_key:
    with st.sidebar:
        st.session_state.api_key = st.text_input(
            "🔑 OpenAI API 키", type="password", placeholder="sk-...")

if not st.session_state.api_key:
    st.info("🔑 secrets.toml 에 OPENAI_API_KEY 를 넣어주세요 🐰")
    st.stop()

client = OpenAI(api_key=st.session_state.api_key)

def dataurl(b64): return f"data:image/png;base64,{b64}"

# ── 정체성(Arcogit) 초기화 ──
if "unified" not in st.session_state:
    u = UnifiedIdentity()
    load_logic_db_types(u.registry)          # 20종 논리 유형 탑재
    skin.install_molang_persona(u)           # 몰랑이 옷 입힘 (기본값)
    # 정체성을 서버로. skin 다음에 붙여야 DB의 persona 가 이긴다.
    u.identity = SupabaseIdentity(sb)
    # 사고 트리(판단 구조)도 서버에서 복원 — 없으면 기본 유형으로 시작
    import registry_store, skin_store, purpose
    _n = registry_store.load_into(sb, u.registry)
    st.session_state._tree_restored = _n
    skin.install_molang_persona(u)      # molang_faces 자리 보장
    skin_store.load_into(sb, u)         # 서버에 있는 얼굴·외형 복원
    # 목적(왜 사는가)을 정체성 앞에 세운다 — 서버 persona 가 비어 있을 때만
    try:
        if not (u.identity.persona or "").strip():
            u.identity.persona = purpose.to_prompt()
            u.identity.save_identity()
    except Exception:
        pass
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

    # 이제 정체성은 서버(Supabase)에 있다. pkl 은 '처음 한 번 옮기기'에만 쓴다.
    # 표정만 따로 옮기기 (사실은 이미 옮겼고 얼굴만 없을 때)
    _faces_n = len(getattr(u, "molang_faces", {}) or {})
    with st.expander("🐰 예전 몰랑이 얼굴 가져오기",
                     expanded=(_faces_n == 0)):
        if True:
            st.caption(f"지금 표정 {_faces_n}개. pkl 을 올리면 표정과 외형만 꺼내 "
                       "서버에 넣어요. 사실·기억은 건드리지 않아요.")
            _fup = st.file_uploader("molang.pkl", type=None, key="skin_pkl")
            if _fup and st.button("표정만 가져오기"):
                try:
                    import skin_store
                    _old = persist.load_molang_bytes(_fup.getvalue())
                    _faces = getattr(_old, "molang_faces", None) or {}
                    _app = getattr(_old, "molang_appearance", None)
                    if not _faces and not _app:
                        st.warning("이 pkl 에는 표정이 없네요.")
                    else:
                        u.molang_faces = dict(_faces)
                        if _app:
                            u.molang_appearance = _app
                        _n = skin_store.save_all(sb, u)
                        st.success(f"표정 {_n}개를 서버에 넣었어요 🐰")
                        st.rerun()
                except Exception as e:
                    st.error(f"가져오기 실패: {e}")

    _facts_n = len(u.identity.learned_facts)
    st.caption(f"☁️ 서버 연결됨 · 사실 {_facts_n}개 · 대화 {len(u.identity.episodic)}회 "
               f"· 사고유형 {len(u.registry.trees)}개 "
               f"· 표정 {len(getattr(u, 'molang_faces', {}) or {})}개")
    with st.expander("📦 예전 몰랑이(pkl) 옮기기", expanded=(_facts_n == 0)):
        if True:
            up = st.file_uploader("molang.pkl", type=None, key="mig_pkl")
            if up and st.button("서버로 옮기기"):
                try:
                    old = persist.load_molang_bytes(up.getvalue())
                    n = 0
                    for f in (getattr(old.identity, "learned_facts", []) or []):
                        try:
                            u.identity._reinforce_or_add(
                                f["text"] if isinstance(f, dict) else str(f),
                                source="migration")
                            n += 1
                        except Exception:
                            pass
                    if getattr(old.identity, "persona", None):
                        u.identity.persona = old.identity.persona
                        u.identity.save_identity()
                    # 얼굴·외형도 같이 옮긴다 (pkl 에만 있던 것)
                    import skin_store
                    if getattr(old, "molang_faces", None):
                        u.molang_faces = old.molang_faces
                    if getattr(old, "molang_appearance", None):
                        u.molang_appearance = old.molang_appearance
                    _f = skin_store.save_all(sb, u)
                    st.success(f"사실 {n}개, 표정 {_f}개를 서버로 옮겼어요.")
                    st.rerun()
                except Exception as e:
                    st.error(f"옮기기 실패: {e}")

    # 검토 대기 — 검토함이 두 곳이다(대화에서 격리된 사실 + 워커가 찾아온 관측).
    # 앱이 한 쪽만 읽어서 워커가 격리해도 0으로 보이던 문제를 고쳤다.
    import review_box
    _cnt = review_box.counts(sb, u.identity)
    _q = review_box.pending(sb, u.identity, 20)
    _bump = st.session_state.get("_last_bumped")
    if _bump:
        st.caption(f"🌱 요즘 관심: {', '.join(_bump[:5])}")

    st.markdown("---")
    st.markdown(f"### 🧪 검토 대기 {_cnt['total']}")
    st.caption(f"대화에서 {_cnt['fact']}건 · 워커가 찾은 것 {_cnt['observation']}건")
    if not _q:
        st.caption("지금은 없어요. 대화하거나 워커가 돌면 여기에 쌓여요.")
    else:
        for _item in _q[:8]:
            c1, c2, c3 = st.columns([5, 1, 1])
            _mark = "💬" if _item["where"] == "fact" else "🔎"
            c1.caption(f"{_mark} {_item['title']}")
            c1.caption(f"　{_item['reason']}")
            if _item.get("url"):
                c1.caption(f"　{_item['url'][:50]}")
            _k = f"{_item['where']}_{_item['id']}"
            if c2.button("○", key=f"ok_{_k}", help="맞아요 / 쓸 만해요"):
                review_box.approve(sb, u.identity, _item); st.rerun()
            if c3.button("×", key=f"no_{_k}", help="아니에요"):
                review_box.reject(sb, u.identity, _item); st.rerun()

    st.markdown("---")
    st.caption("처음이면: 몰랑이 사진 → 외형학습 → 표정생성")
    base_img = st.file_uploader("기본 몰랑이 사진", type=["png","jpg","jpeg","webp","gif","bmp"])
    if base_img and st.button("① 외형 학습"):
        with st.spinner("얼굴 익히는 중..."):
            b64 = base64.b64encode(base_img.getvalue()).decode()
            feat = skin.extract_appearance(client, b64, base_img.type)
            if feat:
                skin.set_appearance(u, feat)
                import skin_store; skin_store.save_appearance(sb, feat)
                st.success("외형 기억 완료!")
            else: st.error("실패 (API키 확인)")

    if skin.has_appearance(u) and st.button("② 표정 5종 생성"):
        prog = st.progress(0.0)
        fails = []
        last_err = None
        for i,emo in enumerate(skin.EMOTIONS):
            if not skin.has_face(u, emo):
                fb, err = skin.generate_face(client, skin.get_appearance(u), emo)
                if fb:
                    import skin_store; skin_store.save_face(sb, emo, fb)
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
    # 정체성이 서버에 있으면 pkl 로는 저장할 수 없다(접속 객체는 pickle 불가).
    # 서버판에서는 내용만 JSON 으로 내려받는다. 어차피 원본은 Supabase 다.
    if isinstance(u.identity, SupabaseIdentity):
        import json as _json
        try:
            _backup = {
                "persona": u.identity.persona,
                "values": u.identity.values,
                "rules": u.identity.judgment_rules,
                "facts": [{"text": f.get("text"), "strength": f.get("strength"),
                           "source": f.get("source")} for f in u.identity.learned_facts],
                "episodes": list(u.identity.episodic)[-100:],
            }
            st.download_button(
                "⬇️ 백업 받기 (.json)",
                data=_json.dumps(_backup, ensure_ascii=False, indent=2),
                file_name="molang_backup.json", mime="application/json")
            st.caption("정체성은 서버에 있어요. 이건 읽기용 사본이에요 💗")
        except Exception as e:
            st.caption(f"백업 준비 실패: {e}")
    else:
        pkl_bytes = persist.save_molang_bytes(u)
        st.download_button("⬇️ 백업 받기 (.pkl)", data=pkl_bytes,
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
            if fb:
                import skin_store; skin_store.save_face(sb, emotion, fb)
            if fb: skin.store_face(u, emotion, fb)

        # ── 내부: Arcogit 진화 (피드백 학습 + 기억 흡수) ──
        if result is not None:
            fb_val = detect_feedback(msg or "") if msg else None
            u.react(result, fb_val if fb_val is not None else 0.5,
                    was_corrected=(fb_val is not None and fb_val>0))
        # 대화 맥락은 정체성 기억에 흡수
        u.identity.absorb(show, answer, consolidate_fn=consolidate_fn,
                          source="user", emotion=emotion)
        try:                       # 판단 경로를 감사 기록으로 (사고 계보)
            u.identity.audit(type_id=(result["type"] if result else "vision"),
                             path=(result["path"] if result else []),
                             answer=answer)
        except Exception:
            pass
        u.last_talk_ts = _time.time()   # 시간 동기화용
        try:                     # 대화로 바뀐 판단 구조를 서버에 남긴다
            import registry_store
            registry_store.save(sb, u.registry)
        except Exception:
            pass
        # 대화가 관심사로 스며들게 — 여러 번 나온 말만, 작은 가중치로.
        # (한 번 말했다고 바로 파헤치지 않는다. 확신이 천천히 굳는 것과 같은 결)
        try:
            from organism.store import OrganismStore
            from organism.curiosity import nudge_interests
            _os_ = OrganismStore()
            _state = _os_.pull()
            _recent = [t for _, t, _ in st.session_state.chat[-8:]] + [show]
            _bumped = nudge_interests(_state, _recent)
            if _bumped:
                _os_.push_state(_state, "chat")
                st.session_state._last_bumped = _bumped
        except Exception:
            pass
        mself.build_self_model(u)   # 자기 인식 갱신

    st.session_state.chat.append(("molang", answer, emotion))
    if photo:
        st.session_state.photo_key += 1   # 업로더 리셋 → 같은 사진 재반응 방지
    st.rerun()
