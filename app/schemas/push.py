from typing import Literal

from pydantic import BaseModel, Field


class PushDeviceRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=512, pattern=r"^ExponentPushToken\[[^\]]+\]$|^ExpoPushToken\[[^\]]+\]$")
    platform: Literal["android", "ios"]


class PushDeviceResponse(BaseModel):
    registered: bool


class PushDeviceStatusResponse(BaseModel):
    registered_devices: int
