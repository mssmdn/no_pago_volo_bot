import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID     = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
TRAVELPAYOUTS_TOKEN  = os.getenv("TRAVELPAYOUTS_TOKEN")
SERPAPI_KEY          = os.getenv("SERPAPI_KEY")
CHECK_INTERVAL_HOURS = int(os.getenv("CHECK_INTERVAL_HOURS", "3"))
ALERT_COOLDOWN_HOURS = int(os.getenv("ALERT_COOLDOWN_HOURS", "6"))

# Railway a volte fornisce "postgres://" (formato legacy) invece di
# "postgresql://" che è quello richiesto da SQLAlchemy 2.x.
# Questa riga normalizza il prefisso in modo silenzioso.
_raw_db_url = os.getenv("DATABASE_URL", "sqlite:///flight_monitor.db")
DATABASE_URL = _raw_db_url.replace("postgres://", "postgresql://", 1)

if not TELEGRAM_BOT_TOKEN:
    raise ValueError(
        "TELEGRAM_BOT_TOKEN non trovato. "
        "In locale: aggiungi al file .env. "
        "Su Railway: aggiungi nel tab Variables del servizio."
    )
if not TELEGRAM_CHAT_ID:
    raise ValueError(
        "TELEGRAM_CHAT_ID non trovato. "
        "In locale: aggiungi al file .env. "
        "Su Railway: aggiungi nel tab Variables del servizio."
    )
if not TRAVELPAYOUTS_TOKEN:
    raise ValueError(
        "TRAVELPAYOUTS_TOKEN non trovato. "
        "In locale: aggiungi al file .env. "
        "Su Railway: aggiungi nel tab Variables del servizio."
    )

if not SERPAPI_KEY:
    import logging
    logging.getLogger(__name__).warning(
        "SERPAPI_KEY non configurata: il fallback Google Flights non sarà disponibile. "
        "Registrati su serpapi.com per 250 ricerche/mese gratuite."
    )
