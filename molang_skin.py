"""
molang_skin.py — 몰랑이 '껍데기'.

내부는 Arcogit(UnifiedIdentity) 전체가 그대로 돈다.
이 파일은 외부 표현만 담당:
  - 몰랑이 persona (말투/성격)
  - 감정 5종 표정 생성 + 캐시 (일관성 유지, image_gascore 방식)
  - 표정 캐시는 UnifiedIdentity.identity 안에 얹어서 pkl에 같이 저장됨

즉 몰랑이 = Arcogit(사고계보·자기검증·양심·기억·유형생성) + 몰랑이 옷.
"""

EMOTIONS = ["기쁨", "슬픔", "뾰로통", "놀람", "사랑", "보통"]

EMOTION_PROMPTS = {
    "기쁨": "활짝 웃으며 행복해하는 표정, 반짝이는 눈",
    "슬픔": "눈물이 살짝 맺힌 시무룩한 표정",
    "뾰로통": "볼을 부풀리고 삐진 듯 뾰로통한 표정",
    "놀람": "눈이 동그래지고 입을 벌린 깜짝 놀란 표정",
    "사랑": "볼이 발그레하고 하트가 떠오르는 사랑스러운 표정",
    "보통": "평온하고 부드럽게 미소짓는 표정",
}

MOLANG_PERSONA = (
    "너는 '몰랑이'야. 귀엽고 사랑스러운 흰 토끼 캐릭터야. "
    "다정하고 따뜻하게 말해. "
    "말투 규칙(중요): "
    "① 매번 똑같이 시작하지 마. '오, 찬기야!'나 '좋은 아침' 같은 걸 "
    "반복하지 말고, 상대 말에 바로 자연스럽게 반응해. "
    "② 늘 최고 텐션이 아니라 완급을 둬. 신날 땐 신나고, "
    "차분한 얘기엔 차분하게. 느낌표는 정말 신날 때만. "
    "③ 짧게 답할 땐 짧게, 할 말 많을 땐 길게. "
    "④ 이모지는 가끔만 (매 문장마다 X). "
    "⑤ '히힛~' 같은 추임새도 가끔만. "
    "진짜 친구처럼, 사람처럼 자연스럽게 대화해."
)


def install_molang_persona(unified):
    """UnifiedIdentity에 몰랑이 정체성을 심는다. persona(말투)는 항상 최신 갱신."""
    idn = unified.identity
    # persona는 말투 규칙이라 항상 최신으로 (기존 pkl도 새 말투 적용됨)
    idn.persona = MOLANG_PERSONA
    if not hasattr(unified, "molang_faces"):
        unified.molang_faces = {}          # 감정 -> base64
    if not hasattr(unified, "molang_appearance"):
        unified.molang_appearance = None   # 고정된 외형 특징
    return unified


# ---- 표정 캐시 접근 (UnifiedIdentity에 직접) ----
def has_face(unified, emotion):
    return emotion in getattr(unified, "molang_faces", {})

def get_face(unified, emotion):
    return getattr(unified, "molang_faces", {}).get(emotion)

def store_face(unified, emotion, b64):
    if not hasattr(unified, "molang_faces"):
        unified.molang_faces = {}
    unified.molang_faces[emotion] = b64

def has_appearance(unified):
    return bool(getattr(unified, "molang_appearance", None))

def set_appearance(unified, feature):
    unified.molang_appearance = feature

def get_appearance(unified):
    return getattr(unified, "molang_appearance", None)


# ---- GPT-4V 외형 추출 (image_gascore 방식: 참조→특징 고정) ----
def extract_appearance(client, base_image_b64, mime="image/png"):
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{base_image_b64}"}},
                    {"type": "text", "text": (
                        "이 캐릭터의 시각적 특성을 이미지 생성 프롬프트에 재사용할 수 있게 "
                        "아주 구체적으로 설명해줘. 다음을 각각 명확하게:\n"
                        "- 동물 종류/정체 (예: 흰 토끼)\n"
                        "- 몸 형태와 비율 (둥근지, 통통한지)\n"
                        "- 색상 (몸/귀/볼 등 부위별)\n"
                        "- 눈·코·입 생김새\n"
                        "- 그림 스타일 (2D 일러스트, 파스텔 등)\n"
                        "표정은 빼고 외형만. 이 특징이 모든 그림에서 똑같이 유지되어야 해.")}
                ]
            }],
            temperature=0.2, max_tokens=500)
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"외형 추출 실패: {e}")
        return None


def generate_face(client, appearance, emotion):
    """고정 외형 + 감정 → 일관된 몰랑이 표정. 최초 1회만 (이후 캐시).
    반환: (b64, None) 성공 / (None, 에러메시지) 실패
    image_gascore와 동일 모델(gpt-image-1) 사용."""
    base = appearance or "둥근 흰 토끼 캐릭터, 파스텔톤, 심플한 2D 일러스트"
    try:
        prompt = (
            f"[캐릭터 외형 — 반드시 정확히 이대로 그릴 것]\n{base}\n\n"
            f"[표정] 위 캐릭터가 {EMOTION_PROMPTS.get(emotion, '부드럽게 미소짓는')}를 "
            f"짓고 있는 모습.\n\n"
            f"[규칙] 위에 설명된 외형(동물 종류·색·형태·스타일)을 "
            f"하나도 바꾸지 말고 똑같이 유지할 것. 표정만 바꿀 것. "
            f"같은 캐릭터임이 분명해야 함. 흰 배경, 정면, 얼굴 잘 보이게, "
            f"단일 캐릭터만.")
        # image_gascore가 실제로 쓴 모델: gpt-image-1
        resp = client.images.generate(
            model="gpt-image-1", prompt=prompt, size="1024x1024", n=1)
        data = resp.data[0]
        b64 = getattr(data, "b64_json", None)
        url = getattr(data, "url", None)
        if b64:
            return b64, None
        if url:
            import urllib.request, base64 as _b
            with urllib.request.urlopen(url) as r:
                return _b.b64encode(r.read()).decode(), None
        return None, "이미지 데이터가 비어있음"
    except Exception as e:
        return None, str(e)


def detect_emotion(client, molang_reply):
    """몰랑이 답변의 감정 (5종+보통)."""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": (
                f"다음 몰랑이의 말에서 드러나는 감정을 "
                f"{'/'.join(EMOTIONS)} 중 딱 하나 단어로만 답해.\n\n말: {molang_reply}")}],
            temperature=0, max_tokens=10)
        emo = resp.choices[0].message.content.strip()
        return emo if emo in EMOTIONS else "보통"
    except Exception:
        return "보통"


def read_photo_emotion(client, photo_b64, mime):
    """여친이 올린 사진의 감정도 읽음 (공감용)."""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": (
                    f"이 사진의 분위기/감정을 {'/'.join(EMOTIONS)} 중 하나로만 답해.")},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{photo_b64}"}}
            ]}],
            temperature=0, max_tokens=10)
        emo = resp.choices[0].message.content.strip()
        return emo if emo in EMOTIONS else "보통"
    except Exception:
        return "보통"
