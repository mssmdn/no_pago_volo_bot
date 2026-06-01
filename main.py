import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from db import init_db
from bot import build_application
from checker import run_price_checks
from config import CHECK_TIMES, CHECK_TIMEZONE

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _build_check_trigger() -> OrTrigger:
    """
    Costruisce un trigger APScheduler che scatta agli orari configurati in CHECK_TIMES.
    Ogni orario è un CronTrigger indipendente; OrTrigger li combina in un solo job.
    Il timezone garantisce che gli orari siano interpretati nell'ora locale dell'utente
    e non in UTC, gestendo automaticamente il cambio ora legale.
    """
    hours = [int(h.strip()) for h in CHECK_TIMES.split(",")]
    triggers = [
        CronTrigger(hour=h, minute=0, timezone=CHECK_TIMEZONE)
        for h in hours
    ]
    return OrTrigger(triggers)


async def main():
    # 1. Inizializza il database (crea le tabelle se non esistono)
    init_db()
    logger.info("Database inizializzato.")

    # 2. Costruisce l'applicazione Telegram
    app = build_application()

    # 3. Configura lo scheduler con i tre orari fissi
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_price_checks,
        trigger=_build_check_trigger(),
        args=[app.bot],
        id="price_check",
        replace_existing=True,
    )
    scheduler.start()

    times_str = ", ".join(
        f"{int(h.strip()):02d}:00" for h in CHECK_TIMES.split(",")
    )
    logger.info(
        f"Scheduler avviato. Check automatici alle {times_str} ({CHECK_TIMEZONE})."
    )

    # 4. Avvia il bot in modalità polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot Telegram avviato e in ascolto.")

    # 5. Mantieni tutto in esecuzione fino a segnale di stop
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Interruzione ricevuta, avvio shutdown...")
    finally:
        scheduler.shutdown(wait=False)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("Shutdown completato.")


if __name__ == "__main__":
    asyncio.run(main())
