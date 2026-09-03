from __future__ import annotations

from analysis.models import RuleResult
from analysis.textutil import strip_urls_for_length
from domain.posts import CatalogPost

SHORT_TEXT_CHARS = 120


class ShortTextWithLinkRule:
    reason = "short_text_with_link"
    weight = 0.15
    feature = "short_text_with_link"

    def check(self, post: CatalogPost) -> RuleResult:
        if not post.links:
            return RuleResult(matched=False, weight=0.0, reason=self.reason, feature=self.feature)
        body = strip_urls_for_length(post.text)
        matched = 0 < len(body) <= SHORT_TEXT_CHARS
        return RuleResult(
            matched=matched,
            weight=self.weight if matched else 0.0,
            reason=self.reason,
            feature=self.feature,
        )
