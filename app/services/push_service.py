import logging
from collections.abc import Sequence
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.push_device import PushDevice
from app.services.http_client import get_http_client

logger = logging.getLogger(__name__)

EXPO_PUSH_ENDPOINT = "https://exp.host/--/api/v2/push/send"
PushDestination = Literal["/notifications", "/messages"]


class PushService:
    """Best-effort delivery through Expo Push Service."""

    @staticmethod
    async def send_to_user(
        db: AsyncSession,
        user_id: int,
        *,
        destination: PushDestination,
    ) -> None:
        try:
            result = await db.execute(select(PushDevice).where(PushDevice.user_id == user_id))
            devices = list(result.scalars().all())
            if not devices:
                return

            payloads = [PushService._payload(device.token, destination) for device in devices]
            response = await get_http_client().post(
                EXPO_PUSH_ENDPOINT,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json=payloads,
            )
            response.raise_for_status()
            tickets = response.json().get("data", [])
            invalid_tokens = PushService._invalid_tokens(devices, tickets)
            if invalid_tokens:
                await db.execute(delete(PushDevice).where(PushDevice.token.in_(invalid_tokens)))
                await db.commit()
        except Exception as error:
            logger.warning("Push delivery failed for user %s: %s", user_id, error)

    @staticmethod
    def _payload(token: str, destination: PushDestination) -> dict[str, object]:
        """Build a deliberately generic payload with no social or message content."""
        return {
            "to": token,
            "title": "SoundScore",
            "body": "You have new activity.",
            "data": {"url": destination},
            "sound": "default",
            "channelId": "social",
        }

    @staticmethod
    def _invalid_tokens(devices: Sequence[PushDevice], tickets: object) -> list[str]:
        if not isinstance(tickets, list):
            return []
        invalid: list[str] = []
        for device, ticket in zip(devices, tickets):
            if not isinstance(ticket, dict):
                continue
            details = ticket.get("details")
            if ticket.get("status") == "error" and isinstance(details, dict) and details.get("error") == "DeviceNotRegistered":
                invalid.append(device.token)
        return invalid


push_service = PushService()
