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
import outbox                      # 사이드바 여러 곳에서 쓴다 — 블록 안에서
import review_box                  # 부르면 그 블록을 안 탄 실행에서 NameError 가 난다
import purpose_growth

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


# 위젯 키 충돌로 앱이 통째로 죽지 않게 한다.
# 키를 미리 유일하게 만드는 것만으로는 부족했다(Streamlit 판에 따라
# 이전 실행의 키가 남아 DuplicateElementKey 가 난다). 그래서 실제로 그려보고,
# 충돌하면 다른 키로 다시 그린다.
_USED_KEYS = set()


def uk(name: str) -> str:
    k = name
    while k in _USED_KEYS:
        k += "_x"
    _USED_KEYS.add(k)
    return k


def safe(widget, *args, key: str = None, **kwargs):
    """위젯을 그린다. 키가 겹치면 키를 바꿔 다시 시도한다."""
    base = key or ""
    for suffix in ("", "_b", "_c", "_d"):
        try:
            return widget(*args, key=(uk(base + suffix) if base else None),
                          **kwargs)
        except Exception as e:
            if "Duplicate" not in type(e).__name__ and "Duplicate" not in str(e):
                raise
    return None


# 몰랑이가 먼저 걸어둔 말이 있으면 대화에 얹는다 (자율 발화)
if not st.session_state.get("_nudge_checked"):
    st.session_state["_nudge_checked"] = True
    try:
        _waiting = outbox.pending(sb, 1)   # 한 번에 한 마디만
        if _waiting:
            for _w in _waiting:
                st.session_state.chat.append(("molang", _w["body"], "기쁨"))
            outbox.mark_sent(sb, [_w["id"] for _w in _waiting])
            # 무엇을 보자고 한 건지 실체를 들고 있는다.
            # new_finding 만 '보여줄 것'이 있다. pending/grew 는 대화로 이어지지 않는다.
            st.session_state.pop("_offer", None)
            if any(w.get("rule") == "new_finding" for w in _waiting):
                st.session_state["_offer"] = outbox.latest_finding(sb)
            elif any(w.get("rule") == "pending" for w in _waiting):
                st.session_state["_offer"] = {
                    "topic": "검토 대기",
                    "title": "왼쪽 사이드바의 🧪 검토 대기 칸",
                    "text": "내가 찾아왔지만 확실하지 않아 보류해 둔 것들이야. "
                            "여기서 보여줄 수는 없고, 사이드바에서 ○/× 로 골라주면 돼.",
                    "url": ""}
    except Exception:
        pass

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
            _fup = safe(st.file_uploader, "표정이 든 molang.pkl", key="skin_pkl")
            if _fup and safe(st.button, "표정만 가져오기", key="skin_btn"):
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
        st.caption("옛 판 pkl 도 읽어요. 사용자 사실·몰랑이 자기 사실·확인 필요한 "
                   "대화 원문으로 나눠서 넣습니다.")
        up = safe(st.file_uploader, "예전 molang.pkl", key="mig_pkl")
        if up:
            import legacy_import, skin_store
            _parsed = legacy_import.read(up.getvalue())
            if _parsed.get("error"):
                st.error(_parsed["error"])
            else:
                st.caption(
                    f"사용자 사실 {len(_parsed['user_facts'])} · "
                    f"몰랑이 자기 사실 {len(_parsed['self_facts'])} · "
                    f"확인 필요 {len(_parsed['raw_answers'])} · "
                    f"표정 {len(_parsed['faces'])}개"
                    + (f" · 대화 {_parsed['talks']}회" if _parsed.get("talks") else ""))
                # 사고 유형이 기록에 있으면 되돌릴 수 있게
                _tr = _parsed.get("trees") or {}
                if _tr:
                    _miss = [k for k in _tr if k not in u.registry.trees]
                    # 기억이 비어 있는데 기록에는 있는 것도 되돌릴 거리다
                    _thin = [k for k, v in _tr.items()
                             if k in u.registry.trees and v.get("memory")
                             and not getattr(u.registry.trees[k], "memory", None)]
                    _todo = len(_miss) + len(_thin)
                    st.caption(f"🌳 기록에 든 사고 유형 {len(_tr)}개 "
                               + (f"· 되돌릴 것 **{_todo}개**"
                                  + (f" (유형 {len(_miss)} · 기억만 {len(_thin)})"
                                     if _miss and _thin else "")
                                  if _todo else "· 모두 서버에 있음"))
                    if _todo and safe(st.button,
                                      f"사고 유형 {_todo}개 되돌리기",
                                      key=uk("mig_trees")):
                        try:
                            _r = legacy_import.restore_trees(sb, _parsed)
                            if _r.get("restored") or _r.get("filled"):
                                st.success(
                                    f"사고 유형 {_r.get('restored', 0)}개를 되돌리고 "
                                    f"기억 {_r.get('filled', 0)}개를 채웠어요 "
                                    f"({_r['before']} → {_r['now']}개). "
                                    "복구 기록이 남아 자생과 구분됩니다.")
                                st.rerun()
                            else:
                                st.warning(_r.get("why") or "되돌리지 못했어요")
                        except Exception as e:
                            st.error(f"되돌리기 실패: {e}")

                    # 빠진 '경로 기록'만 되돌리기 — 지금 것은 그대로 둔다
                    _lost = 0
                    for _k, _v in _tr.items():
                        _cur = u.registry.trees.get(_k)
                        if _cur is None:
                            continue
                        _d = len(_v.get("history") or []) - len(_cur.history or [])
                        if _d > 0:
                            _lost += _d
                    if _lost:
                        st.caption(f"🧭 기록에만 있는 판단 경로 **{_lost}건** "
                                   "(지금 트리·기억은 그대로 두고 경로만 채웁니다)")
                        if safe(st.button, f"판단 경로 {_lost}건 되돌리기",
                                key=uk("mig_paths")):
                            try:
                                _rp = legacy_import.restore_paths(sb, _parsed)
                                if _rp.get("added"):
                                    st.success(f"판단 경로 {_rp['added']}건을 "
                                               "되돌렸어요.")
                                    st.rerun()
                                else:
                                    st.warning(_rp.get("why") or "되돌리지 못했어요")
                            except Exception as e:
                                st.error(f"되돌리기 실패: {e}")

                _take_p = st.checkbox("말투(페르소나)도 가져오기", value=False,
                                      key=uk("mig_persona"))
                if safe(st.button, "서버로 옮기기", key="mig_btn"):
                    try:
                        r = legacy_import.apply(sb, u.identity, _parsed,
                                                take_persona=_take_p)
                        if _parsed.get("faces"):
                            u.molang_faces = dict(_parsed["faces"])
                        if _parsed.get("appearance"):
                            u.molang_appearance = _parsed["appearance"]
                        _f = skin_store.save_all(sb, u)
                        st.success(
                            f"사실 {r['user_facts']}건, 몰랑이 자기 사실 "
                            f"{r['self_facts']}건, 표정 {_f}개를 옮겼어요. "
                            f"확인 필요 {r['quarantined']}건은 검토 대기로 보냈어요.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"옮기기 실패: {e}")

    # ── 보고 싶은 것만 골라 보기 ──────────────────────────────
    # 한 화면에 전부 늘어놓으면 정신이 없다. 탭으로 나눈다.
    # 묻는 말은 맨 앞에 둔다 — 답을 기다리는 쪽이 먼저다.
    try:
        _t_ask, _t_live, _t_mind, _t_check = st.tabs(
            ["💬 묻는 말", "🏠 사는 곳", "🕸️ 머릿속", "📥 검토"])
    except Exception:
        _t_ask = _t_live = _t_mind = _t_check = st.container()

    with _t_ask:
        # 💬 묻는 말 — **한 번에 하나씩.**
        #
        # 궁금한 것, 기다린 것, 맞춰볼 것이 한꺼번에 뜨면 취조가 된다.
        # 오래된 것부터 하나만 보여주고, 답하면 다음이 나온다.
        try:
            _asks = [p for p in outbox.pending(sb, limit=10)
                     if p.get("rule") in ("peek", "waiting", "confirm")]
            _asks.sort(key=lambda p: p.get("id") or 0)      # 오래된 것부터
            if _asks:
                _a = _asks[0]
                _rule = _a.get("rule")
                _pay = _a.get("payload") or {}
                _left = len(_asks) - 1

                st.markdown("---")
                st.markdown("### 💬 물어볼 게 있대요"
                            + (f"  ({_left}개 더)" if _left else ""))
                st.caption("🐰 " + (_a.get("body") or ""))

                import caring as _cr

                def _done(extra=None):
                    outbox.mark_sent(sb, [_a.get("id")])
                    if extra:
                        extra()
                    st.rerun()

                if _rule == "confirm":
                    _c1, _c2, _c3 = st.columns(3)
                    _fid = _pay.get("fact_id")
                    with _c1:
                        if safe(st.button, "응, 맞아", key=uk(f"ak_y{_a.get('id')}")):
                            _done(lambda: _fid and _cr.confirm_belief(sb, _fid, True))
                    with _c2:
                        if safe(st.button, "아니야", key=uk(f"ak_n{_a.get('id')}")):
                            _done(lambda: _fid and _cr.confirm_belief(sb, _fid, False))
                    with _c3:
                        if safe(st.button, "나중에", key=uk(f"ak_l{_a.get('id')}")):
                            _done()

                elif _rule == "peek":
                    _c1, _c2 = st.columns(2)
                    with _c1:
                        _shot = safe(st.camera_input, "📷 보여주기",
                                     key=uk("peek_cam"))
                        if _shot is not None:
                            st.session_state["peek_photo"] = _shot.getvalue()
                            st.session_state["peek_id"] = _a.get("id")
                            st.caption("보여줬어요. 아래 대화에서 반응을 들어보세요.")
                    with _c2:
                        _snd = None
                        try:
                            _snd = st.audio_input("🎤 들려주기", key=uk("peek_mic"))
                        except Exception:
                            st.caption("(이 판에서는 녹음을 못 써요)")
                        if _snd is not None:
                            st.session_state["peek_sound"] = _snd.getvalue()
                            st.session_state["peek_id"] = _a.get("id")
                            st.caption("들려줬어요.")
                    if safe(st.button, "지금은 안 돼", key=uk(f"ak_s{_a.get('id')}")):
                        _done()

                else:   # waiting
                    _c1, _c2 = st.columns(2)
                    with _c1:
                        if safe(st.button, "대답할게",
                                key=uk(f"ak_a{_a.get('id')}")):
                            _wid = _pay.get("wait_id")
                            _done(lambda: _wid and _cr.mark_asked(sb, _wid))
                    with _c2:
                        if safe(st.button, "나중에", key=uk(f"ak_w{_a.get('id')}")):
                            _done()
        except Exception:
            pass

    with _t_live:
        # ✈️ 여행 — 사진과 기념품
        try:
            import travel as _tvm
            _tt = _tvm.load(sb)
            _trips = _tt.get("trips") or []
            _long = _tt.get("longing") or {}
            _now = None
            try:
                import island as _islm
                _now = _islm.where_now(_tt)
            except Exception:
                pass
            if _trips or _long or (_now and _now.get("away")):
                st.markdown("---")
                st.markdown("### ✈️ 여행")
                if _now and _now.get("away"):
                    st.caption(f"🏝️ **지금 {_now['place']}에 있어요** "
                               f"· 남은 {_now['left']}일 · 지침 {_now['tired']}")

                    # 섬 지도 — 집과 같은 방식으로 좌표대로 놓는다
                    _ic = _islm.layout()["coords"]
                    _irows = sorted({c[0] for c in _ic.values()})
                    _icols = sorted({c[1] for c in _ic.values()})
                    _ig = {(c[0], c[1]): n for n, c in _ic.items()}
                    _seen = _now.get("seen") or []
                    _emoji = {"공항": "✈️", "호텔": "🛏️", "스파": "♨️", "식당": "🍽️",
                              "당근농장": "🥕", "바닷가": "🌊", "등대": "🗼",
                              "산길": "⛰️", "놀이공원": "🎡", "시장": "🏪"}
                    _cells = []
                    for _r in _irows:
                        for _c in _icols:
                            _sp = _ig.get((_r, _c))
                            if not _sp:
                                _cells.append('<div style="min-height:52px"></div>')
                                continue
                            _is_here = _sp == _now.get("spot")
                            _been = _seen.count(_sp)
                            _bg = ("rgba(255,138,76,0.85)" if _is_here
                                   else f"rgba(255,180,120,{0.15 + 0.2 * _been:.2f})")
                            _cells.append(
                                f'<div style="background:{_bg};border:1px solid '
                                f'{"#d35400" if _is_here else "#e8c9b0"};'
                                'border-radius:9px;padding:5px 6px;min-height:52px;'
                                'text-align:center;">'
                                f'<div style="font-size:1.05rem">{_emoji.get(_sp,"📍")}</div>'
                                f'<div style="font-size:0.63rem;color:#444;'
                                f'font-weight:{"700" if _is_here else "400"}">{_sp}'
                                + ("<br>🐰🐤" if _is_here else "") + "</div></div>")
                    st.markdown(
                        f'<div style="display:grid;grid-template-columns:'
                        f'repeat({len(_icols)},1fr);gap:4px;">'
                        + "".join(_cells) + "</div>", unsafe_allow_html=True)

                    if _seen:
                        st.caption("　다녀온 곳: " + " → ".join(_seen))
                    _lt = _now.get("last_talk")
                    if _lt:
                        st.caption(f"　🐰 {(_lt.get('molang') or '')[:52]}")
                        st.caption(f"　🐤 {(_lt.get('piupiu') or '')[:52]}")
                if _trips:
                    _last = _trips[-1]
                    st.caption(f"{len(_trips)}번 다녀옴 · 마지막은 **{_last['where']}**"
                               f" ({_last.get('by','')})")
                _want = sorted(_long.items(), key=lambda kv: -kv[1])[:2]
                for _n, _v in _want:
                    if _v <= 0:
                        continue
                    _bar = "█" * max(1, int(10 * min(1.0, _v / 1.0)))
                    st.caption(f"　{_n} 가고 싶음 {_bar} {_v:.2f}")
                _photos = (_tt.get("photos") or [])[::-1]
                if _photos:
                    with st.expander(f"📷 사진 {len(_photos)}장"):
                        for _p in _photos[:8]:
                            st.caption("　" + _tvm.photo_line(_p))
                _souv = (_tt.get("souvenirs") or [])[::-1]
                if _souv:
                    st.caption("🎁 " + " · ".join(
                        f"{s['name']}({s['from']})" for s in _souv[:4]))
        except Exception:
            pass

        # 🏠 둘의 집과 바깥 — 어디에 있고, 무엇을 놓아뒀고, 무엇이 바뀌었나
        try:
            import home as _home
            import land as _land
            _h = _home.load(sb)
            _ld = _land.load(sb)
            _where = _h.get("where") or {}
            _objs = _h.get("objects") or {}
            _visits = _h.get("visits") or {}
            _mx = max(1, max(_visits.values()) if _visits else 1)
            _coords = _home.layout()["coords"]

            st.markdown("---")
            st.markdown("### 🏠 둘의 집")

            # 방을 **실제 좌표대로** 놓는다. 이름표 여섯 개가 아니라 지도가 되게.
            _rows = sorted({c[0] for c in _coords.values()})
            _cols = sorted({c[1] for c in _coords.values()})
            _grid = {(r, c): None for r in _rows for c in _cols}
            for _r, _xy in _coords.items():
                _grid[(_xy[0], _xy[1])] = _r

            _cells = []
            for _r in _rows:
                for _c in _cols:
                    _room = _grid.get((_r, _c))
                    if not _room:
                        _cells.append('<div style="min-height:70px"></div>')
                        continue
                    _who = "".join(("🐰" if k == "molang" else "🐤")
                                   for k, v in _where.items() if v == _room)
                    _items = [o.get("name") for o in (_objs.get(_room) or [])][-3:]
                    _warm = 0.10 + 0.55 * (_visits.get(_room, 0) / _mx)
                    _sm = _home.stim(_room)
                    _cells.append(
                        f'<div style="background:rgba(254,240,27,{_warm:.2f});'
                        'border:1px solid #cfcfcf;border-radius:10px;padding:6px 7px;'
                        'min-height:70px;">'
                        f'<div style="font-size:0.75rem;font-weight:700;color:#333;">'
                        f'{_room} <span style="float:right">{_who}</span></div>'
                        f'<div style="font-size:0.62rem;color:#888;">'
                        f'{"☀️" if _sm["lift"] > 0.65 else "🌙" if _sm["lift"] < 0.45 else "·"}'
                        f'{" 🔇" if _sm["quiet"] else ""}</div>'
                        f'<div style="font-size:0.66rem;color:#666;line-height:1.3;">'
                        + ("<br>".join("· " + str(i)[:9] for i in _items)
                           if _items else "")
                        + "</div></div>")
            st.markdown(
                f'<div style="display:grid;grid-template-columns:repeat({len(_cols)},1fr);'
                'gap:5px;">' + "".join(_cells) + "</div>", unsafe_allow_html=True)

            _same = len(set(_where.values())) == 1 and len(_where) > 1
            st.caption("🐰🐤 같은 방에 있어요" if _same else
                       f"🐰 {_where.get('molang','?')} · 🐤 {_where.get('piupiu','?')}")

            # 바깥 — 집에서 얼마나 먼지, 가봤는지
            _places = _ld.get("places") or []
            if _places:
                _lv = _ld.get("visits") or {}
                _icon = {"바다": "🌊", "산": "⛰️", "숲": "🌲",
                         "마을": "🏘️", "들판": "🌾", "물가": "💧"}
                st.markdown("#### 🧭 바깥")
                for _p in sorted(_places, key=lambda x: x["dist"]):
                    _n = _lv.get(_p["kind"], 0)
                    _bar = "─" * int(min(10, _p["dist"]))
                    st.caption(
                        f"🏠{_bar}{_icon.get(_p['kind'],'📍')} **{_p['kind']}** "
                        f"· {_p['dist']}만큼 멀리 · "
                        + (f"{_n}번 다녀옴" if _n else "아직 못 가봄")
                        + (f" · {', '.join(_p.get('from', [])[:2])}에서 생김"
                           if _p.get("from") else ""))

            _log = (_h.get("log") or [])[-6:][::-1]
            _llog = (_ld.get("log") or [])[-4:][::-1]
            if _log or _llog:
                with st.expander(f"🔨 바뀐 자취 {len(_h.get('log') or []) + len(_ld.get('log') or [])}"):
                    for _e in _llog:
                        st.caption(f"🧭 {_e.get('kind')} — {_e.get('what')}"
                                   + ("(처음)" if _e.get("first") else ""))
                    for _e in _log:
                        _wh = "🐰" if _e.get("who") == "molang" else "🐤"
                        if _e.get("what") == "옮김":
                            st.caption(f"{_wh} {_e.get('item')} 를 "
                                       f"{_e.get('from')} → {_e.get('to')}")
                        else:
                            st.caption(f"{_wh} {_e.get('room')}에 "
                                       f"{_e.get('item')} 를 놓았어요")

            # 커지면 한눈에 — 별도 탭처럼 펼쳐 보는 자리
            st.session_state["_world"] = {"home": _h, "land": _ld,
                                          "coords": _coords}
        except Exception as _e:
            st.caption(f"집을 못 불러왔어요: {str(_e)[:60]}")

        # 피우피우 — 사용자와 직접 말하지 않는다. 몰랑이가 전할 뿐.
        try:
            import piupiu
            _pt = (sb.table("molang_peer_talks").select("*")
                   .order("id", desc=True).limit(3).execute().data) or []
            if _pt:
                with st.expander(f"🐤 피우피우와 나눈 이야기 {len(_pt)}"):
                    for _t in _pt:
                        st.caption(f"**{_t.get('topic')}**")
                        st.caption(f"　🐰 {(_t.get('molang') or '')[:70]}")
                        st.caption(f"　🐤 {(_t.get('piupiu') or '')[:70]}")
        except Exception:
            pass

    with _t_mind:
        # 🕸️ 기억 지도 — 무엇이 무엇에 끌리는지, 무엇이 아직 엉켜 있는지
        try:
            import semantic_map as _sm
            import word_gravity as _wgv
            _gm, _gcl = _sm.load(sb)
            if _gm.get("edges"):
                _mass = _gm.get("mass") or {}
                st.markdown("---")
                st.markdown("### 🕸️ 기억 지도")
                st.caption(f"마디 {len(_gm.get('freq') or {})}개 · "
                           f"실 {len(_gm.get('edges') or {})}개 · "
                           f"갈래 {len(_gcl)}개")

                # 무거운 낱말 = 친숙한 것
                _heavy = sorted(((w, m) for w, m in _mass.items() if m > 0),
                                key=lambda kv: -kv[1])[:8]
                if _heavy:
                    st.caption("**친숙한 것** · " +
                               " · ".join(f"{w}({m:.1f})" for w, m in _heavy))

                # 한 낱말이 어디로 끌리는지 직접 보기
                _pick = st.selectbox(
                    "무엇이 어디로 끌리는지 보기",
                    [w for w, _ in _heavy] + [w for w in (_gm.get("freq") or {})
                                              if w not in dict(_heavy)][:40],
                    key=uk("grav_pick"))
                if _pick:
                    _att = _wgv.attracted(_gm, _mass, _pick, 6)
                    if _att:
                        _mx = max(p for _, p in _att) or 1
                        for _n, _p in _att:
                            _bar = "█" * max(1, int(10 * _p / _mx))
                            st.caption(f"　{_pick} → **{_n}** {_bar} {_p:.2f}")
                    else:
                        st.caption("　아직 끌리는 데가 없어요")
                    _h = _wgv.home_branch(_gm, _mass, _gcl, _pick)
                    if _h.get("branch"):
                        st.caption(
                            f"　제 자리: **{_h['branch']}** ({_h['score']:.1f})"
                            + ("" if _h["settled"] else
                               " ← 아직 " + ", ".join(r[0] for r in _h["rivals"])
                               + " 사이에서 흔들림"))

                # 갈래와 확신
                with st.expander(f"갈래 {len(_gcl)}개"):
                    for _c in _gcl[:12]:
                        _conf = _c.get("confidence", 0)
                        _mark = ("🔴" if _c.get("unsure") else
                                 "🟡" if _conf < 0.6 else "🟢")
                        st.caption(f"{_mark} **{_c['name']}** ({_c['size']}개, "
                                   f"확신 {_conf:.2f})"
                                   + (f" ← {_c['from']}에서 갈라짐"
                                      if _c.get("from") else ""))
                        st.caption("　" + ", ".join(_c["members"][:8]))
        except Exception as _e:
            st.caption(f"지도를 못 불러왔어요: {str(_e)[:50]}")

    with _t_check:
        # 검토 대기 — 검토함이 두 곳이다(대화에서 격리된 사실 + 워커가 찾아온 관측).
        # 앱이 한 쪽만 읽어서 워커가 격리해도 0으로 보이던 문제를 고쳤다.
        _cnt = review_box.counts(sb, u.identity)
        _q = review_box.pending(sb, u.identity, 20)
        # 호기심이 사고 구조를 얼마나 바꿨나
        try:
            _grown = sum(1 for t in u.registry.trees.values()
                         for n in t.nodes if str(n).startswith("grown_"))
            _tmem = sum(len(getattr(t, "memory", [])) for t in u.registry.trees.values())
            _used = sum((u.registry.usage_count or {}).values())
            st.caption(f"🌳 사고 기억 {_tmem}개 · 늘린 판단 단계 {_grown}개 · "
                       f"트리 사용 {_used}회")
            if st.session_state.get("_tree_save_error"):
                st.error(f"트리 저장 실패: {st.session_state['_tree_save_error'][:80]}")
        except Exception:
            pass

        if st.session_state.get("_guard_note"):
            st.caption("🛑 " + st.session_state["_guard_note"])

        _bump = st.session_state.get("_last_bumped")
        if _bump:
            st.caption(f"🌱 요즘 관심: {', '.join(_bump[:5])}")

        # 목적 제안 — 몰랑이가 "이걸 목적으로 삼아도 될까?" 하고 물어온 것
        try:
            # sent_at 은 '말을 걸었나'이지 '결정했나'가 아니다.
            # 결정 여부는 error(거절) / molang_purposes(승인) 로 판단한다.
            _props = (sb.table("molang_outbox")
                      .select("id,body,rule,payload,created_at")
                      .in_("rule", ["purpose_sub", "purpose_core"])
                      .is_("error", "null")
                      .order("id", desc=True).limit(6).execute().data) or []
            _done = {p.get("purpose") for p in purpose_growth.load_subs(sb, False)}
            _props = [p for p in _props
                      if (p.get("payload") or {}).get("purpose") not in _done][:3]
        except Exception:
            _props = []
        if _props:
            st.markdown("### 🎯 목적 제안")
        for _p in _props:
            _core = (_p["rule"] == "purpose_core")
            st.caption(("🌱 하위 목적" if not _core else "🧭 핵심 목적 바꾸기")
                       + f" · {_p['body']}")
            _pl = _p.get("payload") or {}
            if _pl.get("why"):
                st.caption(f"　이유: {_pl['why']}")
            if _core and _pl.get("subs"):
                st.caption("　그동안 품은 목적: " + ", ".join(_pl["subs"][:4]))
            pc1, pc2 = st.columns(2)
            if safe(pc1.button, "○ 그러자", key=f"pok_{_p['id']}"):
                _r = purpose_growth.accept(sb, u.identity, _p)
                if _r.get("ok"):
                    outbox.mark_sent(sb, [_p["id"]])   # 다시 안 뜨게
                    st.success("목적에 담았어요" + (f" — {_r.get('new','')}"
                                                  if _r.get("new") else ""))
                    st.rerun()
                else:
                    st.error(_r.get("error"))
            if safe(pc2.button, "× 아직", key=f"pno_{_p['id']}"):
                purpose_growth.decline(sb, _p)
                st.rerun()
        _subs = purpose_growth.load_subs(sb)
        if _subs:
            st.caption("지금 품은 목적: " +
                       " · ".join(s["purpose"] for s in _subs[:4]))

    st.markdown("---")
    st.markdown(f"### 🧪 검토 대기 {_cnt['total']}")
    st.caption(f"대화에서 {_cnt['fact']}건 · 워커가 찾은 것 {_cnt['observation']}건")
    if not _q:
        st.caption("지금은 없어요. 대화하거나 워커가 돌면 여기에 쌓여요.")
    else:
        for _item in _q[:8]:
            if _item["where"] == "error":       # 읽기 실패는 버튼 없이 알림만
                st.error(_item["title"])
                continue
            c1, c2, c3 = st.columns([5, 1, 1])
            _mark = "💬" if _item["where"] == "fact" else "🔎"
            c1.caption(f"{_mark} {_item['title']}")
            c1.caption(f"　{_item['reason']}")
            if _item.get("url"):
                c1.caption(f"　{_item['url'][:50]}")
            _k = f"{_item['where']}_{_item['id']}"
            # 긴 대화 원문은 그대로 사실이 못 된다 → 사실만 뽑아서 넣는 길을 준다
            if len(_item.get("title") or "") > 60 or _item.get("url"):
                if safe(c1.button, "✂️ 사실만 뽑기", key=f"ex_{_k}"):
                    with st.spinner("뽑는 중…"):
                        st.session_state[f"ex_res_{_k}"] = review_box.extract_facts(
                            _item.get("full") or _item.get("title") or "",
                            st.session_state.api_key)
            _ex = st.session_state.get(f"ex_res_{_k}")
            if _ex:
                if _ex.get("error"):
                    c1.caption(f"뽑기 실패: {_ex['error'][:50]}")
                elif not (_ex["user"] or _ex["molang"]):
                    c1.caption("남길 만한 사실이 없어요")
                else:
                    for _t in _ex["user"]:
                        c1.caption(f"　👤 {_t}")
                    for _t in _ex["molang"]:
                        c1.caption(f"　🐰 {_t}")
                    if safe(c1.button, "이대로 넣기", key=f"exok_{_k}"):
                        _r = review_box.save_extracted(
                            sb, u.identity, _item, _ex["user"], _ex["molang"])
                        if _r.get("ok"):
                            st.session_state.pop(f"ex_res_{_k}", None)
                            st.rerun()
                        else:
                            st.error(_r.get("error"))
            if safe(c2.button, "○", key=f"ok_{_k}", help="맞아요 / 쓸 만해요"):
                _r = review_box.approve(sb, u.identity, _item)
                if _r.get("ok"):
                    st.rerun()
                else:                       # 조용히 실패하면 왜 안 되는지 모른다
                    st.error(f"승인 실패: {_r.get('error')}")
            if safe(c3.button, "×", key=f"no_{_k}", help="아니에요"):
                _r = review_box.reject(sb, u.identity, _item)
                if _r.get("ok"):
                    st.rerun()
                else:
                    st.error(f"거절 실패: {_r.get('error')}")

    st.markdown("---")
    st.caption("처음이면: 몰랑이 사진 → 외형학습 → 표정생성")
    base_img = safe(st.file_uploader, "기본 몰랑이 사진", key="base_img",
                    type=["png","jpg","jpeg","webp","gif","bmp"])
    if base_img and safe(st.button, "① 외형 학습", key="appearance_btn"):
        with st.spinner("얼굴 익히는 중..."):
            b64 = base64.b64encode(base_img.getvalue()).decode()
            feat = skin.extract_appearance(client, b64, base_img.type)
            if feat:
                skin.set_appearance(u, feat)
                import skin_store; skin_store.save_appearance(sb, feat)
                st.success("외형 기억 완료!")
            else: st.error("실패 (API키 확인)")

    if skin.has_appearance(u) and safe(st.button, "② 표정 5종 생성", key="faces_btn"):
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

            # 성장 기록 — 화면은 '지금'을 보여주지만 성장은 '어떻게 변해왔나'다.
            # 나중에 파이썬으로 열어 그래프를 그리거나 비교 실험을 하려면
            # 원본이 통째로 있어야 한다.
            try:
                import growth_export
                _gstate = None
                try:
                    from organism.store import OrganismStore
                    _gstate = OrganismStore(sb).pull()
                except Exception:
                    pass
                _gdata = growth_export.collect(sb, u.registry, _gstate, u.identity)
                st.download_button(
                    "🌳 성장 기록 받기 (.pkl)",
                    data=__import__("pickle").dumps(_gdata),
                    file_name=f"molang_growth_{__import__('time').strftime('%m%d_%H%M')}.pkl",
                    mime="application/octet-stream",
                    key=uk("growth_dl"))
                st.caption(growth_export.summary_line(_gdata))
            except Exception as e:
                st.caption(f"성장 기록 준비 실패: {str(e)[:60]}")
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

# ── 세계 한눈에 보기 (집이 커지면 사이드바로는 좁다) ──
_w = st.session_state.get("_world")
if _w and (len(_w["land"].get("places") or []) >= 2
           or sum(len(v) for v in (_w["home"].get("objects") or {}).values()) >= 6):
    with st.expander("🗺️ 몰랑이의 세계 한눈에 보기"):
        _h2, _l2, _co = _w["home"], _w["land"], _w["coords"]
        _wh = _h2.get("where") or {}
        _ob = _h2.get("objects") or {}
        _vi = _h2.get("visits") or {}
        _mx2 = max(1, max(_vi.values()) if _vi else 1)
        _rows2 = sorted({c[0] for c in _co.values()})
        _cols2 = sorted({c[1] for c in _co.values()})
        _g2 = {(c[0], c[1]): r for r, c in _co.items()}
        _cell = []
        for _r in _rows2:
            for _c in _cols2:
                _rm = _g2.get((_r, _c))
                if not _rm:
                    _cell.append('<div></div>'); continue
                _who2 = "".join(("🐰" if k == "molang" else "🐤")
                                for k, v in _wh.items() if v == _rm)
                _its = [o.get("name") for o in (_ob.get(_rm) or [])]
                _warm2 = 0.08 + 0.5 * (_vi.get(_rm, 0) / _mx2)
                import home as _hm2
                _s2 = _hm2.stim(_rm)
                _f2 = _hm2.fit("molang", _rm)
                _cell.append(
                    f'<div style="background:rgba(254,240,27,{_warm2:.2f});'
                    'border:1px solid #d5d5d5;border-radius:12px;padding:10px;'
                    'min-height:110px;">'
                    f'<div style="font-weight:700;color:#333;">{_rm} '
                    f'<span style="float:right;font-size:1.1rem">{_who2}</span></div>'
                    f'<div style="font-size:0.72rem;color:#999;margin:3px 0;">'
                    f'{"☀️ 환함" if _s2["lift"] > 0.65 else "🌙 어둑" if _s2["lift"] < 0.45 else "· 보통"}'
                    f'{" · 🔇 조용" if _s2["quiet"] else ""} · 🐰{_f2["feel"]}</div>'
                    f'<div style="font-size:0.75rem;color:#555;line-height:1.5;">'
                    + ("<br>".join("· " + str(i) for i in _its) if _its
                       else '<span style="color:#bbb">비어 있음</span>')
                    + f'</div><div style="font-size:0.68rem;color:#aaa;'
                    f'margin-top:4px;">{_vi.get(_rm, 0)}번 머묾</div></div>')
        st.markdown(
            f'<div style="display:grid;grid-template-columns:repeat({len(_cols2)},1fr);'
            'gap:8px;">' + "".join(_cell) + "</div>", unsafe_allow_html=True)

        _pl = _l2.get("places") or []
        if _pl:
            _lv2 = _l2.get("visits") or {}
            _ic = {"바다": "🌊", "산": "⛰️", "숲": "🌲",
                   "마을": "🏘️", "들판": "🌾", "물가": "💧"}
            st.markdown("**바깥** — 집에서 멀어지는 순서")
            for _p in sorted(_pl, key=lambda x: x["dist"]):
                _n2 = _lv2.get(_p["kind"], 0)
                st.markdown(
                    f"🏠 {'━' * int(min(14, _p['dist']))} "
                    f"{_ic.get(_p['kind'], '📍')} **{_p['kind']}** "
                    f"({_p['dist']}) — "
                    + (f"{_n2}번 다녀옴" if _n2 else "아직 못 가봄"))

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

# 🪞 내다보기로 보여준 사진이 있으면 그것이 이번 입력이 된다.
# (사이드바에서 찍은 것이 대화로 이어져야 기억이 된다)
class _Shot:
    def __init__(self, raw): self._raw = raw; self.name = "peek.jpg"
    def getvalue(self): return self._raw
    def read(self): return self._raw

# 🎤 들려준 소리 — 글로 옮겨 대화에 넣는다.
# 들은 것은 사실로 바로 넣지 않고 확인 거리로 보낸다
# (곁에 있던 사람의 말이 섞일 수 있다).
heard = ""
if st.session_state.get("peek_sound"):
    try:
        import listening
        _raw = st.session_state.pop("peek_sound")
        _r = listening.transcribe(_raw, st.session_state.api_key)
        if _r.get("ok"):
            heard = _r["text"]
            listening.to_quarantine(sb, heard, "소리로 들은 것")
            if not msg:
                msg = "(지금 여기 소리를 들려줬어)"
        else:
            st.caption(f"못 들었어요: {_r.get('why')}")
        _pid = st.session_state.pop("peek_id", None)
        if _pid:
            outbox.mark_sent(sb, [_pid])
    except Exception as _e:
        st.caption(f"듣기 실패: {str(_e)[:60]}")

if photo is None and st.session_state.get("peek_photo"):
    photo = _Shot(st.session_state.pop("peek_photo"))
    if not msg:
        msg = "(궁금해해서 지금 여기를 보여줬어)"
    try:
        _pid = st.session_state.pop("peek_id", None)
        if _pid:
            outbox.mark_sent(sb, [_pid])
    except Exception:
        pass

# 이미 처리한 입력인지 체크 (사진 무한 반응 방지)
if msg or photo:
    show = msg or "(사진을 보냈어요 📷)"
    st.session_state.chat.append(("me", show, "보통"))

    with st.spinner("몰랑이가 생각 중... 🐰"):
        # 시간 맥락 (한국시간 KST 기준)
        last_ts = getattr(u, "last_talk_ts", None)
        time_ctx = mtime.time_context(last_ts)
        self_ctx = mself.to_self_prompt(u)   # 자기 인식 (LLM 독립)

        # 지금 어디에 있는가. 집은 워커가 움직이는데 그 사실이 대화에 안 들어가면
        # 몰랑이는 제 집을 모르는 채로 말하게 된다 (공간과 자기가 따로 논다).
        place_ctx = ""
        # 여행 중이면 집 위치를 말하면 안 된다.
        # ("지금 어디야?" 에 부엌이라고 답한 일이 있었다 — 섬에 있었는데)
        _away = False
        try:
            import travel as _tvq
            _away = bool((_tvq.load(sb) or {}).get("current"))
        except Exception:
            _away = False
        try:
            if _away:
                raise RuntimeError("여행 중")
            import home as _hm
            _hh = _hm.load(sb)
            _room = (_hh.get("where") or {}).get("molang")
            _piu_room = (_hh.get("where") or {}).get("piupiu")
            _here = [o.get("name") for o in
                     (_hh.get("objects") or {}).get(_room, [])][-4:]
            _fit = _hm.fit("molang", _room) if _room else {}
            if _room:
                place_ctx = (
                    f"[지금 있는 곳] 너는 {_room}에 있다."
                    + (f" 너는 대왕토끼라 여기가 {_fit['feel']}."
                       + (f" {_fit['note']}." if _fit.get("note") else "")
                       if _fit else "")
                    + (f" 여기엔 {', '.join(map(str, _here))}가 있다." if _here else "")
                    + (f" 피우피우는 {_piu_room}에 있다."
                       if _piu_room and _piu_room != _room
                       else " 피우피우도 같은 방에 있다." if _piu_room else "")
                    + " 방을 옮기거나 물건을 놓는 일은 혼자 있을 때 일어난다."
                      " 물으면 지금 자리를 그대로 말하라. 지어내지 마라.")
                u.identity.place = _room     # 기억에 '어디서'가 남게
        except Exception:
            place_ctx = ""
        # ── 내부: Arcogit이 생각 (유형판별→트리→기억주입→답) ──
        q = msg or "이 사진 보고 몰랑이답게 반응해줘"

        # 의미 지도 — 물어본 말에 딸린 것과 **비어 있는 것**을 함께 준다.
        # 빈자리를 보여주면 지어낼 자리가 줄어든다.
        map_ctx = ""
        try:
            import semantic_map as _smap
            _g, _cl = _smap.load(sb)
            if _g.get("edges"):
                import re as _re
                import word_gravity as _wg
                _qw = [w for w in _re.findall(r'[가-힣A-Za-z]{2,}', q)][:4]
                _mass = _g.get("mass") or _wg.masses(_g, None)
                # 이웃을 **끌림 순서**로 준다. 굵기순이면 '바다 → 다운로드'가
                # 앞에 오지만, 끌림순이면 무겁고 여러 곳에 걸친 쪽이 앞에 온다.
                _body = _wg.context_line(_g, _mass, _cl, _qw)
                _lines = [_body] if _body else []
                for _w in _qw:
                    _gp = _smap.gaps(_g, _cl, _w)
                    if _gp.get("missing"):
                        _lines.append(f"    ({_w}에서 아직 모르는 쪽: "
                                      f"{', '.join(_gp['missing'][:4])})")
                if _lines:
                    map_ctx = ("[내 기억 지도에서 이어진 것]\n"
                               + "\n".join(_lines) + "\n")
        except Exception:
            map_ctx = ""

        # 들려준 소리가 있으면 그것부터
        heard_ctx = ""
        try:
            if heard:
                import listening as _ls
                heard_ctx = _ls.context_line(heard)
        except Exception:
            heard_ctx = ""

        # 여행 — 다녀온 곳, 그리고 사진 한 장
        travel_ctx = ""
        try:
            import travel as _tv
            _t = _tv.load(sb)
            try:
                import island as _isl
                travel_ctx += _isl.context_line(_t)
            except Exception:
                pass
            _desc = _tv.describe(_t)
            # 질문과 이어질 때만 사진을 꺼낸다. 늘 넣으면 프롬프트만 길어지고
            # 정작 정체성 지시가 묻힌다.
            _ph = _tv.recall_photo(_t, cue=q) if len(q) >= 2 else None
            if _ph:
                import re as _re2
                _qw = set(_re2.findall(r"[가-힣A-Za-z]{2,}", q))
                _pw = set(_re2.findall(r"[가-힣A-Za-z]{2,}",
                                       f"{_ph.get('where','')} {_ph.get('scene','')}"))
                if not (_qw & _pw):
                    _ph = None
            # += 여야 한다. = 로 덮어쓰면 바로 위에서 만든 '여행 중' 맥락이
            # 지워져서, 섬에 있으면서 집에 있는 것처럼 말하게 된다.
            if _desc:
                travel_ctx += _desc + "\n"
            if _ph:
                travel_ctx += ("[떠오르는 사진] " + _tv.photo_line(_ph)
                               + " (물어보면 이 이야기를 하되, 없는 건 "
                                 "지어내지 마라)\n")
        except Exception:
            travel_ctx = ""

        # 요즘 알고 싶은 것 — 승인된 하위 목적
        purpose_ctx = ""
        try:
            import purpose_drive as _pd
            purpose_ctx = _pd.chat_context(_pd.load(sb))
        except Exception:
            purpose_ctx = ""

        # 모르는 것을 지어내지 못하게 (말하기 전 단계)
        import groundcheck as _gc
        guard_ctx = _gc.guard_prompt(q if not photo else "", u.identity) \
            + _gc.self_report(q if not photo else "", u.identity,
                              st.session_state.get("_last_unknown"))

        # 사진이면 answer_fn 대신 직접 vision 호출로 답 생성
        if photo:
            pb = base64.b64encode(photo.getvalue()).decode()
            try:
                r = client.chat.completions.create(model="gpt-4o",
                    messages=[{"role":"system","content":u.identity.to_system_prompt(question=q)+"\n"+self_ctx+"\n"+place_ctx+"\n"+time_ctx+"\n"+heard_ctx+"\n"+travel_ctx+"\n"+purpose_ctx+"\n"+guard_ctx
                     +"\n[말투] 너는 몰랑이다. 반말로, 토끼답게, 짧고 다정하게 답한다."
                      " '저는/하시나요' 같은 존댓말을 쓰지 마라."},
                        {"role":"user","content":[
                            {"type":"text","text":"이 사진 보고 몰랑이답게 반응해줘!"},
                            {"type":"image_url","image_url":{"url":f"data:{photo.type};base64,{pb}"}}]}],
                    temperature=0.9, max_tokens=300)
                answer = r.choices[0].message.content
            except Exception: answer = "우와 사진이다! 🐰💗"
            result = None
        else:
            # 맥락이 길어지면 맨 앞의 정체성 지시가 묻힌다.
            # (여행 중 긴 프롬프트에서 몰랑이가 존댓말 챗봇처럼 답한 일이 있었다)
            # 그래서 **맨 뒤에 말투를 한 번 더** 못박는다. 마지막 지시가 가장 세다.
            tail_ctx = ("[말투] 너는 몰랑이다. 반말로, 토끼답게, 짧고 다정하게 "
                        "답한다. '저는/하시나요' 같은 존댓말을 쓰지 마라.\n")
            bg = self_ctx + ((" " + place_ctx) if place_ctx else "") \
                 + ((" " + time_ctx) if time_ctx else "") \
                 + (("\n" + heard_ctx) if heard_ctx else "") \
                 + (("\n" + travel_ctx) if travel_ctx else "") \
                 + (("\n" + purpose_ctx) if purpose_ctx else "") \
                 + (("\n" + map_ctx) if map_ctx else "") \
                 + (("\n" + guard_ctx) if guard_ctx else "") \
                 + ("\n" + tail_ctx)
            # 최근 대화를 맥락으로 — 이게 없으면 몰랑이가 자기가 방금 한 말도 모른다
            _recent_lines = []
            for _r, _t, _ in st.session_state.chat[-7:-1]:
                _who = "나(몰랑이)" if _r == "molang" else "사용자"
                _recent_lines.append(f"{_who}: {_t[:120]}")
            _hist = "\n".join(_recent_lines)
            # 내가 먼저 보여주겠다고 한 것이 있으면 그 실체도 같이
            _off = st.session_state.get("_offer") or {}
            _offer_txt = ""
            if _off:
                _offer_txt = ("\n[내가 방금 보여주겠다고 한 것]\n"
                              f"주제: {_off.get('topic','')}\n"
                              f"제목: {_off.get('title','')}\n"
                              f"내용: {(_off.get('text') or '')[:400]}\n"
                              f"주소: {_off.get('url','')}")
            q_with_time = (f"[최근 대화]\n{_hist}\n\n"
                           f"사용자가 방금 한 말: \"{q}\"{_offer_txt}\n{bg}")
            result = u.think(q_with_time, choose_fn=choose_fn, answer_fn=answer_fn,
                             classify_fn=classify_fn, tree_factory=designer)
            answer = result["answer"] or "히힛 🐰"

        # 기억에 없는 이름을 댔으면 그 문장을 걷어낸다.
        # (한로로 곡을 네 번 지어낸 일이 이 자리에서 막힌다)
        if not photo:
            _chk = _gc.check_answer(answer, q, u.identity)
            if not _chk["ok"]:
                answer = _chk["fixed"]
                st.session_state["_last_unknown"] = _chk["unknown"]
                st.session_state["_guard_note"] = (
                    "기억에 없는 이름을 덜어냈어요: "
                    + ", ".join(_chk["unknown"][:4]))
            else:
                st.session_state.pop("_guard_note", None)

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
            _rs = registry_store.save(sb, u.registry)
            if not _rs.get("ok"):
                # 조용히 실패하면 트리가 영영 안 쌓인다 (실제로 그랬다)
                st.session_state["_tree_save_error"] = _rs.get("error")
        except Exception as e:
            st.session_state["_tree_save_error"] = str(e)[:200]
        # 대화가 관심사로 스며들게 — 여러 번 나온 말만, 작은 가중치로.
        # (한 번 말했다고 바로 파헤치지 않는다. 확신이 천천히 굳는 것과 같은 결)
        try:
            from organism.store import OrganismStore
            from organism.curiosity import nudge_interests
            _os_ = OrganismStore()
            _state = _os_.pull()
            # 사용자가 한 말에서만 관심사를 뽑는다.
            # 몰랑이 답까지 섞으면 '히힛', '너가', '있어' 같은 말투가 관심사가 된다.
            _recent = [t for r, t, _ in st.session_state.chat[-12:]
                       if r == "me"] + [show]
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
