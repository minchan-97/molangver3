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
STOP_EXACT = {'그리고', '하지만', '또한', '이는', '그것', '우리', '자신', '사용',
              '대해', '관련', '가장', '매우', '정말', '조금', '다음', '이후',
              '이전', '현재', '내용', '정보', '경우', '문제', '결과', '방법'}

HAS_DIGIT = re.compile(r'\d')


def _is_topic_like(t: str) -> bool:
    if len(t) < 2 or len(t) > 12:
        return False
    if HAS_DIGIT.search(t):
        return False
    if t in STOP_EXACT:
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


def choose_topic(state, rng=None):
    """
    검색 주제는 SEEDS 또는 이전에 실제로 검색했던 주제에서만 고른다.
    추론 태그가 그대로 검색어가 되면 관심 지형이 파편으로 채워진다.
    """
    rng = rng or random.Random()
    searched = [t for t in state.visited if t in SEEDS or ' ' in t or len(t) >= 3]

    # 35% 과감한 탐색
    if not state.interests or rng.random() < .35:
        pool = [x for x in SEEDS if state.visited.get(x, 0) < 3] or SEEDS
        return rng.choice(pool)

    ranked = sorted(
        (t for t in state.interests if t in searched or t in SEEDS),
        key=lambda t: state.interests[t] * state.novelty(t), reverse=True)
    if not ranked:
        return rng.choice(SEEDS)
    return rng.choice(ranked[:max(1, min(5, len(ranked)))])


def brave_search(query, api_key, count=5):
    if not api_key:
        return []
    url = ('https://api.search.brave.com/res/v1/web/search?'
           + urllib.parse.urlencode({'q': query, 'count': count}))
    req = urllib.request.Request(url, headers={
        'Accept': 'application/json', 'X-Subscription-Token': api_key})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    return [{'title': x.get('title', ''), 'text': x.get('description', ''),
             'url': x.get('url', '')}
            for x in data.get('web', {}).get('results', [])]


def expand_query_with_openai(topic, identity_prompt="", model=None):
    key = os.environ.get('OPENAI_API_KEY')
    if not key:
        return topic
    try:
        from openai import OpenAI
        c = OpenAI(api_key=key)
        msg = ("You are choosing one curiosity search direction for a "
               "persistent digital organism. Return ONLY a short Korean "
               "web-search query. Seek something genuinely informative and "
               "not merely useful. Current topic: " + topic
               + "\nIdentity context:\n" + identity_prompt[-2500:])
        r = c.chat.completions.create(
            model=model or os.environ.get('OPENAI_CURIOSITY_MODEL',
                                          'gpt-4o-mini'),
            messages=[{'role': 'user', 'content': msg}],
            temperature=.9, max_tokens=60)
        q = (r.choices[0].message.content or '').strip().strip('"')
        return q[:160] or topic
    except Exception:
        return topic
