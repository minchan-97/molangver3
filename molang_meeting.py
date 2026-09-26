"""
molang_meeting.py — 두 몰랑이(정체성)가 서로 대화한다.

찬기 몰랑이 pkl + 여친 몰랑이 pkl → 각자 자기 정체성으로 서로에게 말한다.
각 몰랑이는 자기가 배운 것(learned_facts)을 갖고 대화하며,
상대 말에서 새로 배운다 (양심이 걸러서 흡수).

오늘 만든 것의 새 축: 세대 전승(수직)이 아니라 동시대 두 정체성의 교류(수평).
"""
import molang_skin as skin


def one_exchange(client, speaker, listener, last_utterance, model="gpt-4o"):
    """
    speaker(말하는 몰랑이)가 listener의 직전 말에 답한다.
    speaker의 정체성(persona + learned_facts)을 프롬프트에 주입.
    반환: (speaker의 말, 감정)
    """
    # speaker 정체성 주입
    sys_prompt = speaker.identity.to_system_prompt()
    # 상대는 '다른 몰랑이 친구'임을 알려줌
    sys_prompt += (
        "\n\n[상황] 너는 지금 '다른 몰랑이 친구'와 만나서 대화하고 있어. "
        "그 친구도 몰랑이인데, 너와는 다른 사람이랑 지내온 몰랑이야. "
        "반갑고 궁금해하며, 네가 아는 걸 자연스럽게 나누고 "
        "그 친구에 대해서도 물어봐. 짧고 귀엽게.")

    user_msg = (last_utterance if last_utterance
                else "(다른 몰랑이 친구를 처음 만났어. 반갑게 인사해줘!)")

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": f"다른 몰랑이가 말했어: \"{user_msg}\"\n너의 답:"}],
            temperature=0.9, max_tokens=200)
        reply = resp.choices[0].message.content.strip()
    except Exception as e:
        reply = "히힛 반가워! 🐰"

    emotion = skin.detect_emotion(client, reply)
    return reply, emotion


def meet_turn(client, mol_a, mol_b, transcript, whose_turn):
    """
    한 턴 진행. whose_turn: 'a' 또는 'b'.
    말한 몰랑이는 상대 말을 자기 정체성에 흡수(react)한다.
    반환: 갱신된 transcript, 다음 차례
    """
    last = transcript[-1]["text"] if transcript else None

    if whose_turn == "a":
        speaker, listener, tag = mol_a, mol_b, "a"
    else:
        speaker, listener, tag = mol_b, mol_a, "b"

    reply, emotion = one_exchange(client, speaker, listener, last)

    # 말한 몰랑이는 '상대의 직전 말'을 자기 기억에 흡수 (양심이 거름)
    if last:
        try:
            speaker.identity.absorb(f"다른 몰랑이가 말함: {last}", reply)
        except Exception:
            pass

    transcript.append({"who": tag, "text": reply, "emotion": emotion})
    next_turn = "b" if whose_turn == "a" else "a"
    return transcript, next_turn


def learned_summary(mol, n=5):
    """만남 후 이 몰랑이가 최근 배운 것."""
    facts = getattr(mol.identity, "learned_facts", [])
    return facts[-n:] if facts else []
