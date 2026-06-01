import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID     = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
TRAVELPAYOUTS_TOKEN  = os.getenv("TRAVELPAYOUTS_TOKEN")
SERPAPI_KEY          = os.getenv("SERPAPI_KEY")
ALERT_COOLDOWN_HOURS = int(os.getenv("ALERT_COOLDOWN_HOURS", "6"))

# Orari del check automatico giornaliero (virgola-separati, ora locale)
# e fuso orario del proprietario del bot.
# Configurabili via variabili d'ambiente su Railway per adattarsi a qualsiasi timezone.
CHECK_TIMES    = os.getenv("CHECK_TIMES", "9,13,21")
CHECK_TIMEZONE = os.getenv("CHECK_TIMEZONE", "Europe/Rome")

# Railway a volte fornisce "postgres://" (formato legacy) invece di
# "postgresql://" richiesto da SQLAlchemy 2.x — questo lo corregge silenziosamente.
_raw_db_url  = os.getenv("DATABASE_URL", "sqlite:///flight_monitor.db")
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
        "SERPAPI_KEY non configurata: SerpAPI non disponibile. "
        "Il bot userà solo Aviasales come fonte dati. "
        "Registrati su serpapi.com per 250 ricerche/mese gratuite."
    )
