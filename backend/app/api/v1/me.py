from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DbSession, EngineDep
from app.models.user import SavedTrip
from app.schemas.users import SavedTripIn, SavedTripOut, UserOut

router = APIRouter(prefix="/api/v1/me", tags=["me"])


@router.get("", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(user: CurrentUser, db: DbSession) -> Response:
    """Delete the account and every saved trip (GDPR Art. 17)."""
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/trips", response_model=list[SavedTripOut])
def list_trips(user: CurrentUser, db: DbSession) -> list[SavedTripOut]:
    trips = db.query(SavedTrip).filter(SavedTrip.user_id == user.id).order_by(SavedTrip.created_at.desc()).all()
    return [SavedTripOut.model_validate(t) for t in trips]


@router.post("/trips", response_model=SavedTripOut, status_code=status.HTTP_201_CREATED)
def create_trip(body: SavedTripIn, user: CurrentUser, db: DbSession, eng: EngineDep) -> SavedTripOut:
    origin = eng.store.resolve_station(body.from_station_id)
    destination = eng.store.resolve_station(body.to_station_id)
    if origin is None or destination is None:
        raise HTTPException(status_code=422, detail="Unknown station")
    if db.query(SavedTrip).filter(SavedTrip.user_id == user.id).count() >= 50:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At most 50 saved trips")
    trip = SavedTrip(
        user_id=user.id, label=body.label, from_station_id=origin.id, from_station_name=origin.name,
        to_station_id=destination.id, to_station_name=destination.name, usual_departure=body.usual_departure,
        regional_only=body.regional_only,
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return SavedTripOut.model_validate(trip)


@router.delete("/trips/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trip(trip_id: int, user: CurrentUser, db: DbSession) -> Response:
    trip = db.get(SavedTrip, trip_id)
    if trip is None or trip.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    db.delete(trip)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
