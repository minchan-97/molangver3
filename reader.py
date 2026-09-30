"""
reader.py — 검색 결과의 **본문을 읽고** 요약한다.

무엇이 문제였나
  지금까지 관측으로 남는 건 검색 결과의 제목과 한 줄 요약뿐이었다.
  그래서 사전 페이지를 찾아도 들어오는 건 뜻풀이가 아니라
  'WordReference', 'Collins Korean-English Dictionary', 'Translate', 'from'
  같은 **사이트 껍데기**였다. 실제로 그것들이 꿈에 남고 관심이 되었다.

  뜻을 알고 싶어서 사전을 찾았는데 사이트 이름만 배운 셈이다.

무엇을 하나
  1) 본문을 가져온다 (표준 라이브러리만, 5초 안에)
  2) 껍데기를 걷어낸다 — 메뉴·로그인·약관·공유·사이트명
  3) **주제와 이어진 문장만** 남겨 요약한다 (로컬 계산, LLM 없음)

왜 로컬 요약인가
  요약까지 LLM에 맡기면 무엇이 남을지를 바깥 모델이 정한다.
  여기서는 '주제 낱말이 들어 있고, 문장다운 것'을 고르는 규칙으로 뽑는다.
  거칠지만 어디서 왔는지 끝까지 추적된다.
"""
from __future__ import annotations
import html
import re
import urllib.request

TIMEOUT = 5
MAX_BYTES = 400_000
KEEP_CHARS = 700

# 사이트 껍데기 — 본문이 아니라 화면 구성 요소
CHROME = re.compile(
    r"(로그인|회원가입|비밀번호|이용약관|개인정보\s*처리방침|쿠키|광고|배너|"
    r"구독|알림\s*설정|공유하기|목차|메뉴|검색어|더보기|댓글|스크랩|신고|"
    r"저작권|무단\s*전재|재배포|Copyright|All rights reserved|Sign in|Log in|"
    r"Subscribe|Advertisement|Cookie|Privacy Policy|Terms of|Share this|"
    r"WordReference|Collins|Dictionary\.com|Translate|Naver 사전|다음 사전)",
    re.I)

# 낱말 하나로 봤을 때 '내용'이 아니라 '매체'인 것들.
# 지도·꿈·관심에서 공통으로 쓴다.
MEDIUM_WORDS = {
    "사전", "백과", "백과사전", "위키", "나무위키", "블로그", "카페", "포털",
    "기사", "뉴스", "신문", "방송", "채널", "영상", "동영상", "사이트",
    "홈페이지", "게시판", "댓글", "목록", "분류", "문서", "페이지", "링크",
    "번역", "검색", "차트", "순위", "정보", "소개", "안내", "설명",
}


def is_medium(word: str) -> bool:
    """뜻이 아니라 '어디서 봤나'에 해당하는 낱말인가."""
    w = (word or "").strip()
    return w in MEDIUM_WORDS or bool(CHROME.search(w))


TAG = re.compile(r"<(script|style|nav|header|footer|aside|form)[^>]*>.*?</\1>",
                 re.S | re.I)
# 낱말 하나로 봤을 때 '내용'이 아니라 '매체'인 것들.
# 지도·꿈·관심에서 공통으로 쓴다.
MEDIUM_WORDS = {
    "사전", "백과", "백과사전", "위키", "나무위키", "블로그", "카페", "포털",
    "기사", "뉴스", "신문", "방송", "채널", "영상", "동영상", "사이트",
    "홈페이지", "게시판", "댓글", "목록", "분류", "문서", "페이지", "링크",
    "번역", "검색", "차트", "순위", "정보", "소개", "안내", "설명",
}


ANY_TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"[ \t\u00a0]+")
SENT = re.compile(r"(?<=[.!?。])\s+|\n+")


def fetch(url: str, timeout=TIMEOUT) -> str:
    """본문 글자만. 실패하면 빈 문자열 — 실패가 회차를 멈추면 안 된다."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MolangReader/1.0)",
            "Accept-Language": "ko,en;q=0.8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "html" not in ctype and "text" not in ctype:
                return ""
            raw = r.read(MAX_BYTES)
        try:
            enc = re.search(rb'charset=["\']?([\w-]+)', raw[:2000])
            text = raw.decode(enc.group(1).decode() if enc else "utf-8",
                              errors="ignore")
        except Exception:
            text = raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""

    text = TAG.sub(" ", text)
    text = ANY_TAG.sub("\n", text)
    text = html.unescape(text)
    text = SPACE.sub(" ", text)
    return text


def clean_lines(text: str) -> list:
    """껍데기를 걷어낸 줄들."""
    out = []
    for line in (text or "").split("\n"):
        s = line.strip()
        if len(s) < 12 or len(s) > 400:
            continue
        if CHROME.search(s):
            continue
        # 낱말이 아니라 기호·숫자 덩어리면 버린다
        letters = len(re.findall(r"[가-힣A-Za-z]", s))
        if letters < len(s) * 0.5:
            continue
        out.append(s)
    return out


def summarize(text: str, topic: str, keep=KEEP_CHARS) -> str:
    """
    주제와 이어진 문장만 남긴다. 로컬 계산.
      점수 = 주제 낱말 포함 + 문장다움 + 앞쪽 가산
    """
    lines = clean_lines(text)
    if not lines:
        return ""
    key = set(re.findall(r"[가-힣A-Za-z]{2,}", topic or ""))
    stems = {w[:2] for w in key if len(w) >= 2}

    scored = []
    for i, s in enumerate(lines[:300]):
        ws = set(re.findall(r"[가-힣A-Za-z]{2,}", s))
        hit = len(key & ws) + 0.5 * len(stems & {w[:2] for w in ws})
        if hit <= 0:
            continue
        # 문장다움 — 조사나 서술어가 있으면 설명문일 가능성이 높다
        proper = 1.0 + (0.4 if re.search(r"(이다|한다|된다|있다|는다|이며|으로)", s)
                        else 0.0)
        early = 1.0 + max(0.0, (60 - i) / 120)
        scored.append((hit * proper * early, s))

    if not scored:
        return ""
    scored.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for _, s in scored:
        k = s[:24]
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
        if sum(len(x) for x in out) >= keep:
            break
    return " ".join(out)[:keep]


def read(url: str, topic: str, fallback: str = "") -> dict:
    """
    본문을 읽어 요약. 못 읽으면 검색 요약(fallback)을 쓴다.
    반환: {"text", "source": "body"|"snippet"|"none", "chars"}
    """
    body = fetch(url)
    if body:
        s = summarize(body, topic)
        if len(s) >= 80:
            return {"text": s, "source": "body", "chars": len(s)}
    if fallback:
        # 검색 요약에서도 껍데기는 걷어낸다
        fb = " ".join(clean_lines(fallback)) or fallback
        if not CHROME.search(fb):
            return {"text": fb[:KEEP_CHARS], "source": "snippet",
                    "chars": len(fb)}
    return {"text": "", "source": "none", "chars": 0}
