from __future__ import annotations

import re

from analysis.models import RuleResult
from domain.posts import CatalogPost

_EXCESS_RE = re.compile(r"!{2,}|\?{2,}|!\?|\?!")


class ExcessivePunctuationRule:
    reason = "excessive_punctuation"
    weight = 0.05
    feature = "has_excessive_exclamation"

    def check(self, post: CatalogPost) -> RuleResult:
        text = post.text or ""
        bangs = text.count("!")
        matched = bangs >= 3 or bool(_EXCESS_RE.search(text))
        return RuleResult(
            matched=matched,
            weight=self.weight if matched else 0.0,
            reason=self.reason,
            feature=self.feature,
        )
