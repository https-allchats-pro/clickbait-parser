from __future__ import annotations

from typing import Protocol, Sequence

from analysis.models import ClickbaitAnalysis, ClickbaitFeatures, RuleContribution
from analysis.rules import default_rules
from analysis.rules.base import ClickbaitRule
from domain.posts import CatalogPost

DEFAULT_CLICKBAIT_THRESHOLD = 0.5


class PostAnalyzer(Protocol):
    """Future-proof analyzer interface (rule-based / ML / hybrid)."""

    def analyze(self, post: CatalogPost) -> ClickbaitAnalysis: ...


class RuleBasedClickbaitAnalyzer:
    """Weighted rule-based clickbait scorer. No DB / VK / HTTP dependencies."""

    def __init__(
        self,
        *,
        rules: Sequence[ClickbaitRule] | None = None,
        threshold: float = DEFAULT_CLICKBAIT_THRESHOLD,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0.0 and 1.0")
        self._rules: list[ClickbaitRule] = list(rules) if rules is not None else list(default_rules())  # type: ignore[arg-type]
        self.threshold = float(threshold)

    def analyze(self, post: CatalogPost) -> ClickbaitAnalysis:
        if post.id is None:
            raise ValueError("CatalogPost.id is required for analysis")

        features = ClickbaitFeatures()
        reasons: list[str] = []
        contributions: list[RuleContribution] = []
        total = 0.0

        for rule in self._rules:
            result = rule.check(post)
            if not result.matched:
                continue
            weight = float(result.weight)
            total += weight
            if result.reason and result.reason not in reasons:
                reasons.append(result.reason)
            contributions.append(
                RuleContribution(reason=result.reason or "rule", weight=weight)
            )
            feature_name = result.feature or getattr(rule, "feature", None)
            if feature_name and hasattr(features, feature_name):
                setattr(features, feature_name, True)

        score = min(max(total, 0.0), 1.0)
        return ClickbaitAnalysis(
            post_id=int(post.id),
            score=score,
            is_clickbait=score >= self.threshold,
            reasons=reasons,
            features=features,
            rule_contributions=contributions,
        )


# Spec alias
ClickbaitAnalyzer = RuleBasedClickbaitAnalyzer
