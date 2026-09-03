from __future__ import annotations

from analysis.rules.caps import CapsRule
from analysis.rules.continuation import ContinuationBaitRule
from analysis.rules.cta import CtaRule
from analysis.rules.cta_near_link import CtaNearLinkRule
from analysis.rules.curiosity import CuriosityBaitRule
from analysis.rules.ellipsis import EllipsisRule
from analysis.rules.emoji import EmojiRule
from analysis.rules.external_link import ExternalLinkRule
from analysis.rules.punctuation import ExcessivePunctuationRule
from analysis.rules.short_text_link import ShortTextWithLinkRule


def default_rules() -> list[object]:
    return [
        ContinuationBaitRule(),
        CuriosityBaitRule(),
        CtaRule(),
        ExternalLinkRule(),
        CtaNearLinkRule(),
        ShortTextWithLinkRule(),
        EllipsisRule(),
        ExcessivePunctuationRule(),
        CapsRule(),
        EmojiRule(),
    ]
