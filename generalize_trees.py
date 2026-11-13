"""
generalize_trees.py — **이미 있는 지시문에서 그때 그 소재를 걷어낸다.**

왜 필요했나
  유형은 한 번 만들어 여러 번 다시 쓰인다. 그런데 만들 때 그 대화의
  질문을 보여주니 지시문에 **그때 주제가 박혀** 나왔다.

    "사용자가 언급한 **음악과 출근 상황**에서 느끼는 감정을 분석한다"
    "**경전철과 바닷가**의 감성을 연결짓는다"

  다음에 다른 주제로 그 유형을 쓰면, 지시문은 옛 주제를 말하고
  답은 새 주제를 말한다. **둘이 안 닿는다.**

  실제로 쟀더니(pathcheck) 답이 걸은 길과 닿는 정도가 **0.26** 이고
  61%는 아예 안 닿았다. 경로는 남는데 **그 경로를 따랐다고 보기
  어려운** 상태였다.

  새로 만드는 유형은 llm_bridge 에서 막았다. 이미 있는 41개는
  여기서 한 번 손본다.

무엇을 하나
  소재가 박힌 지시문만 골라, 어떤 주제에도 맞는 말로 바꾼다.
  **단계의 뜻과 순서는 그대로 둔다** — 사고 절차를 바꾸는 것이
  아니라, 그 절차를 다시 쓸 수 있게 만드는 일이다.

조심한 것
  바꾸기 전 원문을 남긴다. 계보를 손대는 일이라, 무엇을 어떻게
  바꿨는지 되짚을 수 있어야 한다.
"""
from __future__ import annotations
import json
import re
import time

TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")

# 사고 절차에 쓰이는 흔한 말 — 소재가 아니다
_ABSTRACT = {
    "감정", "상황", "이유", "근거", "기준", "차이", "관계", "대상",
    "맥락", "의도", "결론", "방향", "대화", "상대", "사용자", "생각",
    "기억", "경험", "의미", "부분", "내용", "질문", "answer", "사람",
    "정보", "사실", "가능", "필요", "중요", "구체", "전체", "방법",
    "분석", "파악", "탐색", "설계", "판단", "제시", "설명", "고려",
    "확인", "정리", "선택", "비교", "연결", "반영", "표현", "전달",
}


# 소재는 **명사**다. 동사·형용사 꼴은 절차를 말하는 말이다.
# 이걸 안 가르면 '갖춰졌는지'·'견준다' 같은 것까지 소재로 세어진다.
_VERBISH = re.compile(
    r"(한다|된다|하다|되다|있다|없다|같다|난다|간다|온다|본다|준다|"
    r"짓다|짓는다|낸다|진다|린다|른다|는다|았다|었다|였다|"
    r"하는|되는|보는|주는|나는|가는|오는|지는|리는|"
    r"하면|되면|으면|어서|아서|해서|되어|하여|하고|되고|"
    r"는지|은지|인지|려면|면서|거나|든지|지도|지만)$")

# 소재처럼 보이지만 사고 절차의 말인 것들
_PROCEDURE = {
    "먼저", "다음", "나중", "지금", "여기", "그것", "이것", "무엇",
    "어느", "서로", "각각", "모두", "다시", "아직", "이미", "실제",
    "억지", "유보", "적용", "배제", "형식", "방식", "단계", "쪽이",
}


def looks_specific(directive: str) -> list:
    """
    이 지시문에 **그때 그 소재**가 박혀 있나. 박힌 낱말을 돌려준다.

    소재는 명사다 — '음악', '출근', '경전철', '축구팀', '인공지능'.
    절차를 말하는 동사꼴('갖춰졌는지', '견준다')은 소재가 아니다.
    그걸 안 가르면 이미 일반적인 지시문까지 고치게 된다.
    """
    hits = []
    for w in TOKEN.findall(directive or ""):
        base = w.rstrip("과와의을를이가에서도만은는로으")
        if len(base) < 2:
            continue
        if base in _ABSTRACT or w in _ABSTRACT:
            continue
        if base in _PROCEDURE or w in _PROCEDURE:
            continue
        if _VERBISH.search(w) or _VERBISH.search(base):
            continue
        hits.append(base)
    return sorted(set(hits))


def _mostly_korean(t: str) -> bool:
    k = len(re.findall(r"[가-힣]", t or ""))
    a = len(re.findall(r"[A-Za-z]", t or ""))
    return (k / (k + a)) >= 0.6 if (k + a) else False


def plan(registry, only_used: bool = True, top_types: int = 0) -> list:
    """
    무엇을 고칠지. 바꾸기 전에 눈으로 볼 수 있게.

    **영어 지시문은 건드리지 않는다.** logic_db 에서 온 기본 20종이
    그런데, 실제로 걸은 경로가 508건 중 1건뿐이다. 손볼 값어치가
    없고, 괜히 바꾸면 원래 뜻만 흐려진다.

    only_used=True 면 **실제로 걸어본 유형만** 본다. 안 쓰는 것을
    고치는 데 LLM 을 쓸 이유가 없다.
    """
    trees = (getattr(registry, "trees", {}) or {})

    # **경로가 많은 유형부터.**
    #
    # 85개를 하나하나 보는 것은 무리다. 그런데 실제로는 쏠려 있다 —
    # emotion_analysis 292건, inference 73건, conditional_chain 46건…
    # 상위 다섯이 전체의 9할이다. 거기만 손봐도 효과의 대부분을
    # 가져가고, 볼 것은 열댓 개로 준다.
    order = sorted(trees.items(),
                   key=lambda kv: -len(getattr(kv[1], "history", None) or []))
    if top_types:
        order = order[:top_types]

    out = []
    for tid, tree in order:
        walked = len(getattr(tree, "history", None) or [])
        if only_used and not walked:
            continue
        for nid, node in (getattr(tree, "nodes", {}) or {}).items():
            d = getattr(node, "directive", "") or ""
            if not d or not _mostly_korean(d):
                continue
            # 이미 보고 "괜찮다" 한 것, 또는 고친 것은 건너뛴다
            if getattr(node, "_directive_ok", None) == d:
                continue
            # 규칙으로는 **후보만** 넓게 잡는다. 정말 소재가 박혔는지는
            # rewrite 에서 가린다 (규칙으로 명사와 동사꼴을 가르는 데
            # 한계가 뚜렷했다).
            hits = looks_specific(d)
            if len(hits) >= 2:
                out.append({"tree": tid, "node": nid, "walked": walked,
                            "directive": d, "specific": hits})
    # 많이 걸은 유형이 먼저 — 고칠 값어치가 큰 쪽이다
    out.sort(key=lambda r: (-r["walked"], -len(r["specific"])))
    return out


def rewrite(client, rows: list, model: str = "gpt-4o-mini",
            batch: int = 3, log=print) -> list:
    """
    한 번에 여러 개씩 다듬는다. **바꿀 것이 없으면 안 바꾼다.**

    고를 때는 규칙으로 후보만 넓게 잡고, **정말 소재가 박혔는지는
    여기서 가린다.** 규칙으로 명사와 동사꼴을 가르려 해봤지만
    '모른다고'·'밝힌다' 까지 소재로 세어졌다. 형태소 분석을 넣을
    바에는 이 자리에서 한 번 묻는 편이 낫다.

    바꿀 필요가 없으면 LLM 이 원문을 그대로 돌려주고, 그러면
    apply 가 건너뛴다.
    """
    done, ok, fail = [], [], []
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        try:
            r = client.chat.completions.create(
                model=model, temperature=0.0, max_tokens=700,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content":
                           "아래는 사고 절차의 단계별 지시문입니다. 이 절차들은 "
                           "**여러 주제에 다시 쓰입니다.**\n\n"
                           "지시문에 **특정 소재**(고유명사, 그때 그 대화에만 "
                           "해당하는 것)가 들어 있으면, 어떤 주제에도 맞는 말로 "
                           "바꾸세요. **단계의 뜻과 순서는 그대로 두세요.**\n\n"
                           "바꿔야 하는 예\n"
                           "  음악과 출근 상황에서 느끼는 감정을 분석한다\n"
                           "  → 상대가 말한 상황에서 어떤 감정이 걸리는지 짚는다\n\n"
                           "**이미 일반적이면 그대로 두세요** (그대로 출력)\n"
                           "  예: 전제가 확실하지 않다. 모른다고 말하고 무엇이 "
                           "있어야 판단할 수 있는지 밝힌다\n"
                           "  예: 쌓인 근거들이 서로 맞는지 먼저 견준다\n\n"
                           "지시문:\n"
                           + "\n".join(f"{n+1}. {c['directive']}"
                                       for n, c in enumerate(chunk))
                           + "\n\n아래 꼴의 JSON 만 출력하세요. "
                             "개수와 순서를 그대로 지키세요.\n"
                             '{"steps": ["지시문1", "지시문2", ...]}'}])
            t = r.choices[0].message.content.strip()
            t = t.replace("```json", "").replace("```", "").strip()
            fixed = json.loads(t)
            # {"steps": [...]} 로 받는다. 배열만 와도 받아준다.
            if isinstance(fixed, dict):
                fixed = (fixed.get("steps") or fixed.get("directives")
                         or next((v for v in fixed.values()
                                  if isinstance(v, list)), None))
            if not isinstance(fixed, list):
                fail.append(f"배열이 아님: {t[:40]}")
                continue
            if len(fixed) != len(chunk):
                # 개수가 어긋나면 짝을 못 맞춘다. 적게 온 만큼만 쓴다.
                fail.append(f"개수 어긋남 {len(fixed)}≠{len(chunk)}")
                if len(fixed) < len(chunk):
                    chunk = chunk[:len(fixed)]
                else:
                    fixed = fixed[:len(chunk)]
            for c, nb in zip(chunk, fixed):
                if not (isinstance(nb, str) and nb.strip()):
                    continue
                nb = nb.strip()
                if nb != c["directive"]:
                    done.append({**c, "new": nb})
                else:
                    # **이미 괜찮다고 판단된 것도 기록한다.**
                    # 안 남기면 규칙이 다음에 또 후보로 잡아서,
                    # 고쳐도 고쳐도 목록이 안 줄어든다.
                    ok.append(c)
        except Exception as e:
            fail.append(f"{type(e).__name__}: {str(e)[:60]}")
            if log:
                log(f"  다듬기 실패: {str(e)[:60]}")
    # **왜 못 했는지 들고 나온다.** 조용히 빈손으로 돌아오면
    # "바꿀 것이 없었다" 와 "부르다 실패했다" 를 구분할 수 없다.
    return done, ok, fail


def mark_ok(registry, rows: list) -> int:
    """
    **이미 주제에서 떨어져 있다**고 표시한다.

    규칙은 후보를 넓게 잡는다(86개). 그런데 실제로 바뀌는 것은
    열 개쯤이고, 나머지는 LLM 이 "이대로 괜찮다" 고 돌려보낸다.
    그 사실을 안 남기면 다음에 또 후보로 잡혀서, 고쳐도 목록이
    줄지 않는다.
    """
    n = 0
    for r in rows or []:
        tree = (getattr(registry, "trees", {}) or {}).get(r["tree"])
        node = (getattr(tree, "nodes", {}) or {}).get(r["node"]) if tree else None
        if node is None:
            continue
        try:
            setattr(node, "_directive_ok", r["directive"])
            n += 1
        except Exception:
            pass
    return n


def apply(registry, done: list, log=print) -> int:
    """
    고친다. **원문을 남긴다** — 계보를 손대는 일이라 되짚을 수 있어야 한다.
    """
    n = 0
    for d in done:
        tree = (getattr(registry, "trees", {}) or {}).get(d["tree"])
        if tree is None:
            continue
        node = (getattr(tree, "nodes", {}) or {}).get(d["node"])
        if node is None:
            continue
        try:
            if not hasattr(node, "_directive_was"):
                setattr(node, "_directive_was", node.directive)
            node.directive = d["new"]
            # 고친 것도 다시 후보가 되지 않게
            setattr(node, "_directive_ok", d["new"])
            n += 1
        except Exception:
            pass
    if n and log:
        log(f"  🌳 지시문 {n}개를 주제에서 떼어냈다")
    return n


def propose(registry, client, top_types: int = 5, log=print) -> list:
    """
    **다듬어 보기만 한다. 아직 고치지 않는다.**

    바뀐 것만 돌려주므로, 사람이 볼 것은 실제로 달라진 것뿐이다.
    LLM 이 "이미 일반적" 으로 판단한 것은 원문 그대로 와서 빠진다.
    """
    rows = plan(registry, top_types=top_types)
    if not rows:
        return []
    done, ok, fail = rewrite(client, rows, log=log)
    # 괜찮다고 판단된 것은 **그 자리에서 표시**해 둔다.
    # 사람이 고를 일이 없고, 다시 후보로 올라오면 안 된다.
    mark_ok(registry, ok)
    if fail:
        # 실패한 것은 표시하지 않는다 — 다시 해봐야 한다
        propose.last_error = fail[:3]
    else:
        propose.last_error = []
    return done


def run(sb, registry, client, picked: list = None,
        top_types: int = 5, log=print) -> dict:
    """
    picked 를 주면 **그것만** 고친다 (사람이 고른 것).
    안 주면 다듬은 것을 전부 고친다.
    """
    done = picked if picked is not None else propose(
        registry, client, top_types=top_types, log=log)
    n = apply(registry, done or [], log=log)

    # **아무것도 안 고쳤어도 저장한다.**
    # propose 가 "이미 괜찮다" 로 표시해 둔 것들이 있다. 그걸 안
    # 남기면 다음에 또 후보로 올라와서, 눌러도 목록이 안 줄어든다.
    try:
        import registry_store
        registry_store.save(sb, registry)
    except Exception:
        pass

    if not done:
        return {"rewrote": 0, "skip": "바꿀 것이 없다", "at": time.time()}
    return {"rewrote": n, "at": time.time()}
