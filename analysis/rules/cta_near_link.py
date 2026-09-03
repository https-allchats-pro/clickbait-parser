from __future__ import annotations

import re

from analysis.models import RuleResult
from analysis.rules.cta import CTA_PHRASES
from analysis.textutil import normalize_text
from domain.posts import CatalogPost

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class CtaNearLinkRule:
    reason = "cta_near_link"
    weight = 0.15
    feature = "link_near_cta"

    def check(self, post: CatalogPost) -> RuleResult:
        if not post.links:
            return RuleResult(matched=False, weight=0.0, reason=self.reason, feature=self.feature)

        text = post.text or ""
        # Prefer explicit URL in body; otherwise treat link as after the whole text.
        matches = list(_URL_RE.finditer(text))
        windows: list[str] = []
        if matches:
            for match in matches:
                start = max(0, match.start() - 80)
                windows.append(text[start:match.start()])
        else:
            windows.append(text[-120:] if len(text) > 120 else text)

        for window in windows:
            normalized = normalize_text(window)
            for phrase in CTA_PHRASES:
                needle = normalize_text(phrase)
                if needle and f" {needle} " in f" {normalized} ":
                    return RuleResult(
                        matched=True,
                        weight=self.weight,
                        reason=self.reason,
                        feature=self.feature,
                    )
        return RuleResult(matched=False, weight=0.0, reason=self.reason, feature=self.feature)
