"""Trusted-source classification loaded from config/source_registry.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml


@dataclass(frozen=True, slots=True)
class SourceClassification:
    source_id: str | None
    role: str
    tier: int | None
    domain: str
    is_official: bool
    is_discovery_only: bool


class SourceRegistry:
    def __init__(self, config_path: Path | None = None) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        self.config_path = config_path or repo_root / "config" / "source_registry.yaml"
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        self.rules = data.get("rules") or {}
        self._domains: dict[str, dict] = {}
        for source in data.get("sources") or []:
            for domain in source.get("domains") or []:
                self._domains[str(domain).lower()] = source

    def classify(self, url: str) -> SourceClassification:
        parsed = urlparse(url)
        domain = (parsed.hostname or "").lower()
        source = self._domains.get(domain)
        if source is None:
            return SourceClassification(
                source_id=None,
                role="unknown",
                tier=None,
                domain=domain,
                is_official=False,
                is_discovery_only=True,
            )
        role = str(source.get("role", "unknown"))
        return SourceClassification(
            source_id=str(source.get("id")),
            role=role,
            tier=int(source.get("tier")) if source.get("tier") is not None else None,
            domain=domain,
            is_official=role == "official",
            is_discovery_only=role != "official",
        )

    def is_https_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if self.rules.get("require_https", True) and parsed.scheme != "https":
            return False
        return bool(parsed.hostname)
