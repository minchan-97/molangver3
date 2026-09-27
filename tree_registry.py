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

    def wither(self, min_uses: int = 1, keep_recent: int = 2, max_types: int = 26):
        """
        오래 안 쓰인 자동생성 유형은 시들어 사라진다.
        늘기만 하고 줄지 않으면 그건 성장이 아니라 비대다.
        기본 20종과 최근에 만든 것은 건드리지 않는다.
        """
        auto = [c["type_id"] for c in self.creation_log if not c.get("skipped")]
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

        steps = design["steps"]
        if not steps:
            return None

        # 설계를 실제 트리로 (순차 단계 → 노드 체인)
        tree = ThoughtStructure(learning_rate=0.12, continuity=0.7)
        prev_id = None
        for i, step in enumerate(steps):
            nid = f"{type_id}_{i}"
            is_last = (i == len(steps) - 1)
            node = JudgmentNode(
                nid, step.get("name", f"단계{i+1}"),
                directive=step.get("directive", ""),
                is_terminal=is_last)
            tree.add_node(node, is_root=(i == 0))
            if prev_id is not None:
                tree.add_branch(prev_id, nid, 1.0)
            prev_id = nid

        self.register_type(type_id, tree, examples=[question])

        # 감사 로그 (언제/왜/어떤 유형이/어떤 구조로 생겼나)
        self.creation_log.append({
            "type_id": type_id,
            "reason": reason,
            "trigger_question": question[:60],
            "steps": [s.get("name", "") for s in steps],
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

        tree = ThoughtStructure(learning_rate=0.12, continuity=0.7)
        # 논리 유형 → 3단 사고 트리
        tree.add_node(JudgmentNode(
            f"{type_id}_0", f"{entry['name']} 적용 판단",
            directive=f"이 질문에 '{entry['name']}'({entry['description']}) "
                      f"논리를 적용할지 판단한다."), is_root=True)
        if is_fallacy:
            # 오류 유형은 '감지·회피' 트리
            tree.add_node(JudgmentNode(
                f"{type_id}_1", "오류 회피",
                directive=f"'{entry['name']}'은 논리적 오류다({entry['expression']}). "
                          f"이 오류에 빠지지 않았는지 점검하고 피한다.",
                is_terminal=True))
        else:
            tree.add_node(JudgmentNode(
                f"{type_id}_1", f"{entry['name']} 추론",
                directive=f"{entry['expression']} 형식으로 추론한다.",
                is_terminal=True))
        tree.add_branch(f"{type_id}_0", f"{type_id}_1", 1.0)

        registry.register_type(type_id, tree, examples=[entry["description"]])
        loaded += 1
    return loaded

