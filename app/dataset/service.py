from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from analysis.models import ClickbaitAnalysis
from domain.dataset import (
    MAX_IMBALANCE_RATIO,
    MIN_CLICKBAIT_FOR_ML,
    MIN_NORMAL_FOR_ML,
    DatasetLabel,
    DatasetStats,
    DatasetValidation,
    PostLabel,
)
from domain.posts import CatalogPost
from infrastructure.db.repositories.analysis_repository import AnalysisRepository
from infrastructure.db.repositories.label_repository import LabelRepository
from infrastructure.db.repositories.post_repository import PostRepository

LabelMode = Literal["default", "random", "suspicious"]


class DatasetService:
    """Human labeling + export. Keeps ground truth separate from rule predictions."""

    def __init__(
        self,
        *,
        posts: PostRepository,
        labels: LabelRepository,
        analyses: AnalysisRepository,
    ) -> None:
        self._posts = posts
        self._labels = labels
        self._analyses = analyses

    def label_post(
        self,
        post_id: int,
        label: DatasetLabel,
        note: str | None = None,
    ) -> PostLabel:
        if not isinstance(label, DatasetLabel):
            raise ValueError(f"invalid label: {label!r}")
        post = self._posts.get_by_id(post_id)
        if post is None:
            raise ValueError(f"post {post_id} not found")
        now = int(time.time())
        return self._labels.save(
            PostLabel(
                post_id=post_id,
                label=label,
                note=note,
                created_at=now,
                updated_at=now,
            )
        )

    def get_next_unlabeled_post(self, *, mode: LabelMode = "default") -> CatalogPost | None:
        if mode == "random":
            return self._posts.get_random_unlabeled()
        if mode == "suspicious":
            return self._posts.get_suspicious_unlabeled()
        return self._posts.get_next_unlabeled()

    def get_label_context(
        self,
        post: CatalogPost,
    ) -> tuple[CatalogPost, ClickbaitAnalysis | None, PostLabel | None]:
        if post.id is None:
            raise ValueError("post.id is required")
        analysis = self._analyses.get_by_post_id(post.id)
        existing = self._labels.get_by_post_id(post.id)
        return post, analysis, existing

    def get_dataset_stats(self) -> DatasetStats:
        by_label = self._labels.count_by_label()
        total_labeled = sum(by_label.values())
        total_posts = self._posts.count_all()
        unlabeled = max(0, total_posts - total_labeled)
        rule_clickbait, rule_normal = self._analyses.count_predictions()

        # Disagreement only among labeled posts that also have analysis.
        human_cb_rule_n = 0
        human_n_rule_cb = 0
        for label in self._labels.list_all():
            analysis = self._analyses.get_by_post_id(label.post_id)
            if analysis is None:
                continue
            if label.label == DatasetLabel.CLICKBAIT and not analysis.is_clickbait:
                human_cb_rule_n += 1
            elif label.label == DatasetLabel.NORMAL and analysis.is_clickbait:
                human_n_rule_cb += 1

        return DatasetStats(
            total_labeled=total_labeled,
            unlabeled=unlabeled,
            by_label=by_label,
            rule_clickbait=rule_clickbait,
            rule_normal=rule_normal,
            disagreement_human_clickbait_rule_normal=human_cb_rule_n,
            disagreement_human_normal_rule_clickbait=human_n_rule_cb,
        )

    def validate(self) -> DatasetValidation:
        by_label = self._labels.count_by_label()
        total = sum(by_label.values())
        warnings: list[str] = []
        clickbait = by_label[DatasetLabel.CLICKBAIT]
        normal = by_label[DatasetLabel.NORMAL]

        if clickbait < MIN_CLICKBAIT_FOR_ML:
            warnings.append(
                f"Only {clickbait} clickbait examples available. "
                f"Recommended: >= {MIN_CLICKBAIT_FOR_ML} before training ML."
            )
        if normal < MIN_NORMAL_FOR_ML:
            warnings.append(
                f"Only {normal} normal examples available. "
                f"Recommended: >= {MIN_NORMAL_FOR_ML} before training ML."
            )
        binary_total = clickbait + normal
        if binary_total > 0:
            majority = max(clickbait, normal)
            minority = min(clickbait, normal) or 1
            ratio = majority / minority
            if ratio > MAX_IMBALANCE_RATIO:
                warnings.append(
                    f"Dataset is imbalanced (clickbait={clickbait}, normal={normal}, "
                    f"ratio={ratio:.1f} > {MAX_IMBALANCE_RATIO})."
                )
        if total == 0:
            warnings.append("No labeled posts yet.")

        return DatasetValidation(
            total_labeled=total,
            by_label=by_label,
            warnings=warnings,
        )

    def export_csv(self, path: Path | str) -> Path:
        """Export labeled posts only. Human label is ground truth; rule score is separate."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)

        labels = self._labels.list_all()
        fieldnames = [
            "post_id",
            "source",
            "owner_id",
            "post_id_vk",
            "text",
            "label",
            "rule_score",
            "rule_prediction",
            "reasons",
            "features",
        ]
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for label in labels:
                post = self._posts.get_by_id(label.post_id)
                if post is None:
                    continue
                analysis = self._analyses.get_by_post_id(label.post_id)
                writer.writerow(
                    {
                        "post_id": label.post_id,
                        "source": post.source,
                        "owner_id": post.owner_id,
                        "post_id_vk": post.post_id,
                        "text": post.text,
                        "label": label.label.value,
                        "rule_score": "" if analysis is None else f"{analysis.score:.4f}",
                        "rule_prediction": (
                            ""
                            if analysis is None
                            else ("clickbait" if analysis.is_clickbait else "normal")
                        ),
                        "reasons": (
                            ""
                            if analysis is None
                            else json.dumps(analysis.reasons, ensure_ascii=False)
                        ),
                        "features": (
                            ""
                            if analysis is None
                            else json.dumps(asdict(analysis.features), ensure_ascii=False)
                        ),
                    }
                )
        return out
