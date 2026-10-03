"""
tree_registry.py — 유형별 사고 트리 저장소.

남들 동적 트리(일회용)와 다른 점:
  남들: 질문마다 트리 생성 → 답 내면 버림
  민찬기: 유형별 트리를 보관 → 재사용 → 각각 진화

핵심:
  - 질문이 오면 '유형'을 판별
  - 그 유형의 트리가 있으면 재사용, 없으면 새로 만들어 등록
  - 사용 후 대화 반응으로 그 유형 트리가 진화 (전이 학습)
  - 유형별로 따로 자라므로, 도메인별 전문성이 축적됨

+ IdentityMemory(예전 정체성 모델) 결합:
  - 트리는 '어떻게 판단하나'(구조)
  - IdentityMemory는 '무엇을 아나/믿나'(내용)
  - 둘이 함께 하나의 정체성
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
import pickle
import time

from thought_structure import ThoughtStructure, JudgmentNode


class TreeRegistry:
    """
    유형(type) → 사고 트리 매핑.
    각 유형이 독립적으로 재사용·진화한다.
    """
    def __init__(self):
        self.trees: Dict[str, ThoughtStructure] = {}
        self.type_examples: Dict[str, List[str]] = {}   # 유형별 예시 질문 (판별용)
        self.usage_count: Dict[str, int] = {}
        # 유형 생성 감사 로그 (언제/왜/어떤 유형이 생겼나)
        self.creation_log: List[dict] = []

    def register_type(self, type_id: str, tree: ThoughtStructure,
                      examples: List[str] = None):
        """새 유형과 그 트리를 등록."""
        self.trees[type_id] = tree
        self.type_examples[type_id] = examples or []
        self.usage_count.setdefault(type_id, 0)

    def classify_type(self, question: str, embed_fn: Optional[Callable] = None,
                      classify_fn: Optional[Callable] = None) -> Optional[str]:
        """
        질문이 어느 유형인지 판별.
        classify_fn(question, type_ids, examples) -> type_id  (LLM 판별, 우선)
        embed_fn 있으면 예시와의 유사도로.
        없으면 단어 겹침.
        """
        if not self.trees:
            return None
        type_ids = list(self.trees.keys())

        # LLM 판별 (제일 정확). None을 주면 '새 유형' 신호로 존중.
        if classify_fn is not None:
            chosen = classify_fn(question, type_ids, self.type_examples)
            if chosen in self.trees:
                return chosen
            return None   # classify_fn이 매칭 실패/NEW → 새 유형 생성 유도

        # 임베딩 유사도
        if embed_fn is not None:
            import numpy as np
            qv = embed_fn(question)
            best, best_sim = None, -1
            for tid in type_ids:
                for ex in self.type_examples.get(tid, []):
                    ev = embed_fn(ex)
                    sim = float(np.dot(qv, ev) /
                                ((np.linalg.norm(qv)*np.linalg.norm(ev))+1e-12))
                    if sim > best_sim:
                        best_sim, best = sim, tid
            if best_sim > 0.3:
                return best

        # 단어 겹침 (폴백)
        import re
        qw = set(re.findall(r'[가-힣a-zA-Z0-9]{2,}', question))
        best, best_ov = None, 0
        for tid in type_ids:
            for ex in self.type_examples.get(tid, []):
                ew = set(re.findall(r'[가-힣a-zA-Z0-9]{2,}', ex))
                ov = len(qw & ew)
                if ov > best_ov:
                    best_ov, best = ov, tid
        return best if best_ov > 0 else type_ids[0]

    def get_or_create(self, type_id: str,
                      factory: Optional[Callable] = None) -> ThoughtStructure:
        """유형의 트리를 재사용, 없으면 생성."""
        if type_id not in self.trees:
            tree = factory() if factory else ThoughtStructure()
            self.register_type(type_id, tree)
        self.usage_count[type_id] = self.usage_count.get(type_id, 0) + 1
        return self.trees[type_id]

    @staticmethod
    def _step_words(steps) -> set:
        """
        단계 글자를 3글자 조각으로. 낱말 단위로 비교하면
        '감정 파악' 과 '감정 읽기' 를 다른 것으로 본다 — 실제로 그래서
        같은 일을 하는 유형이 넷이나 생겼다. 조각으로 보면 '감정' 이 겹친다.
        """
        import re
        text = " ".join(
            f"{s.get('name','')} {s.get('directive','')}" for s in (steps or []))
        text = re.sub(r'[^가-힣A-Za-z]', '', text)
        for stop in ("사용자", "대화", "정보", "단계", "내용", "답변", "한다", "하고"):
            text = text.replace(stop, "")
        return {text[i:i + 3] for i in range(len(text) - 2)}

    def _too_similar(self, design: dict, thr: float = 0.35):
        """설계가 기존 트리와 얼마나 겹치나. 많이 겹치면 그 유형 이름을 돌려준다."""
        new = self._step_words(design.get("steps"))
        if len(new) < 6:
            return None
        best, best_score = None, 0.0
        for tid, tree in self.trees.items():
            old = self._step_words(
                [{"name": n.prompt, "directive": n.directive}
                 for n in tree.nodes.values()])
            if not old:
                continue
            # 합집합이 아니라 '작은 쪽' 기준으로 본다.
            # 단계 수가 다르면 자카드는 낮게 나오지만, 새 설계의 내용이
            # 기존 것에 거의 다 들어 있으면 그건 같은 일을 하는 유형이다.
            j = len(new & old) / max(1, min(len(new), len(old)))
            if j > best_score:
                best, best_score = tid, j
        return best if best_score >= thr else None

    def merge_deep(self, a: str, b: str, log=print):
        """
        두 사고 방식을 하나로 합쳐 깊게 만든다.

        왜 합치나
          같은 질문에 늘 두 방식이 번갈아 쓰인다면, 그 둘은 사실 한 사고의
          앞뒤다. 따로 두면 각자 얕은 채로 남는다. 이어 붙이면
          'A로 살피고 → 그 결과로 B를 판단'하는 한 층 깊은 구조가 된다.

          A의 갈래 중 가장 많이 쓰인 길을 B의 시작으로 잇는다.
          나머지 갈래는 그대로 둔다 — 전부 이어 버리면 A가 사라진다.

        만들어진 유형은 새 이름을 갖고, 원본 둘은 남는다.
        (합친 게 나쁘면 원래 것으로 돌아갈 수 있어야 한다)
        """
        if a not in self.trees or b not in self.trees:
            return None
        ta, tb = self.trees[a], self.trees[b]
        new_id = f"{a}__{b}"
        if new_id in self.trees:
            return None
        if len(self.trees) >= self.MAX_TYPES + 6:
            return None

        import copy
        nt = ThoughtStructure(learning_rate=0.12, continuity=0.7)
        for nid, node in ta.nodes.items():
            nn = copy.deepcopy(node)
            nn.id = f"A_{nid}"
            nt.add_node(nn, is_root=(nid == ta.root_id))
        for frm, tos in ta.transitions.items():
            for to, p in (tos or {}).items():
                nt.add_branch(f"A_{frm}", f"A_{to}", p)

        # A 에서 가장 자주 간 갈래를 B 로 잇는다
        leaf = None
        best = -1.0
        for frm, tos in (ta.transitions or {}).items():
            for to, p in (tos or {}).items():
                if not (ta.transitions.get(to) or {}) and p > best:
                    leaf, best = to, p
        if leaf is None:
            return None

        for nid, node in tb.nodes.items():
            nn = copy.deepcopy(node)
            nn.id = f"B_{nid}"
            nt.add_node(nn)
        for frm, tos in tb.transitions.items():
            for to, p in (tos or {}).items():
                nt.add_branch(f"B_{frm}", f"B_{to}", p)

        nt.nodes[f"A_{leaf}"].is_terminal = False
        nt.add_branch(f"A_{leaf}", f"B_{tb.root_id}", 1.0)

        self.register_type(new_id, nt,
                           examples=(self.type_examples.get(a, [])[:1]
                                     + self.type_examples.get(b, [])[:1]))
        from datetime import datetime as _dt
        self.creation_log.append({
            "type_id": new_id, "reason": f"{a} 와 {b} 가 늘 함께 쓰여 합침",
            "merged_from": [a, b],
            "timestamp": _dt.now().isoformat(timespec="seconds"),
        })
        log(f"  사고 합치기: {a} + {b} → {new_id} (노드 {len(nt.nodes)})")
        return new_id

    MAX_TYPES = 26

    def wither(self, min_uses: int = 1, keep_recent: int = 2, max_types: int = 26):
        """
        오래 안 쓰인 자동생성 유형은 시들어 사라진다.
        늘기만 하고 줄지 않으면 그건 성장이 아니라 비대다.
        기본 20종과 최근에 만든 것은 건드리지 않는다.
        """
        # creation_log 에는 유형 생성 말고도 복구 기록(restored, paths_restored)
        # 같은 것이 섞인다. 그런 항목에는 type_id 가 없다.
        # 예전에는 c["type_id"] 로 바로 꺼내서 KeyError 로 회차가 통째로 멈췄다.
        auto = [c["type_id"] for c in self.creation_log
                if c.get("type_id") and not c.get("skipped")]
        protect = set(auto[-keep_recent:])
        gone = []
        # 유형이 많아질수록 경로가 흩어져 '깊어지기'가 영영 안 일어난다.
        # 상한을 넘으면 덜 쓰인 것부터 놓아준다.
        over = max(0, len(self.trees) - max_types)
        pool = auto[:-keep_recent] if len(auto) > keep_recent else []
        pool.sort(key=lambda k: (self.usage_count.get(k, 0),
                                 len(getattr(self.trees.get(k), "memory", []) or [])))
        for tid in pool:
            if over <= 0 and self.usage_count.get(tid, 0) > min_uses:
                continue
            if tid in protect or tid not in self.trees:
                continue
            mem = len(getattr(self.trees[tid], "memory", []) or [])
            if mem == 0 or over > 0:      # 근거가 쌓였으면 상한을 넘을 때만
                self.trees.pop(tid, None)
                self.usage_count.pop(tid, None)
                gone.append(tid)
                over -= 1
        return gone

    def create_from_design(self, design: dict, question: str,
                           reason: str = "새 유형 감지") -> Optional[str]:
        """
        LLM이 설계한 사고 단계(design)로 새 트리를 생성하고 감사 로그에 남긴다.
        design: {"type_id": str, "steps": [{"name","directive"}, ...]}
        반환: 생성된 type_id (실패 시 None)
        """
        from datetime import datetime
        if not design or "type_id" not in design or "steps" not in design:
            return None
        type_id = design["type_id"]
        if type_id in self.trees:
            return type_id   # 이미 있으면 그대로

        # 과생성 방지 1: 자동생성 트리 총량 상한
        auto_created = len(self.creation_log)
        if auto_created >= 12:
            return None   # 이미 충분히 다양 → 기존 유형으로 처리

        # 과생성 방지 1-b: 기존 유형과 '하는 일'이 겹치면 만들지 않는다.
        #
        # 이름만 보고 걸러서는 부족했다. 하룻밤에 analyze / dialogue /
        # discussion / emotion_analysis 가 각각 생겼는데 단계가 사실상 같았다.
        # 유형이 흩어지면 같은 경로가 반복될 일이 없어져서, 넓어지느라
        # 깊어지지 못한다(판단 단계가 한 번도 안 늘어난 원인).
        _dup = self._too_similar(design)
        if _dup:
            self.creation_log.append({
                "type_id": type_id, "at": datetime.now().isoformat(),
                "skipped": True, "merged_into": _dup,
                "reason": f"기존 '{_dup}' 와 하는 일이 겹쳐 만들지 않음"})
            return _dup      # 기존 유형을 쓰게 한다

        # 과생성 방지 2: 화제성 이름 거부 (사고방식이 아닌 주제면 안 만듦)
        topic_like = {"preference", "time_management", "conversation", "hobby",
                      "food", "sports", "weather", "greeting", "daily", "chat",
                      "fashion_advice", "small_talk", "emotion_talk"}
        if type_id.lower() in topic_like:
            return None

        steps = design.get("steps") or []
        branches = design.get("branches") or []
        if not steps:
            return None
        # 갈림길 없는 설계는 받지 않는다. 길이 하나뿐인 트리는
        # 전이 확률이 늘 1.0 이라 경험이 쌓여도 달라지지 않는다.
        if len(branches) < 2:
            return None

        # 정합성 검사는 **로컬**이 한다 (LLM 에게 맡기면 기준이 매번 달라지고
        # 어디에도 남지 않는다). 규칙 + 작은 신경망.
        verdict = {"ok": True}
        try:
            import logic_check
            verdict = logic_check.judge(design, self,
                                        getattr(self, "logic_scorer", None))
        except Exception:
            verdict = {"ok": True}
        if not verdict.get("ok"):
            self.creation_log.append({
                "type_id": type_id, "skipped": True,
                "reason": f"정합성 미달: {verdict.get('why')}",
                "stage": verdict.get("stage"),
                "timestamp": datetime.now().isoformat(timespec="seconds")})
            return None

        # 설계를 실제 트리로: 단계는 이어지고, 마지막에서 갈래로 퍼진다
        tree = ThoughtStructure(learning_rate=0.12, continuity=0.7)
        prev_id = None
        for i, step in enumerate(steps):
            nid = f"{type_id}_{i}"
            node = JudgmentNode(
                nid, step.get("name", f"단계{i+1}"),
                directive=step.get("directive", ""), is_terminal=False)
            tree.add_node(node, is_root=(i == 0))
            if prev_id is not None:
                tree.add_branch(prev_id, nid, 1.0)
            prev_id = nid

        for j, br in enumerate(branches[:3]):
            bid = f"{type_id}_b{j}"
            tree.add_node(JudgmentNode(
                bid, br.get("name", f"갈래{j+1}"),
                directive=br.get("directive", ""), is_terminal=True))
            tree.add_branch(prev_id, bid, 1.0 / len(branches[:3]))
        tree._normalize(prev_id)

        self.register_type(type_id, tree, examples=[question])

        # 감사 로그 (언제/왜/어떤 유형이/어떤 구조로 생겼나)
        self.creation_log.append({
            "type_id": type_id,
            "reason": reason,
            "trigger_question": question[:60],
            "steps": [s.get("name", "") for s in steps],
            "branches": [b.get("name", "") for b in branches[:3]],
            "features": verdict.get("features"),
            "score": verdict.get("score"),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
        return type_id

    def creation_history(self) -> List[dict]:
        """유형 생성 감사 로그 (무엇이 언제 왜 생겼나)."""
        return self.creation_log

    def stats(self) -> dict:
        """유형별 성숙도 (재사용·학습 횟수)."""
        return {
            tid: {
                "usage": self.usage_count.get(tid, 0),
                "learned": len(t.history),
                "memory": len(t.memory),
                "dominant": [t.nodes[n].prompt[:10] for n in t.dominant_path()],
            }
            for tid, t in self.trees.items()
        }

    # ── 저장/복원 (모든 유형 트리 + 성숙도 지속) ──
    def save(self, path: str):
        with open(path, "wb") as f:
            pickle.dump(self.to_blob(), f)
        return path

    def to_blob(self) -> dict:
        """registry를 dict로 (통합 pkl에 끼워넣기용)."""
        return {
            "trees": {tid: self._tree_blob(t) for tid, t in self.trees.items()},
            "type_examples": self.type_examples,
            "usage_count": self.usage_count,
            "creation_log": self.creation_log,
        }

    @classmethod
    def from_blob(cls, blob: dict) -> "TreeRegistry":
        """dict에서 registry 복원 (통합 pkl에서 꺼내기용)."""
        from thought_structure import PathRecord
        reg = cls()
        for tid, tb in blob.get("trees", {}).items():
            t = ThoughtStructure(learning_rate=tb["lr"], continuity=tb["continuity"])
            for k, v in tb["nodes"].items():
                t.nodes[k] = JudgmentNode(**v)
            t.transitions = tb["transitions"]
            t.root_id = tb["root_id"]
            t.history = [PathRecord(**r) for r in tb["history"]]
            t.memory = tb.get("memory", [])
            reg.trees[tid] = t
        reg.type_examples = blob.get("type_examples", {})
        reg.usage_count = blob.get("usage_count", {})
        reg.creation_log = blob.get("creation_log", [])
        return reg

    @staticmethod
    def _tree_blob(t: ThoughtStructure) -> dict:
        return {
            "nodes": {k: v.__dict__ for k, v in t.nodes.items()},
            "transitions": t.transitions, "root_id": t.root_id,
            "lr": t.lr, "continuity": t.continuity,
            "history": [r.__dict__ for r in t.history],
            "memory": t.memory,
        }

    @classmethod
    def load(cls, path: str) -> "TreeRegistry":
        from thought_structure import PathRecord
        with open(path, "rb") as f:
            blob = pickle.load(f)
        reg = cls()
        for tid, tb in blob["trees"].items():
            t = ThoughtStructure(learning_rate=tb["lr"], continuity=tb["continuity"])
            for k, v in tb["nodes"].items():
                t.nodes[k] = JudgmentNode(**v)
            t.transitions = tb["transitions"]
            t.root_id = tb["root_id"]
            t.history = [PathRecord(**r) for r in tb["history"]]
            t.memory = tb.get("memory", [])
            reg.trees[tid] = t
        reg.type_examples = blob.get("type_examples", {})
        reg.usage_count = blob.get("usage_count", {})
        return reg


def load_logic_db_types(registry, db_path: str = "logic_db.json"):
    """
    1년 전 logic_db.json의 논리 유형들을 registry의 초기 사고 트리로 로드.
    각 논리 유형(삼단논법, 귀납 등)을 판단 트리로 변환.
    오류 유형(순환논증 등)은 '피해야 할 것'으로 directive에 명시.
    """
    import json, os
    if not os.path.exists(db_path):
        return 0
    try:
        db = json.load(open(db_path, encoding="utf-8"))
    except Exception:
        return 0

    fallacy_types = {"informal fallacy", "inductive fallacy", "causal fallacy"}
    loaded = 0
    for entry in db:
        type_id = entry["name"].lower().replace(" ", "_").replace("≠", "not")
        if type_id in registry.trees:
            continue
        is_fallacy = entry.get("type", "") in fallacy_types

        # 논리 유형 → **갈림길이 있는** 사고 트리.
        #
        # 예전 로더는 무엇을 받든 '적용 판단 → 추론' 2단 일직선을 만들었다.
        # 그러면 전이 확률이 전부 1.0 이라 **대화로 조정될 여지가 없다.**
        # 삼단논법을 서른 번 써도 매번 같은 길이니 학습이 일어나지 않는다.
        # 이름만 논리학이고 안은 비어 있던 셈이다.
        #
        # 그래서 모든 유형을 이 모양으로 만든다:
        #   전제 살피기 → [판단이 갈리는 지점] → 성립 / 불성립 / 유보
        # 갈림길이 있어야 경험이 확률로 쌓인다.
        tree = ThoughtStructure(learning_rate=0.12, continuity=0.7)
        n = lambda i: f"{type_id}_{i}"

        tree.add_node(JudgmentNode(
            n(0), f"{entry['name']}에 필요한 것 살피기",
            directive=(f"이 질문에서 '{entry['name']}'({entry['description']}) "
                       f"를 쓰려면 무엇이 있어야 하는지 먼저 확인한다. "
                       f"형식: {entry['expression']}")), is_root=True)

        tree.add_node(JudgmentNode(
            n(1), "갖춰졌는지 가르기",
            directive=("필요한 것이 실제로 갖춰졌는지 판단한다. "
                       "갖춰졌으면 적용, 어긋나면 배제, "
                       "모르겠으면 유보로 간다. 억지로 맞추지 않는다.")))
        tree.add_branch(n(0), n(1), 1.0)

        if is_fallacy:
            tree.add_node(JudgmentNode(
                n(2), "오류에 빠졌음 — 물러서기",
                directive=(f"'{entry['name']}'은 논리적 오류다"
                           f"({entry['expression']}). 지금 그 모양이라면 "
                           f"결론을 거두고 근거를 다시 찾는다."),
                is_terminal=True))
            tree.add_node(JudgmentNode(
                n(3), "오류 아님 — 그대로 진행",
                directive="이 오류에는 해당하지 않는다. 하던 판단을 잇는다.",
                is_terminal=True))
            tree.add_node(JudgmentNode(
                n(4), "헷갈림 — 근거 먼저",
                directive="오류인지 아닌지 지금은 가릴 수 없다. "
                          "단정하지 말고 근거를 더 본다.",
                is_terminal=True))
        else:
            tree.add_node(JudgmentNode(
                n(2), "성립 — 결론 내기",
                directive=f"{entry['expression']} 형식으로 추론해 결론을 낸다.",
                is_terminal=True))
            tree.add_node(JudgmentNode(
                n(3), "불성립 — 다른 길",
                directive=(f"'{entry['name']}'로는 풀리지 않는다. "
                           f"무엇이 모자란지 말하고 다른 방식을 찾는다."),
                is_terminal=True))
            tree.add_node(JudgmentNode(
                n(4), "유보 — 모른다고 말하기",
                directive="전제가 확실하지 않다. 모른다고 말하고 "
                          "무엇이 있어야 판단할 수 있는지 밝힌다.",
                is_terminal=True))

        # 세 갈래. 처음엔 고르게 두고, 쓰이면서 확률이 갈린다.
        for k, p in ((2, 0.45), (3, 0.30), (4, 0.25)):
            tree.add_branch(n(1), n(k), p)
        tree._normalize(n(1))

        registry.register_type(type_id, tree, examples=[entry["description"]])
        loaded += 1
    return loaded
