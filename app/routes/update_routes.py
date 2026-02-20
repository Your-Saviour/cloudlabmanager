"""Update check API routes."""

from fastapi import APIRouter, Depends, Request

from auth import get_current_user

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/updates")
async def get_update_status(
    request: Request,
    user=Depends(get_current_user),
):
    """Return update availability for CloudLab and CLM repos."""
    checker = request.app.state.update_checker
    return checker.get_status()
