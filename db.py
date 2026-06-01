from contextlib import contextmanager
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String,
    Float, Boolean, DateTime, ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker
from config import DATABASE_URL

engine       = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Route(Base):
    """Una tratta da monitorare (es. MXP → GRU, 15 nov – 30 nov)."""
    __tablename__ = "routes"

    id                  = Column(Integer,  primary_key=True, autoincrement=True)
    origin              = Column(String,   nullable=False)
    destination         = Column(String,   nullable=False)
    departure_date      = Column(String,   nullable=False)
    return_date         = Column(String,   nullable=True)
    base_price          = Column(Float,    nullable=True)    # legacy, mantenuto per retrocompat.
    base_price_currency = Column(String,   nullable=True)    # legacy
    created_at          = Column(DateTime, default=datetime.utcnow)
    is_active           = Column(Boolean,  default=True)
    max_stops           = Column(Integer,  nullable=True)

    price_checks      = relationship("PriceCheck",           back_populates="route", cascade="all, delete-orphan")
    alert_logs        = relationship("AlertLog",              back_populates="route", cascade="all, delete-orphan")
    monitored_flights = relationship("MonitoredFlight",       back_populates="route", cascade="all, delete-orphan")
    pending_proposals = relationship("PendingFlightProposal", back_populates="route", cascade="all, delete-orphan")


class PriceCheck(Base):
    """Legacy: rilevazione a livello di rotta (pre-v2). Mantenuta per retrocompatibilità."""
    __tablename__ = "price_checks"

    id         = Column(Integer,  primary_key=True, autoincrement=True)
    route_id   = Column(Integer,  ForeignKey("routes.id"), nullable=False)
    checked_at = Column(DateTime, default=datetime.utcnow)
    price      = Column(Float,    nullable=False)
    currency   = Column(String,   nullable=False)
    airline    = Column(String,   nullable=True)
    deep_link  = Column(String,   nullable=True)

    route = relationship("Route", back_populates="price_checks")


class MonitoredFlight(Base):
    """
    Uno dei voli attivamente monitorati per una tratta.
    Di norma 3, espandibile dall'utente tramite la funzione 'Aggiungi' sui bottoni Telegram.
    """
    __tablename__ = "monitored_flights"

    id                  = Column(Integer,  primary_key=True, autoincrement=True)
    route_id            = Column(Integer,  ForeignKey("routes.id"), nullable=False)
    airline             = Column(String,   nullable=True)
    base_price          = Column(Float,    nullable=False)
    base_price_currency = Column(String,   nullable=False, default="EUR")
    duration_minutes    = Column(Integer,  nullable=True)   # None = non disponibile dall'API
    deep_link           = Column(String,   nullable=True)
    is_active           = Column(Boolean,  default=True)
    created_at          = Column(DateTime, default=datetime.utcnow)

    route        = relationship("Route",            back_populates="monitored_flights")
    price_checks = relationship("FlightPriceCheck", back_populates="monitored_flight", cascade="all, delete-orphan")
    alert_logs   = relationship("AlertLog",         back_populates="monitored_flight")


class FlightPriceCheck(Base):
    """Ogni singola rilevazione di prezzo per un MonitoredFlight."""
    __tablename__ = "flight_price_checks"

    id                  = Column(Integer,  primary_key=True, autoincrement=True)
    monitored_flight_id = Column(Integer,  ForeignKey("monitored_flights.id"), nullable=False)
    checked_at          = Column(DateTime, default=datetime.utcnow)
    price               = Column(Float,    nullable=False)
    currency            = Column(String,   nullable=False)

    monitored_flight = relationship("MonitoredFlight", back_populates="price_checks")


class AlertLog(Base):
    """
    Traccia ogni alert inviato per il meccanismo anti-spam (cooldown).
    alert_type: "price_drop"  → calo >=20% su un volo monitorato
                "new_cheaper" → trovato nuovo volo più economico dei monitorati
    """
    __tablename__ = "alert_log"

    id                  = Column(Integer,  primary_key=True, autoincrement=True)
    route_id            = Column(Integer,  ForeignKey("routes.id"), nullable=False)
    monitored_flight_id = Column(Integer,  ForeignKey("monitored_flights.id"), nullable=True)
    sent_at             = Column(DateTime, default=datetime.utcnow)
    alert_type          = Column(String,   nullable=False, default="price_drop")

    route            = relationship("Route",           back_populates="alert_logs")
    monitored_flight = relationship("MonitoredFlight", back_populates="alert_logs")


class PendingFlightProposal(Base):
    """
    Proposta in attesa di risposta utente: un volo più economico trovato dal checker
    che potrebbe sostituire uno dei monitorati o essere aggiunto alla lista.
    resolved=False finché l'utente non preme uno dei bottoni Telegram.
    """
    __tablename__ = "pending_flight_proposals"

    id                = Column(Integer,  primary_key=True, autoincrement=True)
    route_id          = Column(Integer,  ForeignKey("routes.id"), nullable=False)
    replace_flight_id = Column(Integer,  ForeignKey("monitored_flights.id"), nullable=True)
    airline           = Column(String,   nullable=True)
    price             = Column(Float,    nullable=False)
    currency          = Column(String,   nullable=False, default="EUR")
    duration_minutes  = Column(Integer,  nullable=True)
    deep_link         = Column(String,   nullable=True)
    created_at        = Column(DateTime, default=datetime.utcnow)
    resolved          = Column(Boolean,  default=False)

    route = relationship("Route", back_populates="pending_proposals")


def init_db():
    """Crea tutte le tabelle se non esistono. Sicuro da chiamare più volte."""
    Base.metadata.create_all(engine)


@contextmanager
def get_session():
    """
    Context manager per la sessione DB con rollback automatico su eccezione.
    Usare sempre con: 'with get_session() as session:'
    """
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()