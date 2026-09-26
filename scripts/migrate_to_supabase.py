"""
02_migrate.py — 몰랑이 pkl → Supabase 이관 + 오염 분류.

원칙: 자동으로 지우지 않는다. 의심스러운 건 검역소로 보내고
      최종 승격은 사람이 한다 (cogito anchor).

사용법:
    python 02_migrate.py 몰랑이22.pkl --out ./migration
    # 검토 후
    python 02_migrate.py 몰랑이22.pkl --out ./migration --push
"""
import argparse, json, os, pickle, re, sys, tempfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# ---------------- 정규화/분류: molang_norm 공용 모듈 ----------------
# 운영(molang_store.py)과 반드시 같은 규칙을 써야 norm_key가 일치한다.
from molang_norm import (normalize, jaccard, classify_kind,
                         is_assistant_echo, TTL)

# ---------------- pkl 로드 ----------------

def load_identity(pkl_path: str, code_dir: str):
    sys.path.insert(0, code_dir)
    from unified_identity import UnifiedIdentity  # noqa
    raw = open(pkl_path, 'rb').read()
    bundle = pickle.loads(raw)
    if isinstance(bundle, dict) and 'arcogit' in bundle:
        blob = bundle['arcogit']
        faces = bundle.get('molang_faces', {})
        appearance = bundle.get('molang_appearance')
    else:
        blob, faces, appearance = raw, {}, None
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pkl')
    tmp.write(blob); tmp.close()
    u = UnifiedIdentity.load(tmp.name)
    os.unlink(tmp.name)
    return u, faces, appearance

# ---------------- 분류 파이프라인 ----------------

def triage(learned_facts):
    keep, quarantine = [], []
    seen = []   # (norm_key, index in keep)

    for f in learned_facts:
        text = f['text'] if isinstance(f, dict) else str(f)
        strength = f.get('strength', 0.6) if isinstance(f, dict) else 0.6
        cnt = f.get('seen', 1) if isinstance(f, dict) else 1
        text = text.strip()
        if not text:
            continue

        if is_assistant_echo(text):
            quarantine.append({
                'text': text, 'reason': 'assistant_echo',
                'evidence': {'strength': strength},
            })
            continue

        # 근접 중복 병합
        dup_idx = None
        for i, k in enumerate(keep):
            if jaccard(text, k['text']) >= 0.75:
                dup_idx = i
                break
        if dup_idx is not None:
            k = keep[dup_idx]
            k['seen'] += cnt
            k['strength'] = min(1.0, max(k['strength'], strength) + 0.1)
            k.setdefault('merged', []).append(text)
            quarantine.append({
                'text': text, 'reason': 'near_duplicate',
                'evidence': {'merged_into': k['text']},
            })
            continue

        kind = classify_kind(text)
        entry = {
            'text': text,
            'norm_key': normalize(text),
            'kind': kind,
            'strength': strength,
            'seen': cnt,
            'source': 'user',
            # 이관 시점엔 아무것도 human이 아니다. 승인은 사람이 따로.
            'trust': 'derived',
            'approved_by_human': False,
            'expires_at': None,
        }
        if kind == 'state':
            # 이미 지난 상태 — 만료시켜서 프롬프트에서 빠지게 한다
            entry['expires_at'] = datetime.now(KST).isoformat()
            entry['stale'] = True
            quarantine.append({
                'text': text, 'reason': 'stale_state',
                'evidence': {'note': '일시 상태가 확정 사실로 승격돼 있었음'},
            })
        keep.append(entry)

    return keep, quarantine

# ---------------- 메인 ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pkl')
    ap.add_argument('--code', default='.', help='molang_v2 코드 디렉터리')
    ap.add_argument('--out', default='./migration')
    ap.add_argument('--push', action='store_true', help='Supabase에 실제 반영')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    u, faces, appearance = load_identity(args.pkl, args.code)
    ident = u.identity

    keep, quarantine = triage(ident.learned_facts)

    report = {
        'source_pkl': os.path.basename(args.pkl),
        'before': {
            'facts': len(ident.learned_facts),
            'episodes': len(ident.episodic),
            'values': len(ident.values),
            'rules': len(ident.judgment_rules),
        },
        'after': {
            'facts_kept': len(keep),
            'quarantined': len(quarantine),
            'by_kind': {k: sum(1 for e in keep if e['kind'] == k)
                        for k in ('fact', 'state', 'preference')},
            'stale_states': sum(1 for e in keep if e.get('stale')),
        },
    }

    with open(f'{args.out}/facts_keep.jsonl', 'w', encoding='utf-8') as fh:
        for e in keep:
            fh.write(json.dumps(e, ensure_ascii=False) + '\n')
    with open(f'{args.out}/quarantine.jsonl', 'w', encoding='utf-8') as fh:
        for e in quarantine:
            fh.write(json.dumps(e, ensure_ascii=False) + '\n')
    with open(f'{args.out}/episodes.jsonl', 'w', encoding='utf-8') as fh:
        for e in ident.episodic:
            fh.write(json.dumps({'summary': e}, ensure_ascii=False) + '\n')
    with open(f'{args.out}/identity.json', 'w', encoding='utf-8') as fh:
        json.dump({'persona': ident.persona,
                   'values': ident.values,
                   'rules': ident.judgment_rules}, fh, ensure_ascii=False, indent=2)
    with open(f'{args.out}/report.json', 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f'\n검토 파일: {args.out}/facts_keep.jsonl, quarantine.jsonl')

    if not args.push:
        print('\n--push 없이 실행됨. 실제 반영 안 함.')
        return

    from supabase import create_client
    sb = create_client(os.environ['SUPABASE_URL'],
                       os.environ['SUPABASE_SERVICE_KEY'])

    sb.table('molang_identity').upsert({
        'id': 1,
        'persona': ident.persona,
        'values': ident.values,
        'rules': ident.judgment_rules,
    }).execute()

    rows = [{k: v for k, v in e.items() if k not in ('merged', 'stale')}
            for e in keep]
    for i in range(0, len(rows), 100):
        sb.table('molang_facts').upsert(
            rows[i:i+100], on_conflict='norm_key').execute()

    for i in range(0, len(quarantine), 100):
        sb.table('molang_quarantine').insert(quarantine[i:i+100]).execute()

    blob = pickle.dumps(u.registry)
    sb.table('molang_registry').upsert({
        'id': 1, 'blob': blob.hex(), 'version': 1}).execute()

    print('반영 완료.')


if __name__ == '__main__':
    main()
