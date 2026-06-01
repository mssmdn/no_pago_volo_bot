import logging
from datetime import datetime
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from config import TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def _fmt_duration(minutes: int | None) -> str:
    """Formatta una durata in minuti come '2h 30m'. Restituisce 'N/D' se None."""
    if minutes is None:
        return "N/D"
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m"


def _date_line(route) -> str:
    """Riga di testo con date di partenza (e ritorno se presente)."""
    if route.return_date:
        return f"📅 Partenza: {route.departure_date} | Ritorno: {route.return_date}"
    return f"📅 Partenza: {route.departure_date} (solo andata)"


async def send_flight_price_drop_alert(
    bot: Bot,
    route,
    monitored_flight,
    current_price: float,
    currency: str,
    airline: str,
    deep_link: str,
) -> None:
    """
    Invia alert di calo prezzo (>=20%) per un singolo volo monitorato.
    Mostra compagnia, durata totale, prezzo base, prezzo attuale e percentuale di calo.
    """
    drop_pct = ((monitored_flight.base_price - current_price) / monitored_flight.base_price) * 100

    message = (
        f"🚨 *PRICE DROP ALERT*\n"
        f"✈️ {route.origin} → {route.destination}\n"
        f"{_date_line(route)}\n\n"
        f"🏷️ Compagnia: *{airline}*\n"
        f"⏱️ Durata totale: {_fmt_duration(monitored_flight.duration_minutes)}\n\n"
        f"💸 Prezzo base: {currency}{monitored_flight.base_price:.0f}\n"
        f"📉 Prezzo attuale: *{currency}{current_price:.0f}* (-{drop_pct:.1f}%)\n\n"
        f"🔗 [Prenota ora]({deep_link})\n"
        f"🕐 Rilevato: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
    )

    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        logger.info(
            f"Alert price_drop inviato: {route.origin}→{route.destination} "
            f"({airline}, {currency}{current_price:.0f})"
        )
    except Exception as e:
        logger.error(f"Errore nell'invio dell'alert price_drop: {e}")


async def send_new_cheaper_flight_alert(
    bot: Bot,
    route,
    most_expensive_mf,
    new_flight: dict,
    proposal_id: int,
) -> None:
    """
    Notifica interattiva: trovato un volo più economico di uno dei monitorati.
    Presenta tre bottoni: Sostituisci / Aggiungi / Ignora.
    I callback_data codificano l'ID della proposta salvata nel DB.
    """
    currency     = new_flight["currency"]
    new_price    = new_flight["price"]
    new_airline  = new_flight["airline"] or "Sconosciuta"
    new_duration = _fmt_duration(new_flight.get("duration_minutes"))
    old_airline  = most_expensive_mf.airline or "Sconosciuta"
    old_price    = most_expensive_mf.base_price
    old_duration = _fmt_duration(most_expensive_mf.duration_minutes)
    saving       = old_price - new_price

    message = (
        f"🆕 *NUOVO VOLO PIÙ ECONOMICO TROVATO*\n"
        f"✈️ {route.origin} → {route.destination}\n"
        f"{_date_line(route)}\n\n"
        f"*Attualmente il più costoso tra i monitorati:*\n"
        f"  🏷️ {old_airline} — {currency}{old_price:.0f} | ⏱️ {old_duration}\n\n"
        f"*Nuovo volo trovato:*\n"
        f"  🏷️ {new_airline} — {currency}{new_price:.0f} | ⏱️ {new_duration}\n"
        f"  💰 Risparmio potenziale: {currency}{saving:.0f}\n\n"
        f"Cosa vuoi fare?"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"♻️ Sostituisci {old_airline} con {new_airline}",
            callback_data=f"prop_rep:{proposal_id}",
        )],
        [InlineKeyboardButton(
            f"➕ Monitora anche {new_airline}",
            callback_data=f"prop_add:{proposal_id}",
        )],
        [InlineKeyboardButton(
            "❌ Ignora",
            callback_data=f"prop_ign:{proposal_id}",
        )],
    ])

    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=keyboard,
        )
        logger.info(
            f"Alert new_cheaper inviato: {route.origin}→{route.destination} "
            f"({new_airline}, proposta ID {proposal_id})"
        )
    except Exception as e:
        logger.error(f"Errore nell'invio dell'alert new_cheaper: {e}")