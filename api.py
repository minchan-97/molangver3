"""
api.py — 몰랑이를 앱·단축어에서 부를 수 있게 하는 API 층.

설계 원칙: **코어는 손대지 않는다.**
  UnifiedIdentity(판단 트리 + 정체성 기억)와 SupabaseIdentity(상태)는 그대로 쓰고,
  이 파일은 HTTP 창구만 연다. 나중에 화면이 Streamlit이든 네이티브 앱이든
  이 창구를 그대로 쓴다.

창구
  GET  /health            살아있나
  POST /chat              말 걸기 → 답 + 판단 경로
  GET  /state             지금 몰랑이가 아는 것 (확신/미확신/대화수)
  GET  /pending           검토 대기(격리된 사실)
  POST /approve           격리된 사실 승인
  POST /doubt             격리된 사실 의심(약화)
  POST /feedback          답변에 대한 반응 → 트리 진화

인증
  헤더 X-Molang-Key 에 MOLANG_API_KEY 값. 없으면 401.
  (단축어에서 헤더 한 줄로 넣을 수 있다)

실행
  uvicorn api:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations
import os, time, hmac, hashlib
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

API_KEY = os.environ.get("MOLANG_API_KEY", "")
MODEL = os.environ.get("MOLANG_MODEL", "gpt-4o-mini")

app = FastAPI(title="몰랑이 API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


def _auth(key: Optional[str]):
    if not API_KEY:
        return                      # 키를 안 걸어두면 통과 (로컬 시험용)
    if not key or not hmac.compare_digest(key, API_KEY):
        raise HTTPException(401, "키가 없거나 틀렸어요")


# ── 몰랑이 불러오기 (한 번만) ────────────────────────────────
_STATE = {"identity": None, "sb": None, "store": None, "last": None}


def _boot():
    if _STATE["identity"] is not None:
        return _STATE
    from supabase import create_client
    from molang_store import SupabaseIdentity
    from unified_identity import UnifiedIdentity

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    store = SupabaseIdentity(sb)
    ident = UnifiedIdentity(memory=store)
    _STATE.update(sb=sb, store=store, identity=ident)
    return _STATE


def _llm():
    """LLM 호출자 (답변 생성 / 유형 판별 / 트리 설계에 주입)."""
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def answer_fn(question, context=""):
        sys = _STATE["store"].to_system_prompt()
        msgs = [{"role": "system", "content": sys}]
        if context:
            msgs.append({"role": "system", "content": f"판단 경로: {context}"})
        msgs.append({"role": "user", "content": question})
        r = client.chat.completions.create(model=MODEL, messages=msgs,
                                           temperature=0.7)
        return r.choices[0].message.content
    return answer_fn


# ── 요청/응답 모양 ───────────────────────────────────────────
class ChatIn(BaseModel):
    text: str
    speak: bool = False          # True면 답을 짧게 (음성용)


class ChatOut(BaseModel):
    answer: str
    type_id: Optional[str] = None
    path: list = []
    facts: int = 0
    turn_id: Optional[str] = None
    elapsed: float = 0


class FeedbackIn(BaseModel):
    turn_id: str
    score: float = 1.0           # +1 긍정 ~ -1 부정
    corrected: bool = False      # 내가 고쳐준 경우 (확정 기억으로 굳힘)


class FactIn(BaseModel):
    fact_id: int


# ── 창구 ─────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"ok": True, "at": time.time()}


@app.post("/chat", response_model=ChatOut)
def chat(body: ChatIn, x_molang_key: str = Header(None)):
    _auth(x_molang_key)
    s = _boot()
    t0 = time.time()
    q = body.text.strip()
    if not q:
        raise HTTPException(400, "할 말이 비어 있어요")
    if body.speak:
        q += "\n(음성으로 들을 거라 세 문장 안으로 짧게)"

    answer_fn = _llm()
    try:
        out = s["identity"].think(q, answer_fn=answer_fn)
    except Exception as e:
        raise HTTPException(500, f"생각하다 막혔어요: {e}")

    answer = out.get("answer") or ""
    turn_id = hashlib.sha1(f"{q}{t0}".encode()).hexdigest()[:12]
    _STATE["last"] = {"turn_id": turn_id, "question": q, "answer": answer,
                      "result": out, "type_id": out.get("type")}
    try:                            # 대화 내용 흡수 (확신은 반복되어야 굳는다)
        s["store"].absorb(q, answer)
    except Exception:
        pass
    return ChatOut(answer=answer, type_id=out.get("type"),
                   path=list(out.get("path") or []),
                   facts=len(s["store"].learned_facts),
                   turn_id=turn_id, elapsed=round(time.time() - t0, 2))


@app.post("/feedback")
def feedback(body: FeedbackIn, x_molang_key: str = Header(None)):
    _auth(x_molang_key)
    s = _boot()
    last = _STATE.get("last")
    if not last or last["turn_id"] != body.turn_id:
        raise HTTPException(404, "그 대화를 못 찾겠어요")
    result = last.get("result")
    if not result:
        return {"ok": False, "note": "경로 기록이 없어 학습을 건너뜁니다"}
    try:
        # 코어의 react()가 트리 학습 + 망각까지 한 번에 한다 (중복 구현 금지)
        s["identity"].react(result, float(body.score),
                            was_corrected=bool(body.corrected))
        return {"ok": True, "type": last["type_id"]}
    except Exception as e:
        raise HTTPException(500, f"학습 실패: {e}")


@app.get("/state")
def state(x_molang_key: str = Header(None)):
    _auth(x_molang_key)
    s = _boot()
    st = s["store"]
    facts = st.learned_facts
    sure = [f for f in facts if (f.get("strength") or 0) >= 0.8]
    return {"확신": [f["text"] for f in sure][:20],
            "아직_확신못함": len(facts) - len(sure),
            "배운_사실": len(facts),
            "대화수": len(st.episodic),
            "상태": s["identity"].status()}


@app.get("/pending")
def pending(x_molang_key: str = Header(None)):
    _auth(x_molang_key)
    s = _boot()
    return {"대기": s["store"].pending_quarantine()}


@app.post("/approve")
def approve(body: FactIn, x_molang_key: str = Header(None)):
    _auth(x_molang_key)
    _boot()["store"].approve(body.fact_id)
    return {"ok": True}


@app.post("/doubt")
def doubt(body: FactIn, x_molang_key: str = Header(None)):
    _auth(x_molang_key)
    _boot()["store"].doubt(body.fact_id)
    return {"ok": True}
