from fastapi import APIRouter
from sqlalchemy import delete, func, select

from app.dependencies import CurrentUser, DbSession
from app.models.push_device import PushDevice
from app.schemas.push import PushDeviceRequest, PushDeviceResponse, PushDeviceStatusResponse

router = APIRouter()


@router.post("/devices", response_model=PushDeviceResponse)
async def register_push_device(payload: PushDeviceRequest, current_user: CurrentUser, db: DbSession):
    result = await db.execute(select(PushDevice).where(PushDevice.token == payload.token))
    device = result.scalar_one_or_none()
    if device is None:
        db.add(PushDevice(user_id=current_user.id, token=payload.token, platform=payload.platform))
    else:
        device.user_id = current_user.id
        device.platform = payload.platform
        device.updated_at = func.now()
    await db.commit()
    return PushDeviceResponse(registered=True)


@router.delete("/devices", response_model=PushDeviceResponse)
async def unregister_push_device(payload: PushDeviceRequest, current_user: CurrentUser, db: DbSession):
    await db.execute(
        delete(PushDevice).where(
            PushDevice.user_id == current_user.id,
            PushDevice.token == payload.token,
        )
    )
    await db.commit()
    return PushDeviceResponse(registered=False)


@router.get("/devices", response_model=PushDeviceStatusResponse)
async def get_push_device_status(current_user: CurrentUser, db: DbSession):
    result = await db.execute(
        select(func.count()).select_from(PushDevice).where(PushDevice.user_id == current_user.id)
    )
    return PushDeviceStatusResponse(registered_devices=result.scalar() or 0)
