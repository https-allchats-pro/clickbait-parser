from __future__ import annotations

import re

from analysis.models import RuleResult
from domain.posts import CatalogPost

# Broad emoji / pictograph ranges (weak feature).
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)


class EmojiRule:
    reason = "emoji"
    weight = 0.02
    feature = "has_emojis"

    def check(self, post: CatalogPost) -> RuleResult:
        matched = bool(_EMOJI_RE.search(post.text or ""))
        return RuleResult(
            matched=matched,
            weight=self.weight if matched else 0.0,
            reason=self.reason,
            feature=self.feature,
        )
