"""Service-level transaction and error behavior for migrated master data."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.errors import NotFoundError, ValidationError
from features.master_data import service as master_data_service
from infrastructure.database.dbo.Channel import Channel


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class FakeChannelRepository:
    def __init__(self, _: FakeSession) -> None:
        self.channels: dict[int, Channel] = {}
        self.names: set[str] = set()
        self.refreshes = 0

    def list(self) -> list[Channel]:
        return list(self.channels.values())

    def get(self, channel_id: int) -> Channel | None:
        return self.channels.get(channel_id)

    def get_by_name(self, name: str) -> Channel | None:
        return Channel(name=name) if name in self.names else None

    def add(self, channel: Channel) -> None:
        channel.id = len(self.channels) + 1
        self.channels[channel.id] = channel
        self.names.add(channel.name)

    def delete(self, channel: Channel) -> None:
        self.channels.pop(channel.id)
        self.names.remove(channel.name)

    def refresh(self, _: Channel) -> None:
        self.refreshes += 1


def test_channel_service_commits_only_mutations_and_preserves_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(master_data_service, "ChannelRepository", FakeChannelRepository)
    session = FakeSession()
    service = master_data_service.ChannelService(session)  # type: ignore[arg-type]

    created = service.create("App")

    assert created.id == 1
    assert session.commits == 1
    assert service.delete(created.id) == "Channel App deleted successfully"
    assert session.commits == 2


def test_channel_service_uses_existing_http_contract_error_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(master_data_service, "ChannelRepository", FakeChannelRepository)
    service = master_data_service.ChannelService(FakeSession())  # type: ignore[arg-type]

    service.create("App")
    with pytest.raises(ValidationError, match="Channel already exists"):
        service.create("App")
    with pytest.raises(NotFoundError, match="Channel not found"):
        service.get(99)
