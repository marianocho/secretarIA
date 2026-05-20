"""Wrapper do Google Calendar API. Cria eventos a partir de ParsedEvent."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src import config
from src.models import ExistingEvent, ParsedEvent


class CreatedEvent(TypedDict):
    event_id: str
    html_link: str


def _load_credentials() -> Credentials:
    if not config.GOOGLE_TOKEN_PATH.exists():
        raise FileNotFoundError(
            f"Token do Google não encontrado em {config.GOOGLE_TOKEN_PATH}. "
            f"Rode `python -m src.auth_google` primeiro."
        )

    creds = Credentials.from_authorized_user_file(
        str(config.GOOGLE_TOKEN_PATH), config.GOOGLE_CALENDAR_SCOPES
    )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            config.GOOGLE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "Token inválido e sem refresh_token. Rode `python -m src.auth_google` de novo."
            )

    return creds


_service = None


def _get_service():
    global _service
    if _service is None:
        creds = _load_credentials()
        _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _service


def _build_event_body(event: ParsedEvent) -> dict:
    body: dict = {"summary": event.title}

    if event.location:
        body["location"] = event.location
    if event.notes:
        body["description"] = event.notes

    if event.is_all_day:
        body["start"] = {"date": event.start.date().isoformat()}
        body["end"] = {"date": event.end.date().isoformat()}
    else:
        body["start"] = {
            "dateTime": event.start.isoformat(),
            "timeZone": config.TIMEZONE_NAME,
        }
        body["end"] = {
            "dateTime": event.end.isoformat(),
            "timeZone": config.TIMEZONE_NAME,
        }

    return body


def create_event(event: ParsedEvent) -> CreatedEvent:
    service = _get_service()
    body = _build_event_body(event)
    created = service.events().insert(calendarId="primary", body=body).execute()
    return CreatedEvent(event_id=created["id"], html_link=created["htmlLink"])


def find_conflicts(event: ParsedEvent) -> list[ExistingEvent]:
    """Lista eventos timed existentes que sobrepõem o horário de `event`.

    Regras:
    - Se `event` é all-day, retorna lista vazia (all-day não conflita).
    - Eventos all-day no calendário também são ignorados na resposta.
    - A API do Google já faz o filtro de overlap quando passamos timeMin/timeMax.
    """
    if event.is_all_day:
        return []

    service = _get_service()
    response = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=event.start.isoformat(),
            timeMax=event.end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        .execute()
    )

    conflicts: list[ExistingEvent] = []
    for item in response.get("items", []):
        start_field = item.get("start", {})
        end_field = item.get("end", {})

        if "dateTime" not in start_field:
            continue  # all-day, ignora

        conflicts.append(
            ExistingEvent(
                event_id=item["id"],
                summary=item.get("summary", "(sem título)"),
                start=datetime.fromisoformat(start_field["dateTime"]),
                end=datetime.fromisoformat(end_field["dateTime"]),
                html_link=item.get("htmlLink", ""),
            )
        )
    return conflicts


def update_event_times(
    event_id: str, new_start: datetime, new_end: datetime, is_all_day: bool
) -> CreatedEvent:
    """Move um evento existente pra novo horário (patch — preserva event_id, link, etc.)."""
    service = _get_service()
    if is_all_day:
        body: dict = {
            "start": {"date": new_start.date().isoformat()},
            "end": {"date": new_end.date().isoformat()},
        }
    else:
        body = {
            "start": {
                "dateTime": new_start.isoformat(),
                "timeZone": config.TIMEZONE_NAME,
            },
            "end": {
                "dateTime": new_end.isoformat(),
                "timeZone": config.TIMEZONE_NAME,
            },
        }
    updated = (
        service.events()
        .patch(calendarId="primary", eventId=event_id, body=body)
        .execute()
    )
    return CreatedEvent(event_id=updated["id"], html_link=updated["htmlLink"])
