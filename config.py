import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID     = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
TRAVELPAYOUTS_TOKEN  = os.getenv("TRAVELPAYOUTS_TOKEN")        # ex TEQUILA_API_KEY
SERPAPI_KEY          = os.getenv("SERPAPI_KEY")                # ex FLIGHTAPI_KEY (opzionale)
CHECK_INTERVAL_HOURS = int(os.getenv("CHECK_INTERVAL_HOURS", "3"))
ALERT_COOLDOWN_HOURS = int(os.getenv("ALERT_COOLDOWN_HOURS", "6"))
DATABASE_URL         = os.getenv("DATABASE_URL", "sqlite:///flight_monitor.db")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN mancante nel file .env")
if not TELEGRAM_CHAT_ID:
    raise ValueError("TELEGRAM_CHAT_ID mancante nel file .env")
if not TRAVELPAYOUTS_TOKEN:
    raise ValueError(
        "TRAVELPAYOUTS_TOKEN mancante nel file .env\n"
        "Registrati su travelpayouts.com → Dashboard → API access per ottenere il token gratuito."
    )
# SERPAPI_KEY è opzionale: se assente il fallback Google Flights è disabilitato
if not SERPAPI_KEY:
    import logging
    logging.getLogger(__name__).warning(
        "SERPAPI_KEY non configurata: il fallback Google Flights non sarà disponibile. "
        "Registrati su serpapi.com per 250 ricerche/mese gratuite."
    )