from __future__ import annotations

import re

from analysis.models import RuleResult
from domain.posts import CatalogPost

_ELLIPSIS_RE = re.compile(r"(\.\.\.|…)")


class EllipsisRule:
    reason = "ellipsis"
    weight = 0.05
    feature = "has_ellipsis"

    def check(self, post: CatalogPost) -> RuleResult:
        text = post.text or ""
        matched = bool(_ELLIPSIS_RE.search(text))
        return RuleResult(
            matched=matched,
            weight=self.weight if matched else 0.0,
            reason=self.reason,
            feature=self.feature,
        )
