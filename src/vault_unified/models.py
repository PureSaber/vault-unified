from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class Source(str, Enum):
    LOCAL = "local"
    PROTON_PASS = "proton_pass"
    BITWARDEN = "bitwarden"


@dataclass
class SecretEntry:
    """Unified secret representation across all backends."""

    title: str
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""
    source: Source = Source.LOCAL
    external_id: str = ""
    tags: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source"] = self.source.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecretEntry:
        source = data.get("source", Source.LOCAL.value)
        if isinstance(source, str):
            source = Source(source)
        return cls(
            id=data.get("id", str(uuid4())),
            title=data.get("title", ""),
            username=data.get("username", ""),
            password=data.get("password", ""),
            url=data.get("url", ""),
            notes=data.get("notes", ""),
            source=source,
            external_id=data.get("external_id", ""),
            tags=list(data.get("tags", [])),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )
