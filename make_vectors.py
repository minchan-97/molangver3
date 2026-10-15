"""
make_vectors.py — 큰 벡터 파일을 **몰랑이 몫만** 남겨 줄인다.

gensim 이 없어도 된다
  Python 3.14 에서는 gensim 이 아직 안 깔린다. 그래서 바이너리(.bin)
  대신 **텍스트 형식**(.vec / .txt)을 읽는다. numpy 만 있으면 된다.

  텍스트 형식은 이렇게 생겼다.
      2000000 300          ← 낱말 수, 차원
      바다 0.123 -0.456 ...
      파도 0.234 0.567 ...

  파일이 커도 (수 GB) **한 줄씩 읽으며 필요한 것만 담으므로**
  메모리를 많이 쓰지 않는다.

쓰는 법 (윈도우)
    pip install numpy supabase

    set SUPABASE_URL=https://....supabase.co
    set SUPABASE_SERVICE_KEY=새로_발급받은_키
    python tools\\make_vectors.py cc.ko.300.vec --out vectors.npz

  접속이 안 되면 낱말 목록 파일로도 된다.
    python tools\\make_vectors.py cc.ko.300.vec --words words.txt

나온 vectors.npz 를 저장소 뿌리에 두면 끝이다.
"""
from __future__ import annotations
import argparse
import gzip
import io
import os
import re
import sys

TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")


def words_from_supabase() -> set:
    """몰랑이가 실제로 쓰는 낱말 — 관심·지도·사실·관측에서."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not (url and key):
        return set()
    try:
        from supabase import create_client
    except ImportError:
        print("supabase 가 없습니다:  pip install supabase")
        return set()
    sb = create_client(url, key)
    out = set()

    def add(t):
        for w in TOKEN.findall(t or ""):
            out.add(w)

    try:
        r = (sb.table("organism_state").select("interests")
             .eq("id", 1).limit(1).execute().data) or []
        out |= set((r[0].get("interests") or {}) if r else {})
    except Exception:
        pass
    try:
        r = (sb.table("molang_map").select("graph")
             .eq("id", 1).limit(1).execute().data) or []
        out |= set(((r[0].get("graph") or {}).get("nodes") or {}) if r else {})
    except Exception:
        pass
    try:
        for row in (sb.table("molang_facts").select("text")
                    .limit(2000).execute().data) or []:
            add(row.get("text"))
    except Exception:
        pass
    try:
        for row in (sb.table("organism_observations")
                    .select("topic,title").limit(1500).execute().data) or []:
            add(row.get("topic"))
            add(row.get("title"))
    except Exception:
        pass
    return {w for w in out if len(w) >= 2}


def words_from_file(path: str) -> set:
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            for w in TOKEN.findall(line):
                out.add(w)
    return {w for w in out if len(w) >= 2}


def _open(path: str):
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8",
                                errors="ignore")
    return open(path, encoding="utf-8", errors="ignore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model", help="cc.ko.300.vec 또는 .vec.gz / .txt")
    ap.add_argument("--out", default="vectors.npz")
    ap.add_argument("--words", help="낱말 목록 파일 (없으면 Supabase에서)")
    ap.add_argument("--extra", type=int, default=3000,
                    help="자주 쓰이는 낱말을 이만큼 더 담는다")
    a = ap.parse_args()

    import numpy as np

    want = words_from_file(a.words) if a.words else words_from_supabase()
    if not want:
        print("낱말을 못 모았습니다.\n"
              "  · 윈도우라면 set SUPABASE_URL=... (따옴표 없이)\n"
              "  · 또는 --words 로 낱말 목록 파일을 주세요")
        sys.exit(1)
    print(f"몰랑이가 쓰는 낱말 {len(want)}개")

    print(f"읽는 중… ({a.model})  — 파일이 크면 몇 분 걸립니다")
    keep, vecs, dim = [], [], None
    extra_left = a.extra
    seen = set()

    with _open(a.model) as f:
        first = f.readline().split()
        if len(first) == 2 and first[0].isdigit():
            dim = int(first[1])          # 머리글
        else:
            dim = len(first) - 1          # 머리글이 없는 판
            w = first[0]
            if w in want:
                keep.append(w)
                vecs.append([float(x) for x in first[1:]])
                seen.add(w)

        for n, line in enumerate(f, 1):
            if n % 200000 == 0:
                print(f"   {n:,}줄… (담은 것 {len(keep)})")
            parts = line.rstrip().split(" ")
            if len(parts) != dim + 1:
                continue
            w = parts[0]
            if w in seen or len(w) < 2 or not TOKEN.fullmatch(w):
                continue
            if w in want:
                pass
            elif extra_left > 0:
                extra_left -= 1          # 앞쪽이 자주 쓰이는 낱말이다
            else:
                continue
            keep.append(w)
            vecs.append([float(x) for x in parts[1:]])
            seen.add(w)

    if not keep:
        print("담긴 낱말이 없습니다. 파일 형식을 확인하세요.")
        sys.exit(1)

    V = np.array(vecs, dtype="float32")
    norm = np.linalg.norm(V, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    V = V / norm

    np.savez_compressed(a.out, words=np.array(keep, dtype=object),
                        vecs=V, dim=V.shape[1])
    mb = os.path.getsize(a.out) / 1e6
    miss = len(want - seen)
    print(f"\n담은 낱말 {len(keep)}개 · {V.shape[1]}차원 · {mb:.1f}MB")
    print(f"파일에 없어서 뺀 낱말 {miss}개 (쓰는 쪽에서 해시로 메움)")
    print(f"→ {a.out} 를 저장소 뿌리에 두세요.")


if __name__ == "__main__":
    main()
