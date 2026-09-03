from __future__ import annotations

from analysis.models import RuleResult
from domain.posts import CatalogPost


class ExternalLinkRule:
    reason = "external_link"
    weight = 0.10
    feature = "has_external_link"

    def check(self, post: CatalogPost) -> RuleResult:
        matched = bool(post.links)
        return RuleResult(
            matched=matched,
            weight=self.weight if matched else 0.0,
            reason=self.reason,
            feature=self.feature,
        )
