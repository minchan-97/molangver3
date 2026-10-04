"""organism/curiosity.py — 관심 지형 오염 수정판.

발견된 문제:
  infer_topics() 가 단순 빈도 상위 토큰을 반환하는데, 한국어에서는
  '가진다', '견디는', '200미터' 같은 활용형·수치가 상위에 올라온다.
  worker 가 이걸 state.interests 에 0.03 씩 누적시키고,
  choose_topic() 은 interests 를 랭킹해 다음 검색어로 쓴다.
  3 사이클만 돌려도 '가진다'(1.475)가 실제 주제보다 높아졌다.
  하루 24 사이클이면 관심 지형이 어미와 숫자로 채워진다.

수정:
  1. 형태 필터 — 숫자 포함, 1글자, 흔한 어미/기능어 제외
  2. 추론 태그와 검색 주제를 분리 — choose_topic 은 실제로 검색했던
     주제(visited)와 SEEDS 에서만 고른다. 태그는 SOM 분석용으로만 남는다.
"""
from __future__ import annotations
import json
import os
import random
import re
import urllib.parse
import urllib.request

from .embedder import tokens

SEEDS = ["심해 생물", "고대 도시", "천문학", "언어의 진화", "동물 행동", "음향학",
         "재료과학", "식물의 신호", "지도 제작", "민속 음악", "기상 현상", "수학사"]

# 활용형 어미·기능어·수치. 관심 지형에 올라오면 안 되는 것들.
STOP_SUFFIX = ('하는', '되는', '있는', '없는', '가진', '가진다', '한다', '된다',
               '이다', '있다', '없다', '에서', '으로', '까지', '부터', '보다',
               '통해', '위해', '대한', '같은', '다른', '많은', '경우', '때문',
               '이런', '그런', '저런', '것은', '것이', '수가', '등의')
# 대화에서 관심사를 뽑기 시작하면서 들어온 것들:
# 대명사·추임새·말끝·감탄사는 주제가 아니다.
TALK_WORDS = {
    '너가', '너는', '나는', '내가', '우리', '저기', '그거', '이거', '요거',
    '히힛', '헤헤', '하하', '흐흐', '음음', '우와', '오오', '그래', '그럼',
    '있어', '없어', '같아', '맞아', '좋아', '싫어', '알아', '몰라', '했어',
    '한다', '하자', '해봐', '보자', '어떤', '무슨', '어디', '언제', '누가',
    '진짜', '정말', '완전', '너무', '조금', '아직', '이제', '다시', '계속',
    '오늘', '어제', '내일', '지금', '아까', '나중', '요즘', '평소', '가끔',
    '궁금해', '좋아해', '싫어해', '재밌어', '신기해', '너의', '나의', '우리의',
    '많이', '조금', '자주', '아주', '약간', '그냥', '역시', '이제', '항상',
    '싶어', '싶다', '했어', '봤어', '들었어', '있었어', '같은', '이런', '저런',
    '이야기', '얘기', '생각', '느낌', '기분', '정도', '때문', '경우', '부분',
    '혹시', '여러', '같이', '함께', '서로', '모두', '다른', '어떻', '무엇',
    '오늘', '내일', '어제', '이번', '다음', '처음', '마지막', '다시', '진짜',
    'strong', 'quot', 'href', 'http', 'https', 'www', 'span', 'div', 'amp',
    'nbsp', 'br', 'em', 'li', 'ul',
}

STOP_EXACT = {'그리고', '하지만', '또한', '이는', '그것', '우리', '자신', '사용',
              '대해', '관련', '가장', '매우', '정말', '조금', '다음', '이후',
              '이전', '현재', '내용', '정보', '경우', '문제', '결과', '방법'}

# **잘린 말** — 어미가 떨어져 나간 조각들.
# '아무래도' 가 '아무래' 로, '뭔가요' 가 '뭔가' 로 들어와 관심 3위·7위까지
# 올라간 일이 있었다. 주제가 아닌 것이 자리를 차지하면 진짜 주제가 밀린다.
# 꿈에서 '남은 낱말' 로 뽑히면 더 올라가므로 입구에서 막는다.
BROKEN = {
    '아무래', '아무리', '어쩌면', '그러면', '그런데', '그래서', '그러니',
    '뭔가', '뭐하고', '뭐가', '무엇', '어쩌', '하여', '이러', '저러',
    '보면서', '하면서', '되면서', '이면서',
    '거의', '만들어봤어', '알려줘', '보여줘', '들려줘',
    '제가', '모르', '일이', '있었어요', '이라고', '라고',
    '같은', '다양한', '여러', '수많', '온갖',
}

HAS_DIGIT = re.compile(r'\d')


# 이름은 주제로 남긴다 — 자기가 누구인지 알아보는 건 막을 이유가 없다.
# 다만 부르는 말('몰랑아')과 줄인 말('몰랑')은 이름 하나로 합친다.
# 안 그러면 같은 관심이 셋으로 갈려 셋 다 약해지고, 목록만 지저분해진다.
NAME_CANON = {
    "몰랑": "몰랑이", "몰랑아": "몰랑이", "몰랑이": "몰랑이", "몰랑이는": "몰랑이",
    "피우": "피우피우", "피우야": "피우피우", "피우피우": "피우피우",
}


def canon_name(t: str) -> str:
    return NAME_CANON.get(t, t)


def _looks_proper(t: str) -> bool:
    """
    고유명사처럼 보이는가 — 가수 이름, 작품 이름, 브랜드.
    사전이 없으니 형태로 짐작한다: 흔한 말이 아니고, 조사·어미가 안 붙고,
    2~6글자인 것. ('한로로', '몰랑이' 같은 것)
    """
    if not (2 <= len(t) <= 6):
        return False
    if t.endswith(STOP_SUFFIX) or t in STOP_EXACT or t in TALK_WORDS:
        return False
    if HAS_DIGIT.search(t):
        return False
    # 서술어·감탄 어미로 끝나면 이름이 아니다 ('궁금해', '좋아', '먹지')
    if t[-1] in '해야어지다네요까게고죠임됨':
        return False
    return bool(re.fullmatch(r'[가-힣]+', t)) and t == strip_josa(t)


JOSA = ('으로', '에서', '에게', '한테', '까지', '부터', '이랑', '하고',
        '들이', '들은', '들을', '들의', '이다', '이야', '예요', '에요',
        '처럼', '보다', '마다', '조차', '밖에', '대로', '라고', '이라',
        '은', '는', '이', '가', '을', '를', '에', '의', '도', '만',
        '과', '와', '로', '랑')


def strip_josa(t: str) -> str:
    """
    조사를 벗겨 원래 낱말로. '우주에' 와 '우주' 가 따로 쌓이면
    같은 관심이 둘로 갈려 둘 다 약해진다.
    두 글자 이상 남을 때만 벗긴다 ('나는' → '나' 처럼 되지 않게).
    """
    # '한로로' 처럼 끝 두 글자가 같으면 벗기지 않는다 (이름일 가능성)
    if len(t) >= 3 and t[-1] == t[-2]:
        return t
    for j in sorted(JOSA, key=len, reverse=True):
        if t.endswith(j) and len(t) - len(j) >= 2:
            return t[:-len(j)]
    return t


def _is_topic_like(t: str) -> bool:
    if len(t) < 2 or len(t) > 12:
        return False
    if HAS_DIGIT.search(t):
        return False
    if t in TALK_WORDS:
        return False
    if t in NAME_CANON:
        return True                       # 이름은 통과
    if len(t) <= 3 and t[-1] in '어아지네게까죠':
        return False                      # '싶어', '봤어' 같은 말끝
    # 네 글자 이상인데 연결·종결 어미로 끝나면 동사 활용형이다.
    # ('들어보려고', '알아가면서') — 두 글자 명사(사고·창고)는 걸리지 않는다.
    # '듣는다', '한다' 같은 서술형. '바다'가 걸리지 않게 끝 두 글자로 본다.
    if len(t) >= 3 and t.endswith(('는다', '한다', '된다', '인다', '진다',
                                   '났다', '왔다', '갔다', '봤다', '한테')):
        return False
    if len(t) >= 4 and (t.endswith(('려고', '면서', '으며', '하며', '지만',
                                    '거나', '든지', '어서', '아서', '려는',
                                    '했던', '하던', '보려', '으려'))
                        or t[-1] in '고며서면'):
        return False
    # **잘린 말 검사는 고유명사 판정보다 먼저.**
    # '아무래', '뭔가' 는 한글 두세 글자라 고유명사로 오인돼 통과했다.
    if t in BROKEN:
        return False

    if _looks_proper(t):
        return True          # 가수·작품 이름 같은 고유명사는 살린다
    if t in STOP_EXACT or t in BROKEN:
        return False
    if t.endswith(STOP_SUFFIX):
        return False
    # 3글자 이상에서 동사 활용형(~는)과 목적격 조사(~를/을)는 명사가 아니다.
    # 2글자는 제외: '지도'의 '도' 같은 정상 명사 말음을 죽이지 않기 위함.
    if len(t) >= 3 and t.endswith(('는', '를', '을', '며', '면서')):
        return False
    return True


def infer_topics(text, n=5):
    """가벼운 태그 추출. 로컬·결정론적. 검색 주제로는 쓰지 않는다."""
    freq = {}
    for t in tokens(text):
        if _is_topic_like(t):
            freq[t] = freq.get(t, 0) + 1
    return [k for k, _ in sorted(freq.items(),
                                 key=lambda kv: (-kv[1], kv[0]))[:n]]


def choose_topic(state, rng=None, subs=None):
    """
    주제 고르기. 세 갈래를 섞는다.

      1) 자유 탐색 (EXPLORE_RATE) — 목적과 무관하게 아무거나.
         호기심이 목적인 존재가 정해진 것만 보면 목적을 스스로 배반한다.
      2) 관심사 기반 — 대화에서 스며든 것과 검색으로 쌓인 것.
         점수 = 관심도 × 새로움 × 목적 친화도
      3) 막히면 씨앗 목록.

    관심사에서 고를 때도 '주제처럼 생긴 말'만 쓴다. 조사나 파편이 검색어가
    되면 관심 지형이 부스러기로 채워진다.
    """
    rng = rng or random.Random()
    try:
        import purpose
        explore, aff = purpose.EXPLORE_RATE, purpose.affinity
    except Exception:
        explore, aff = 0.35, (lambda t: 1.0)

    def ok(t):
        return t in SEEDS or (' ' in t and len(t) >= 3) or _is_topic_like(t)

    # 1) 자유 탐색
    if not state.interests or rng.random() < explore:
        pool = [x for x in SEEDS if state.visited.get(x, 0) < 3] or SEEDS
        # 씨앗 말고 예전에 파본 주제도 가끔 다시 (완전한 무작위성 유지)
        seen = [t for t in state.visited if ok(t)]
        if seen and rng.random() < 0.3:
            pool = pool + seen
        return rng.choice(pool)

    # 2) 관심사 — 핵심 목적 친화도 × **승인된 하위 목적** 가중치
    #    하위 목적은 지금까지 저장만 되고 아무 데서도 읽히지 않았다.
    #    승인한 목적이 행동을 바꾸지 않으면 그건 목적이 아니라 메모다.
    scores = {t: state.interests[t] * state.novelty(t) * aff(t)
              for t in state.interests if ok(t)}
    if subs:
        try:
            import purpose_drive
            scores = purpose_drive.weight_topics(subs, scores)
        except Exception:
            pass
    ranked = sorted(scores, key=lambda t: -scores[t])
    if not ranked:
        return rng.choice(SEEDS)

    # 상위에서 **점수에 비례해** 뽑는다.
    # 예전에는 상위 5개 중 무작위였다. 그러면 목적 가중치를 실어도
    # 5개 안에만 들면 똑같은 확률이라 아무 차이가 없다.
    top = ranked[:max(1, min(8, len(ranked)))]
    weights = [max(1e-6, scores[t]) for t in top]
    total = sum(weights)
    pick = rng.random() * total
    acc = 0.0
    for t, w in zip(top, weights):
        acc += w
        if acc >= pick:
            return t
    return top[-1]


def nudge_from_memory(state, facts, weight=0.15, n=2, cue=None):
    """
    회상에서 탐색 주제를 얻는다.
    대화가 없어도 '문득 떠오른 것'이 관심이 되는 길 — 사람도 그렇다.
    대화로 올리는 것(0.08)보다 조금 세게 준다. 오래 묵은 기억이 떠오른 것이라.
    """
    try:
        import reminisce
    except Exception:
        return []
    got = reminisce.pick(facts or [], state.interests,
                         reminisce.recent_ids(state), n=n, cue=cue)
    bumped = []
    for f in got:
        topic = reminisce.to_topic(f)
        if not topic:
            continue
        old = float(state.interests.get(topic, 0.0))
        # 이미 큰 관심은 회상으로 더 키우지 않는다.
        # 같은 기억이 반복 호출돼도 한쪽만 부풀지 않게.
        if old >= 2.0:
            continue
        state.interests[topic] = max(0.0, min(5.0, old + weight))
        bumped.append(topic)
    if got:
        reminisce.remember_used(state, [f.get("id") for f in got])
    # 계기로 떠오른 것인지 함께 돌려준다 (어디서 떠올랐는지 로그에 남게)
    by_cue = [f for f in got if f.get("_by_cue")]
    if by_cue:
        return {"words": bumped, "by_cue": True,
                "from": [f.get("text", "")[:30] for f in by_cue]}
    return bumped


def nudge_interests(state, texts, weight=None, min_mentions=None):
    """
    대화에서 관심사를 조금씩 올린다. (한 번 말했다고 바로 파지 않는다)
    texts: 최근 대화 문장들. 여러 번 나온 주제어만, 작은 가중치로.
    반환: 올라간 주제 목록
    """
    try:
        import purpose
        weight = purpose.NUDGE_WEIGHT if weight is None else weight
        min_mentions = purpose.MIN_MENTIONS if min_mentions is None else min_mentions
    except Exception:
        weight = weight or 0.08
        min_mentions = min_mentions or 2

    freq = {}
    for text in texts:
        for t in tokens(text or ''):
            t = canon_name(strip_josa(t))   # '우주에'→'우주', '몰랑아'→'몰랑이' 
            if _is_topic_like(t):
                freq[t] = freq.get(t, 0) + 1

    bumped = []
    for t, n in sorted(freq.items(), key=lambda kv: -kv[1]):
        if n < min_mentions:
            continue
        old = float(state.interests.get(t, 0.0))
        state.interests[t] = max(0.0, min(5.0, old + weight * min(n, 4)))
        bumped.append(t)
        if len(bumped) >= 5:
            break
    return bumped


def brave_search(query, api_key, count=5):
    if not api_key:
        return []
    url = ('https://api.search.brave.com/res/v1/web/search?'
           + urllib.parse.urlencode({'q': query, 'count': count}))
    req = urllib.request.Request(url, headers={
        'Accept': 'application/json', 'X-Subscription-Token': api_key})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    items = [{'title': x.get('title', ''), 'text': x.get('description', ''),
              'url': x.get('url', '')}
             for x in data.get('web', {}).get('results', [])]

    # **본문을 읽는다.** 제목과 한 줄 요약만 담으면, 사전을 찾아도
    # 뜻풀이가 아니라 'WordReference', 'Dictionary' 같은 사이트 껍데기가
    # 관측으로 남는다 (실제로 그것들이 꿈에 나오고 관심이 되었다).
    try:
        import reader
        topic = query or ''
        for it in items[:3]:            # 앞의 셋만 — 시간과 예의를 지킨다
            got = reader.read(it.get('url', ''), topic, it.get('text', ''))
            if got['text']:
                it['text'] = got['text']
                it['read'] = got['source']
    except Exception:
        pass
    return items


def expand_query_with_openai(topic, identity_prompt="", model=None,
                            purpose_ctx=""):
    # 이름은 넓히지 않는다. '한로로'를 풀어 쓰면 다른 것이 된다.
    if topic in NAME_CANON or (len(topic) <= 4 and _looks_proper(topic)):
        return topic
    key = os.environ.get('OPENAI_API_KEY')
    if not key:
        return topic
    try:
        from openai import OpenAI
        c = OpenAI(api_key=key)
        try:                      # 목적을 문맥에 얹는다 (없어도 동작)
            import purpose
            why = purpose.query_context()
        except Exception:
            why = ""
        if purpose_ctx:
            identity_prompt = (identity_prompt or "") + "\n" + purpose_ctx
        msg = ("Return ONLY the search query itself — no greeting, no name, "
               "no quotes, no explanation. 8 words max. "
               "You are choosing one curiosity search direction for a "
               "persistent digital organism. Return ONLY a short Korean "
               "web-search query. Seek something genuinely informative and "
               "not merely useful. " + why
               + "\nCurrent topic: " + topic
               + "\nIdentity context:\n" + identity_prompt[-2500:])
        r = c.chat.completions.create(
            model=model or os.environ.get('OPENAI_CURIOSITY_MODEL',
                                          'gpt-4o-mini'),
            messages=[{'role': 'user', 'content': msg}],
            temperature=.9, max_tokens=60)
        q = (r.choices[0].message.content or '').strip().strip('"')

        # 말투가 섞이면 버린다.
        # 실제로 "오, 찬기! 피우피우에 대한 흥미로운 검색어는 이거야: …" 가
        # 그대로 Brave 에 들어갔다. 정체성 프롬프트를 문맥으로 주다 보니
        # 검색어가 아니라 '몰랑이의 대답'이 나온 것이다.
        if ':' in q:                       # "…는 이거야: 실제검색어"
            q = q.split(':')[-1].strip().strip('"')
        bad = ('찬기', '오,', '이거야', '검색어', '안녕', '히힛', '!')
        if any(b in q for b in bad) or len(q) > 60 or not q:
            return topic                   # 의심스러우면 주제를 그대로

        # **주제가 확장된 검색어에 남아 있어야 한다.**
        # 없으면 LLM 이 다른 말로 바꾼 것이다 — 실제로 '한로로'가 '한로'(절기)로,
        # '몰랑이'가 '모링가'로 바뀌어 엉뚱한 자료를 긁어왔다.
        # 이름은 비슷한 말이 많아 특히 잘 어긋난다.
        core = topic.strip()
        if core and core not in q:
            # 이름이면 **정확히** 있어야 한다. 앞 두 글자만 맞으면
            # '한로로'가 '한로'(절기)로 바뀐 것도 통과해 버린다.
            if _looks_proper(core) or core in NAME_CANON:
                return topic
            head = core[:2]
            if not (len(core) >= 3 and head in q):
                return topic               # 주제를 잃었으면 원래대로
        return q[:160]
    except Exception:
        return topic
