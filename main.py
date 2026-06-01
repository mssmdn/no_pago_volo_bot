import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import init_db
from bot import build_application
from checker import run_price_checks
from config import CHECK_INTERVAL_HOURS

# Logging strutturato verso stdout: Railway lo cattura automaticamente
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

async def main():
    # 1. Inizializza il database (crea le tabelle se non esistono)
    init_db()
    logger.info("Database inizializzato.")

    # 2. Costruisce l'applicazione Telegram
    app = build_application()

    # 3. Configura lo scheduler asincrono
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_price_checks,
        trigger="interval",
        hours=CHECK_INTERVAL_HOURS,
        args=[app.bot],
        id="price_check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler avviato. Check ogni {CHECK_INTERVAL_HOURS} ore.")

    # 4. Avvia il bot in modalità polling (non richiede webhook su Railway)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot Telegram avviato e in ascolto.")

    # 5. Mantieni tutto in esecuzione finché non arriva un segnale di stop
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
