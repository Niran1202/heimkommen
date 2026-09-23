from datetime import date

from pydantic import BaseModel, Field


class StationOut(BaseModel):
    id: str
    name: str
    lat: float | None = None
    lon: float | None = None
    is_rail: bool = False


class StopOut(BaseModel):
    station_id: str
    name: str
    platform: str | None = None
    lat: float | None = None
    lon: float | None = None


class LegRisk(BaseModel):
    modelled: bool = Field(description="False for buses/trams, which are assumed to run on time")
    p_cancel: float
    departure_delay_p50: float
    arrival_delay_p50: float
    arrival_delay_p90: float


class LegOut(BaseModel):
    route: str
    category: str
    headsign: str | None = None
    train_number: str | None = None
    origin: StopOut
    destination: StopOut
    departure: str
    arrival: str
    duration_minutes: int
    risk: LegRisk


class PlanBOut(BaseModel):
    departure: str
    arrival: str
    summary: str
    transfers: int


class TransferOut(BaseModel):
    index: int = Field(description="Index of the leg that has to be boarded (0 = first train)")
    station: str
    planned_buffer_minutes: int | None = None
    p_miss: float
    plan_b: PlanBOut | None = None


class JourneyRisk(BaseModel):
    p_connections: float = Field(description="Probability that every planned connection works")
    p_home: float = Field(description="Probability to reach the destination tonight (incl. Plan B)")
    p_stranded: float
    p_on_time: float = Field(description="Probability to arrive at most 5 minutes after the planned arrival")
    arrival_p50: str | None = None
    arrival_p90: str | None = None
    level: str = Field(description="low / medium / high")


class JourneyOut(BaseModel):
    id: str
    service_date: date
    departure: str
    arrival: str
    duration_minutes: int
    transfers: int
    legs: list[LegOut]
    connections: list[TransferOut]
    risk: JourneyRisk
    weak_point: TransferOut | None = None


class JourneySummary(BaseModel):
    departure: str
    arrival: str
    p_home: float
    journey_id: str


class HomeCheckResponse(BaseModel):
    origin: StationOut
    destination: StationOut
    service_date: date
    after: str
    regional_only: bool
    model_version: str
    journeys: list[JourneyOut]
    latest_safe_departure: JourneySummary | None = None
    last_connection: JourneySummary | None = None
    confidence: float
    notes: list[str] = []


class DeadlineCheck(BaseModel):
    departure: str
    arrival: str
    p_arrive_by: float


class DeadlineResponse(BaseModel):
    origin: StationOut
    destination: StationOut
    service_date: date
    arrive_by: str
    confidence: float
    regional_only: bool
    model_version: str
    recommended: JourneyOut | None = None
    p_arrive_by: float | None = None
    checked: list[DeadlineCheck]
    notes: list[str] = []


class StationsResponse(BaseModel):
    query: str
    stations: list[StationOut]


class LiveStop(BaseModel):
    station: str
    eva: str
    train: str
    planned_departure: str | None = None
    expected_departure: str | None = None
    delay_minutes: int | None = None
    cancelled: bool = False
    platform: str | None = None


class LiveJourneyResponse(BaseModel):
    journey_id: str
    available: bool
    source: str
    legs: list[LiveStop]
    notes: list[str] = []
