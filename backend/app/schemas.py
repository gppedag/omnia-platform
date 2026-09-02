from datetime import datetime, date
from typing import Optional, Literal
from pydantic import BaseModel, EmailStr


# --- Auth ---
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: Literal["admin", "operator", "patient"] = "patient"
    phone: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: str
    phone: Optional[str] = None
    is_active: bool
    can_chat: bool = True
    can_phone: bool = True

    class Config:
        from_attributes = True


# --- Patients ---
class PatientCreate(BaseModel):
    # Compatibilita' legacy: se valorizzato collega un User esistente.
    user_id: Optional[int] = None

    # Nuova anagrafica strutturata.
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

    date_of_birth: Optional[date] = None
    fiscal_code: Optional[str] = None
    notes: Optional[str] = None

    reminder_enabled: bool = True
    reminder_channels: Optional[str] = None
    reminder_telegram_chat_id: Optional[str] = None


class PatientOut(BaseModel):
    id: int
    user_id: int
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    fiscal_code: Optional[str] = None
    notes: Optional[str] = None
    reminder_enabled: bool = True
    reminder_channels: Optional[str] = None
    reminder_telegram_chat_id: Optional[str] = None

    class Config:
        from_attributes = True


# --- Bookings ---
class BookingCreate(BaseModel):
    patient_id: int
    operator_id: Optional[int] = None
    service_name: str
    scheduled_at: datetime
    duration_minutes: int | None = None
    priority: Literal["normal", "urgent"] = "normal"
    notes: Optional[str] = None


class BookingUpdate(BaseModel):
    status: Optional[Literal["pending", "confirmed", "cancelled", "completed"]] = None
    scheduled_at: Optional[datetime] = None
    duration_minutes: int | None = None
    priority: Optional[Literal["normal", "urgent"]] = None
    notes: Optional[str] = None


class BookingOut(BaseModel):
    id: int
    patient_id: int
    operator_id: Optional[int] = None
    service_name: str
    scheduled_at: datetime
    duration_minutes: int | None = None
    status: str
    priority: str
    notes: Optional[str] = None

    class Config:
        from_attributes = True


# --- Calls ---
class CallOut(BaseModel):
    id: int
    booking_id: Optional[int] = None
    caller_number: Optional[str] = None
    callee_number: Optional[str] = None
    channel: Optional[str] = None
    status: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    ai_intent: Optional[str] = None
    ai_sentiment: Optional[str] = None
    ai_confidence: Optional[int] = None
    ai_last_summary: Optional[str] = None

    class Config:
        from_attributes = True


class CallStatusUpdate(BaseModel):
    status: Literal["ringing", "active", "held", "ended", "missed"]

# --- Agende, medici e tipologie visita ---
class DoctorCreate(BaseModel):
    full_name: str
    specialty: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    active: bool = True
    external_provider: Literal['none','google','microsoft365'] = 'none'
    external_calendar_id: Optional[str] = None
    external_calendar_user: Optional[str] = None

class DoctorOut(DoctorCreate):
    id: int
    class Config:
        from_attributes = True

class VisitTypeCreate(BaseModel):
    code: Optional[str] = None
    name: str
    duration_minutes: int = 60
    buffer_before_minutes: int = 0
    buffer_after_minutes: int = 0
    color: str = '#0d6efd'
    active: bool = True
    notes: Optional[str] = None
    recall_enabled: bool = True
    recall_days: Optional[int] = None
    followup_enabled: bool = True
    private_price_cents: int = 0
    ssn_enabled: bool = False
    ssn_ticket_cents: int = 0
    requires_prescription: bool = False

class VisitTypeOut(VisitTypeCreate):
    id: int
    class Config:
        from_attributes = True

class AgendaRuleIn(BaseModel):
    weekday: int
    start_time: str
    end_time: str
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    active: bool = True

class AgendaCreate(BaseModel):
    name: str
    doctor_id: int
    location: Optional[str] = None
    timezone: str = 'Europe/Rome'
    slot_minutes: int = 60
    active: bool = True
    visit_type_ids: list[int] = []
    rules: list[AgendaRuleIn] = []

class AgendaOut(BaseModel):
    id: int
    name: str
    doctor_id: int
    location: Optional[str] = None
    timezone: str
    slot_minutes: int
    active: bool
    visit_type_ids: list[int] = []
    rules: list[dict] = []

class CalendarBookingCreate(BaseModel):
    patient_id: int
    agenda_id: Optional[int] = None
    visit_type_id: Optional[int] = None
    doctor_ids: list[int] = []
    scheduled_at: datetime
    duration_minutes: int | None = None
    priority: Literal['normal','urgent'] = 'normal'
    notes: Optional[str] = None
    sync_external: bool = True

class CalendarBookingUpdate(BaseModel):
    agenda_id: Optional[int] = None
    visit_type_id: Optional[int] = None
    doctor_ids: Optional[list[int]] = None
    scheduled_at: Optional[datetime] = None
    duration_minutes: int | None = None
    status: Optional[Literal['pending','confirmed','cancelled','completed']] = None
    priority: Optional[Literal['normal','urgent']] = None
    notes: Optional[str] = None
    sync_external: bool = True
