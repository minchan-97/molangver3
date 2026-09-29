import logging

logger = logging.getLogger("FreudUnconscious")
logger.setLevel(logging.INFO)

class FreudUnconscious:
    """
    Freud-inspired unconscious drive module.
    - Drive rises with entropy (unconscious impulses)
    - Drive is suppressed by learning/ego signals
    - If drive exceeds threshold, system enters 'quarantine' (outputs suppressed, logs only)
    """

    def __init__(self, p0=0.0, alpha=0.25, beta=0.30, threshold=0.85, clamp_min=0.0, clamp_max=1.0):
        self.drive = float(p0)
        self.alpha = float(alpha)   # sensitivity to entropy
        self.beta = float(beta)     # suppression strength
        self.threshold = float(threshold)
        self.clamp_min = clamp_min
        self.clamp_max = clamp_max

    def step(self, entropy_proxy: float, learning_signal: float):
        """
        Update unconscious drive.
        Args:
            entropy_proxy (float): entropy proxy value [0,1]
            learning_signal (float): suppression/ego value [0,1]
        Returns:
            drive (float), quarantined (bool)
        """
        H = max(0.0, min(1.0, float(entropy_proxy)))
        L = max(0.0, min(1.0, float(learning_signal)))

        new_drive = self.drive + self.alpha * H - self.beta * L
        new_drive = max(self.clamp_min, min(self.clamp_max, new_drive))
        self.drive = new_drive

        quarantined = self.drive >= self.threshold

        logger.info({
            "drive": round(self.drive, 4),
            "entropy": round(H, 4),
            "learning": round(L, 4),
            "quarantined": quarantined
        })

        return self.drive, quarantined

    def reset(self, value=0.0):
        self.drive = float(max(self.clamp_min, min(self.clamp_max, value)))
