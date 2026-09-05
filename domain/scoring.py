from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScoringMode(str, Enum):
    """How Final score is derived from Rules / ML."""

    RULES = "rules"
    RULES_ML = "rules_ml"
    ML = "ml"


@dataclass(frozen=True)
class ScoringConfig:
    """Configurable blend weights and clickbait threshold (all in 0..1)."""

    rules_weight: float = 0.3
    ml_weight: float = 0.7
    threshold: float = 0.70

    def __post_init__(self) -> None:
        for name, value in (
            ("rules_weight", self.rules_weight),
            ("ml_weight", self.ml_weight),
            ("threshold", self.threshold),
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        total = float(self.rules_weight) + float(self.ml_weight)
        if total <= 0:
            raise ValueError("rules_weight + ml_weight must be > 0")


DEFAULT_SCORING_CONFIG = ScoringConfig()


@dataclass(frozen=True)
class PostScoring:
    """Resolved Rules / ML / Final scores for one post under a scoring mode."""

    mode: ScoringMode
    rules_score: float
    ml_score: float | None
    final_score: float
    is_clickbait: bool
    rules_weight: float
    ml_weight: float
    threshold: float
    used_ml: bool
    ml_available: bool

    @property
    def effective_mode(self) -> ScoringMode:
        """Mode actually applied (falls back to RULES when ML is missing)."""
        if self.mode in (ScoringMode.ML, ScoringMode.RULES_ML) and not self.ml_available:
            return ScoringMode.RULES
        return self.mode


def compute_post_scoring(
    *,
    rules_score: float,
    ml_score: float | None,
    mode: ScoringMode,
    config: ScoringConfig = DEFAULT_SCORING_CONFIG,
) -> PostScoring:
    """Combine rules/ML into Final score. Values stay in 0..1."""
    rules = min(max(float(rules_score), 0.0), 1.0)
    ml_available = ml_score is not None
    ml = None if not ml_available else min(max(float(ml_score), 0.0), 1.0)

    rw = float(config.rules_weight)
    mw = float(config.ml_weight)
    # Normalize blend weights so they sum to 1.
    blend = rw + mw
    if blend > 0:
        rw, mw = rw / blend, mw / blend

    if mode == ScoringMode.RULES or (mode != ScoringMode.RULES and not ml_available):
        final = rules
        used_ml = False
    elif mode == ScoringMode.ML:
        assert ml is not None
        final = ml
        used_ml = True
    else:  # RULES_ML
        assert ml is not None
        final = rules * rw + ml * mw
        used_ml = True

    final = min(max(float(final), 0.0), 1.0)
    return PostScoring(
        mode=mode,
        rules_score=rules,
        ml_score=ml,
        final_score=final,
        is_clickbait=final >= float(config.threshold),
        rules_weight=rw,
        ml_weight=mw,
        threshold=float(config.threshold),
        used_ml=used_ml,
        ml_available=ml_available,
    )


def default_mode_for_model(*, model_ready: bool) -> ScoringMode:
    """Default score mode is always Rules; ML modes are opt-in."""
    _ = model_ready
    return ScoringMode.RULES
