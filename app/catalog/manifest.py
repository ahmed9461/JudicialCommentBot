"""Load the declarative official catalog source manifest."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class CatalogSourceSpec:
    id: str
    source_id: str
    source_name: str
    kind: str
    enabled: bool = True
    url_template: str | None = None
    volume_start: int | None = None
    volume_end: int | None = None
    landing_pages: tuple[str, ...] = field(default_factory=tuple)
    max_depth: int = 1
    max_pages: int = 100
    allowed_path_prefixes: tuple[str, ...] = field(default_factory=tuple)

    def direct_documents(self) -> list[tuple[str, str]]:
        if self.kind != "numbered_pdf_series" or not self.url_template:
            return []
        if self.volume_start is None or self.volume_end is None:
            return []
        return [
            (f"{self.id}:v{volume}", self.url_template.format(volume=volume))
            for volume in range(self.volume_start, self.volume_end + 1)
        ]


@dataclass(frozen=True, slots=True)
class CatalogManifest:
    sources: tuple[CatalogSourceSpec, ...]
    min_case_text_chars: int = 350
    max_case_text_chars: int = 18000
    request_delay_seconds: float = 0.35


class CatalogManifestLoader:
    def __init__(self, path: Path | None = None) -> None:
        root = Path(__file__).resolve().parents[2]
        self.path = path or root / "config" / "catalog_sources.yaml"

    def load(self) -> CatalogManifest:
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        rules = data.get("rules") or {}
        sources: list[CatalogSourceSpec] = []
        for item in data.get("sources") or []:
            volumes = item.get("volumes") or {}
            sources.append(
                CatalogSourceSpec(
                    id=str(item["id"]),
                    source_id=str(item["source_id"]),
                    source_name=str(item["source_name"]),
                    kind=str(item["kind"]),
                    enabled=bool(item.get("enabled", True)),
                    url_template=str(item["url_template"]) if item.get("url_template") else None,
                    volume_start=int(volumes["start"]) if volumes.get("start") is not None else None,
                    volume_end=int(volumes["end"]) if volumes.get("end") is not None else None,
                    landing_pages=tuple(map(str, item.get("landing_pages") or [])),
                    max_depth=max(0, int(item.get("max_depth", 1))),
                    max_pages=max(1, int(item.get("max_pages", 100))),
                    allowed_path_prefixes=tuple(map(str, item.get("allowed_path_prefixes") or [])),
                )
            )
        return CatalogManifest(
            sources=tuple(sources),
            min_case_text_chars=max(100, int(rules.get("min_case_text_chars", 350))),
            max_case_text_chars=max(1000, int(rules.get("max_case_text_chars", 18000))),
            request_delay_seconds=max(0.0, float(rules.get("request_delay_seconds", 0.35))),
        )
