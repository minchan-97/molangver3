# Molang Digital Organism v1

기존 `molang v13`을 보존하고, 임용 v14.3의 **worker / self-maintenance / gap-search 철학**을 디지털 유기체용으로 재구성한 실험판입니다.

## 핵심
- 기존 몰랑이 PKL은 **읽기 전용 정체성 코어**로 취급합니다. 탐색 결과가 곧바로 `learned_facts`에 들어가지 않습니다.
- 매시간: local curiosity → Brave 탐색 → NM-style gate → candidate/quarantine/reject → SOM 재구성.
- 야간: OpenAI가 탐색 질의를 확장 → Brave deep exploration → gate → SOM 확장 → reflection snapshot.
- `봤다(seen) != 믿는다(believed)`. 호기심과 오염 방지를 분리했습니다.
- NM gate는 새 영역을 막는 방화벽이 아니라 **장기기억 편입 전 면역계**입니다.

## 기존 PKL 이식
```bash
python -m organism.migrate "몰랑이22.pkl"
```
원본 파일은 수정하지 않고 `data/molang.pkl`로 복사합니다.

## 실행
```bash
export BRAVE_API_KEY=...
export OPENAI_API_KEY=...
python -m organism.worker --mode hourly
python -m organism.worker --mode nightly
```

## Streamlit 통합
`app.py` 원하는 위치에서:
```python
from organism.streamlit_panel import render_organism_panel
render_organism_panel()
```

## Supabase 통합 포인트
현재 worker state는 `data/organism_state.pkl`, SOM은 `data/curiosity_som.pkl`, 정체성은 `data/molang.pkl`입니다. 기존 Supabase persistence 계층에서 이 3개를 latest/history 대상으로 올리면 됩니다. **동시 실행 시 optimistic lock 또는 run-id 기반 CAS를 권장합니다.**

## 중요한 안전장치
1. `candidate`도 자동으로 몰랑이의 신념이 되지 않습니다.
2. quarantine은 별도 유지합니다.
3. 관심도에는 decay가 있어 초기 우연이 영구 고착되지 않습니다.
4. 새 topic transition은 확률 0으로 만들지 않아 NM이 curiosity를 질식시키지 않습니다.
5. GitHub Actions의 ephemeral filesystem만으로는 상태가 지속되지 않습니다. Supabase에서 실행 전 pull / 실행 후 push를 연결해야 합니다.

## 다음 연구 단계
- candidate → belief 승격을 2개 이상 독립 출처 + contradiction check로 제한
- 동일 초기 PKL 두 인스턴스를 다른 seed로 30일 실행해 SOM topology / 관심분포 divergence 측정
- novelty-only vs novelty×information-gain 비교
- noisy-TV 방지를 위한 learnability/progress reward 추가
