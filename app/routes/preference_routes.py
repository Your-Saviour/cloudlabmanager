import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from auth import get_current_user
from database import User, UserPreference
from db_session import get_db_session
from models import UserPreferencesUpdate

router = APIRouter(prefix="/api/users/me", tags=["preferences"])

MAX_PREFERENCES_SIZE = 64 * 1024  # 64 KB limit for preferences JSON


@router.get("/preferences")
async def get_preferences(user: User = Depends(get_current_user),
                          session: Session = Depends(get_db_session)):
    pref = session.query(UserPreference).filter_by(user_id=user.id).first()
    if not pref:
        return {"preferences": {}}
    try:
        return {"preferences": json.loads(pref.preferences)}
    except (json.JSONDecodeError, TypeError):
        return {"preferences": {}}


@router.put("/preferences")
async def update_preferences(req: UserPreferencesUpdate,
                             user: User = Depends(get_current_user),
                             session: Session = Depends(get_db_session)):
    pref = session.query(UserPreference).filter_by(user_id=user.id).first()
    if not pref:
        pref = UserPreference(user_id=user.id, preferences="{}")
        session.add(pref)
        session.flush()

    # Merge incoming fields into existing preferences
    try:
        existing = json.loads(pref.preferences)
    except (json.JSONDecodeError, TypeError):
        existing = {}
    update_data = req.model_dump(exclude_none=True)
    existing.update(update_data)

    serialized = json.dumps(existing)
    if len(serialized) > MAX_PREFERENCES_SIZE:
        raise HTTPException(status_code=400, detail="Preferences payload too large")

    pref.preferences = serialized
    session.flush()

    return {"preferences": existing}
