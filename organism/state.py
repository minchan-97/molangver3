from __future__ import annotations
import time, math, hashlib
from dataclasses import dataclass, field, asdict

@dataclass
class OrganismState:
    version: int = 1
    born_at: float = field(default_factory=time.time)
    cycle: int = 0
    interests: dict = field(default_factory=dict)
    visited: dict = field(default_factory=dict)
    transition_counts: dict = field(default_factory=dict)
    observations: list = field(default_factory=list)
    candidates: list = field(default_factory=list)
    quarantine: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    unfinished_questions: list = field(default_factory=list)
    curiosity_history: list = field(default_factory=list)
    reflection_log: list = field(default_factory=list)
    embedding_vocab: dict = field(default_factory=dict)
    last_topic: str = ""
    last_hourly_at: float = 0.0
    last_nightly_at: float = 0.0

    def trim(self):
        self.observations = self.observations[-1200:]
        self.candidates = self.candidates[-600:]
        self.quarantine = self.quarantine[-400:]
        self.rejected = self.rejected[-300:]
        self.curiosity_history = self.curiosity_history[-1000:]
        self.reflection_log = self.reflection_log[-500:]

    def touch_interest(self, topic, reward=0.1):
        if not topic: return
        old = float(self.interests.get(topic, 0.0))
        self.interests[topic] = max(0.0, min(5.0, old * 0.985 + reward))
        self.visited[topic] = int(self.visited.get(topic, 0)) + 1
        if self.last_topic and self.last_topic != topic:
            key = f"{self.last_topic} -> {topic}"
            self.transition_counts[key] = int(self.transition_counts.get(key, 0)) + 1
        self.last_topic = topic

    def novelty(self, topic):
        return 1.0 / math.sqrt(1.0 + self.visited.get(topic, 0))

    def uid(self, text):
        return hashlib.sha1(text.encode('utf-8','ignore')).hexdigest()[:12]
