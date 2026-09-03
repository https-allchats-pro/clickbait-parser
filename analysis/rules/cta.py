from __future__ import annotations

from analysis.models import RuleResult
from analysis.textutil import any_phrase, normalize_text
from domain.posts import CatalogPost

# Weak CTA signals — alone they should not dominate the score.
CTA_PHRASES = [
    "читайте",
    "смотрите",
    "узнайте",
    "переходите",
    "подробнее",
    "жмите",
    "ссылка",
    "читать",
    "смотрите здесь",
    "читайте здесь",
    "перейти",
    "открыть",
]


class CtaRule:
    reason = "cta"
    weight = 0.10
    feature = "has_cta_phrase"

    def check(self, post: CatalogPost) -> RuleResult:
        normalized = normalize_text(post.text)
        matched = any_phrase(normalized, CTA_PHRASES)
        return RuleResult(
            matched=matched,
            weight=self.weight if matched else 0.0,
            reason=self.reason,
            feature=self.feature,
        )
