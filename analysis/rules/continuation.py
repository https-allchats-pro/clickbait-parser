from __future__ import annotations

from analysis.models import RuleResult
from analysis.textutil import any_phrase, normalize_text
from domain.posts import CatalogPost

CONTINUATION_PHRASES = [
    "продолжение по ссылке",
    "читать продолжение",
    "продолжение читайте",
    "продолжение в статье",
    "полная история по ссылке",
    "полную историю читайте",
    "подробнее по ссылке",
    "вся история здесь",
    "что было дальше",
    "что произошло дальше",
    "а дальше было самое интересное",
    "продолжение здесь",
    "смотрите продолжение",
    "читайте далее",
    "читать далее",
    "продолжение по ссылке ниже",
    "читайте продолжение",
    "смотрите дальше",
]


class ContinuationBaitRule:
    reason = "continuation_bait"
    weight = 0.35
    feature = "has_continuation_phrase"

    def check(self, post: CatalogPost) -> RuleResult:
        normalized = normalize_text(post.text)
        matched = any_phrase(normalized, CONTINUATION_PHRASES)
        return RuleResult(
            matched=matched,
            weight=self.weight if matched else 0.0,
            reason=self.reason,
            feature=self.feature,
        )
