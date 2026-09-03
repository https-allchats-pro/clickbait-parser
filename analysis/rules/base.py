from __future__ import annotations

from typing import Protocol

from analysis.models import RuleResult
from domain.posts import CatalogPost


class ClickbaitRule(Protocol):
    reason: str
    weight: float

    def check(self, post: CatalogPost) -> RuleResult: ...
