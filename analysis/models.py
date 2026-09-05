from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuleResult:
    matched: bool
    weight: float
    reason: str
    feature: str | None = None


@dataclass(frozen=True)
class RuleContribution:
    """One matched rule and its weight contribution to Rules score."""

    reason: str
    weight: float


@dataclass
class ClickbaitFeatures:
    has_external_link: bool = False
    has_continuation_phrase: bool = False
    has_curiosity_phrase: bool = False
    has_cta_phrase: bool = False
    has_ellipsis: bool = False
    has_excessive_exclamation: bool = False
    has_caps: bool = False
    has_emojis: bool = False
    short_text_with_link: bool = False
    link_near_cta: bool = False


@dataclass
class ClickbaitAnalysis:
    """Result of analyzing one CatalogPost (``post_id`` = local SQLite posts.id).

    ``score`` / ``is_clickbait`` / ``reasons`` / ``features`` are the Rules result
    (persisted). ``rule_contributions`` is in-memory detail for UI breakdown.
    """

    post_id: int
    score: float
    is_clickbait: bool
    reasons: list[str] = field(default_factory=list)
    features: ClickbaitFeatures = field(default_factory=ClickbaitFeatures)
    rule_contributions: list[RuleContribution] = field(default_factory=list)


@dataclass
class AnalysisBatchResult:
    analyzed: int = 0
    clickbait: int = 0
    normal: int = 0
    skipped: int = 0
