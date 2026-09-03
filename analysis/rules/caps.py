from __future__ import annotations

import re

from analysis.models import RuleResult
from domain.posts import CatalogPost

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]{2,}")
_ALLOWLIST = {
    "NASA",
    "VK",
    "США",
    "СССР",
    "РФ",
    "МВД",
    "ФСБ",
    "ООН",
    "ЕС",
    "НАТО",
    "CPU",
    "GPU",
    "AI",
    "IT",
    "USA",
    "USSR",
}


class CapsRule:
    reason = "caps"
    weight = 0.05
    feature = "has_caps"

    def check(self, post: CatalogPost) -> RuleResult:
        words = _WORD_RE.findall(post.text or "")
        if len(words) < 3:
            return RuleResult(matched=False, weight=0.0, reason=self.reason, feature=self.feature)

        upper_words = [
            w
            for w in words
            if w.isupper() and w not in _ALLOWLIST and len(w) >= 3
        ]
        ratio = len(upper_words) / len(words)
        matched = len(upper_words) >= 3 or ratio >= 0.45
        return RuleResult(
            matched=matched,
            weight=self.weight if matched else 0.0,
            reason=self.reason,
            feature=self.feature,
        )
