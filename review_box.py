"""
review_box.py — 검토 대기를 한 곳에서 본다.

문제
  몰랑이에는 검토함이 두 개 있었다.
    · molang_quarantine        — 대화에서 애매했던 사실
    · organism_observations    — 워커(호기심 루프)가 찾아온 것 중 격리된 것
  앱 사이드바는 앞의 것만 읽어서, 워커가 3건을 격리해도 화면에는 0으로 보였다.

여기서는 둘을 합쳐서 보여주고, 승인·거절도 각각의 자리로 돌려보낸다.

상태 표기
  organism_observations.status:  candidate(후보) / quarantine(격리) / reject(거부)
  승인하면 candidate 로, 거절하면 reject 로 바꾼다.
"""
from __future__ import annotations


def pending(sb, identity, limit: int = 20) -> list[dict]:
    """두 검토함의 대기 항목을 합쳐서 최신순으로."""
    out = []

    # 1) 대화에서 격리된 사실
    try:
        for r in (identity.pending_quarantine(limit) or []):
            out.append({
                "where": "fact",
                "id": r.get("id"),
                "title": str(r.get("text") or "")[:80],
                "reason": r.get("reason") or "확신 전",
                "url": None,
                "at": r.get("created_at"),
            })
    except Exception:
        pass

    # 2) 워커가 찾아와 격리된 관측
    try:
        # 이 표의 시각 열은 created_at 이 아니라 seen_at 이다.
        # 틀린 열을 읽으면 조회가 통째로 실패하고, 예외를 삼키면
        # '워커가 찾은 것'이 목록에 한 건도 안 뜬다 (실제로 그랬다).
        rows = (sb.table("organism_observations")
                .select("id,topic,title,text,url,status,score,seen_at")
                .eq("status", "quarantine")
                .order("id", desc=True).limit(limit).execute().data) or []
        for r in rows:
            out.append({
                "where": "observation",
                "id": r.get("id"),
                "title": (r.get("title") or r.get("text") or "")[:80],
                "reason": f"{r.get('topic','')} · 점수 {round(r.get('score') or 0, 2)}",
                "url": r.get("url"),
                "at": r.get("seen_at"),
            })
    except Exception as e:
        out.append({"where": "error", "id": 0,
                    "title": f"워커 검토함 읽기 실패: {str(e)[:80]}",
                    "reason": "", "url": None, "at": ""})

    out.sort(key=lambda x: str(x.get("at") or ""), reverse=True)
    return out[:limit]


def approve(sb, identity, item) -> dict:
    """
    승인. 격리 항목은 molang_quarantine 에 있으므로 거기를 닫고,
    내용을 실제 사실로 올린다.
    (identity.approve() 는 molang_facts 의 id 를 받는다 — 격리 id 와 다르다.
     이걸 혼동해서 눌러도 목록이 안 줄어들었다)
    """
    try:
        if item["where"] == "fact":
            res = sb.table("molang_quarantine").update(
                {"resolved": "approved"}).eq("id", item["id"]).execute()
            if not (getattr(res, "data", None) or []):
                return {"ok": False,
                        "error": f"격리 {item['id']}번을 못 찾았어요 "
                                 "(이미 처리됐거나 권한 문제)"}
            text = (item.get("title") or "").strip()
            if text:
                # source 는 '어디서 왔나'(user/assistant/search/nudge),
                # human 은 trust 쪽 값이다. 격리된 것은 대화에서 온 것이므로 user.
                identity._reinforce_or_add(text, source="user")
                # 사람이 승인한 것은 바로 확신으로
                rows = (sb.table("molang_facts").select("id")
                        .eq("text", text).limit(1).execute().data) or []
                if rows:
                    identity.approve(rows[0]["id"])
            identity.reload()
        else:
            res = sb.table("organism_observations").update(
                {"status": "candidate"}).eq("id", item["id"]).execute()
            if not (getattr(res, "data", None) or []):
                return {"ok": False,
                        "error": f"관측 {item['id']}번을 못 바꿨어요 "
                                 "(RLS 로 update 가 막혔을 수 있어요)"}
        return {"ok": True, "as_fact": bool(item.get("where") == "fact"
                                            and len(item.get("title") or "") <= 80)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def reject(sb, identity, item) -> dict:
    try:
        if item["where"] == "fact":
            res = sb.table("molang_quarantine").update(
                {"resolved": "rejected"}).eq("id", item["id"]).execute()
            if not (getattr(res, "data", None) or []):
                return {"ok": False, "error": f"격리 {item['id']}번을 못 찾았어요"}
            identity.reload()
        else:
            res = sb.table("organism_observations").update(
                {"status": "reject"}).eq("id", item["id"]).execute()
            if not (getattr(res, "data", None) or []):
                return {"ok": False, "error": f"관측 {item['id']}번을 못 바꿨어요"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def counts(sb, identity) -> dict:
    """사이드바 숫자용 — 어디에 몇 건인지."""
    n_fact = n_obs = 0
    try:
        n_fact = len(identity.pending_quarantine(50) or [])
    except Exception:
        pass
    try:
        res = (sb.table("organism_observations").select("id", count="exact")
               .eq("status", "quarantine").execute())
        n_obs = res.count or 0
    except Exception:
        pass
    return {"fact": n_fact, "observation": n_obs, "total": n_fact + n_obs}
