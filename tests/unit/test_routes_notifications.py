"""알림 라우터 wiring 테스트 — DB 호출은 service 레이어를 monkeypatch 해 격리.

검증 포인트:
- 쿼리 파라미터 (user_id, status) 파싱
- service 함수에 정확한 인자가 전달되는지
- 응답 status code 와 shape (특히 DELETE 204, mark-all-read 의 updated 카운트)
- 404 매핑 (HTTPException → 404)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.models.calendar import NotificationStatus
from app.services import notification_service


client = TestClient(app)
UID = uuid.UUID("00000000-0000-0000-0000-000000000001")
NID = uuid.UUID("11111111-1111-1111-1111-111111111111")
TID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _row(status=NotificationStatus.UNREAD) -> dict:
    """NotificationResponse 스키마(model_config={"from_attributes": True}) 가 받을 수 있는
    객체. dict 가 아닌 SimpleNamespace 가 필요하므로 ad-hoc class 로."""
    class _Row:
        id = NID
        user_id = UID
        term_id = TID
        version_id = None
        title = "테스트 알림"
        diff_summary = "주요 변경 없음"
    r = _Row()
    r.status = status
    r.created_at = datetime(2026, 5, 15, tzinfo=timezone.utc)
    return r


# ── GET / ────────────────────────────────────────────────


def test_get_returns_list_and_unread_count(monkeypatch):
    captured = {}

    async def fake_list(db, user_id, status=None):
        captured["user_id"] = user_id
        captured["status"] = status
        return [_row(), _row(status=NotificationStatus.READ)], 1

    monkeypatch.setattr(notification_service, "list_notifications", fake_list)
    r = client.get(f"/notifications?user_id={UID}")
    assert r.status_code == 200
    body = r.json()
    assert body["unread_count"] == 1
    assert len(body["notifications"]) == 2
    assert captured["user_id"] == UID
    assert captured["status"] is None


def test_get_passes_status_filter(monkeypatch):
    captured = {}

    async def fake_list(db, user_id, status=None):
        captured["status"] = status
        return [], 0

    monkeypatch.setattr(notification_service, "list_notifications", fake_list)
    r = client.get(f"/notifications?user_id={UID}&status=UNREAD")
    assert r.status_code == 200
    assert captured["status"] == NotificationStatus.UNREAD


# ── PATCH /read-all ──────────────────────────────────────


def test_mark_all_read_returns_updated_count(monkeypatch):
    captured = {}

    async def fake_all(db, user_id):
        captured["user_id"] = user_id
        return 5

    monkeypatch.setattr(notification_service, "mark_all_as_read", fake_all)
    r = client.patch(f"/notifications/read-all?user_id={UID}")
    assert r.status_code == 200
    assert r.json() == {"updated": 5}
    assert captured["user_id"] == UID


def test_mark_all_read_when_nothing_unread(monkeypatch):
    """이미 다 읽음 상태여도 200 + updated=0 (idempotent)."""

    async def fake_all(db, user_id):
        return 0

    monkeypatch.setattr(notification_service, "mark_all_as_read", fake_all)
    r = client.patch(f"/notifications/read-all?user_id={UID}")
    assert r.status_code == 200
    assert r.json() == {"updated": 0}


# ── PATCH /{id}/read ─────────────────────────────────────


def test_mark_single_read_returns_notification(monkeypatch):
    async def fake_single(db, notification_id, user_id):
        assert notification_id == NID
        assert user_id == UID
        return _row(status=NotificationStatus.READ)

    monkeypatch.setattr(notification_service, "mark_as_read", fake_single)
    r = client.patch(f"/notifications/{NID}/read?user_id={UID}")
    assert r.status_code == 200
    assert r.json()["status"] == "READ"


def test_mark_single_read_404_when_service_raises(monkeypatch):
    async def fake_single(db, notification_id, user_id):
        raise HTTPException(status_code=404, detail="Notification not found")

    monkeypatch.setattr(notification_service, "mark_as_read", fake_single)
    r = client.patch(f"/notifications/{NID}/read?user_id={UID}")
    assert r.status_code == 404
    assert r.json()["detail"] == "Notification not found"


# ── DELETE /{id} ─────────────────────────────────────────


def test_delete_returns_204(monkeypatch):
    captured = {}

    async def fake_delete(db, notification_id, user_id):
        captured["notification_id"] = notification_id
        captured["user_id"] = user_id

    monkeypatch.setattr(notification_service, "delete_notification", fake_delete)
    r = client.delete(f"/notifications/{NID}?user_id={UID}")
    assert r.status_code == 204
    assert r.content == b""  # 204 본문 없음
    assert captured["notification_id"] == NID
    assert captured["user_id"] == UID


def test_delete_404_when_service_raises(monkeypatch):
    async def fake_delete(db, notification_id, user_id):
        raise HTTPException(status_code=404, detail="Notification not found")

    monkeypatch.setattr(notification_service, "delete_notification", fake_delete)
    r = client.delete(f"/notifications/{NID}?user_id={UID}")
    assert r.status_code == 404


# ── /read-all 와 /{id}/read 라우트 순서 (정규 → 동적 경로 prefix 충돌 가드) ────


def test_read_all_does_not_match_uuid_path(monkeypatch):
    """`/read-all` 이 UUID path param 으로 잘못 잡히면 안 된다 — FastAPI 라우트 순서 의존.

    잘못 잡히면 mark_as_read 가 호출되어 UUID 파싱 422 가 떨어진다.
    """
    called: dict = {"single": 0, "all": 0}

    async def single(db, notification_id, user_id):
        called["single"] += 1
        return _row()

    async def all_(db, user_id):
        called["all"] += 1
        return 0

    monkeypatch.setattr(notification_service, "mark_as_read", single)
    monkeypatch.setattr(notification_service, "mark_all_as_read", all_)
    r = client.patch(f"/notifications/read-all?user_id={UID}")
    assert r.status_code == 200, r.text
    assert called == {"single": 0, "all": 1}
