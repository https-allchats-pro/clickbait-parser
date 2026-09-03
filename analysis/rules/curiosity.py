from __future__ import annotations

from analysis.models import RuleResult
from analysis.textutil import any_phrase, normalize_text
from domain.posts import CatalogPost

CURIOSITY_PHRASES = [
    "вы не поверите",
    "никто не ожидал",
    "что произошло дальше",
    "самое интересное",
    "вот что случилось",
    "результат вас удивит",
    "вы будете удивлены",
    "никто не мог представить",
    "вот что произошло",
    "что было потом",
    "вы даже не представляете",
    "шок",
    "неожиданный поворот",
]


class CuriosityBaitRule:
    reason = "curiosity_bait"
    weight = 0.20
    feature = "has_curiosity_phrase"

    def check(self, post: CatalogPost) -> RuleResult:
        normalized = normalize_text(post.text)
        matched = any_phrase(normalized, CURIOSITY_PHRASES)
        return RuleResult(
            matched=matched,
            weight=self.weight if matched else 0.0,
            reason=self.reason,
            feature=self.feature,
        )
