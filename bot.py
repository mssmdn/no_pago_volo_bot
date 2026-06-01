import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from db import (
    get_session, Route,
    MonitoredFlight, FlightPriceCheck, PendingFlightProposal,
)
from validators import validate_iata, validate_date, validate_return_date
from checker import run_price_checks
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CHECK_TIMES, CHECK_TIMEZONE

logger = logging.getLogger(__name__)

# ── Stati della conversazione /add ─────────────────────────────────────────────
ORIGIN, DESTINATION, DEPARTURE, RETURN_TYPE, RETURN_DATE, MAX_STOPS = range(6)


# ── Utility ────────────────────────────────────────────────────────────────────

def _fmt_duration(minutes: int | None) -> str:
    """Formatta una durata in minuti come '2h 30m'. Restituisce 'N/D' se None."""
    if minutes is None:
        return "N/D"
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m"


def _fmt_check_times() -> str:
    """Formatta gli orari di check configurati per i messaggi Telegram. Es: '09:00, 13:00, 21:00'"""
    return ", ".join(f"{int(h.strip()):02d}:00" for h in CHECK_TIMES.split(","))


def _stops_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✈️  Solo volo diretto", callback_data="stops_0")],
        [InlineKeyboardButton("↔️  Max 1 scalo",       callback_data="stops_1")],
        [InlineKeyboardButton("🌐  Qualsiasi",          callback_data="stops_any")],
    ])


# ── Autorizzazione ─────────────────────────────────────────────────────────────

def authorized(update: Update) -> bool:
    if update.effective_user is None:
        return False
    user_id = update.effective_user.id
    if user_id != TELEGRAM_CHAT_ID:
        logger.warning(f"Accesso non autorizzato da user_id: {user_id}")
        return False
    return True


# ── /start ─────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    await update.message.reply_text(
        "✈️ *Flight Price Monitor*\n\n"
        "Ti avviso quando uno dei voli monitorati cala del 20% o più.\n"
        "Per ogni rotta tengo d'occhio i *3 voli più economici* "
        "(compagnia aerea + durata totale).\n\n"
        "*Comandi disponibili:*\n"
        "• /add — Aggiungi una nuova rotta _(guida passo per passo)_\n"
        "• /list — Mostra le rotte e i voli monitorati\n"
        "• /remove `ID` — Disattiva una rotta\n"
        "• /check — Forza un controllo immediato dei prezzi\n"
        "• /history `ID` — Storico prezzi per tutti i voli di una rotta\n"
        "• /cancel — Annulla l'operazione in corso\n\n"
        f"_Il bot controlla automaticamente alle {_fmt_check_times()} ({CHECK_TIMEZONE})._",
        parse_mode="Markdown",
    )


# ── /add — flusso guidato ──────────────────────────────────────────────────────

async def cmd_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not authorized(update):
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text(
        "✈️ *Aggiunta nuova rotta — Passo 1 di 5*\n\n"
        "Inserisci il codice IATA dell'aeroporto di *partenza*\n"
        "_(3 lettere maiuscole, es. `MXP`, `FCO`, `NAP`)_\n\n"
        "_Usa /cancel in qualsiasi momento per annullare._",
        parse_mode="Markdown",
    )
    return ORIGIN


async def step_origin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    origin = update.message.text.upper().strip()
    if not validate_iata(origin):
        await update.message.reply_text(
            "❌ Codice non valido. Devono essere esattamente 3 lettere _(es. MXP, FCO, NAP)_.\n"
            "Riprova:",
            parse_mode="Markdown",
        )
        return ORIGIN
    context.user_data["origin"] = origin
    await update.message.reply_text(
        f"✅ Partenza: *{origin}*\n\n"
        "✈️ *Passo 2 di 5 — Aeroporto di destinazione*\n\n"
        "Inserisci il codice IATA di *destinazione*\n"
        "_(es. `GRU`, `EZE`, `JFK`, `BKK`)_",
        parse_mode="Markdown",
    )
    return DESTINATION


async def step_destination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    destination = update.message.text.upper().strip()
    if not validate_iata(destination):
        await update.message.reply_text(
            "❌ Codice non valido. Devono essere esattamente 3 lettere _(es. GRU, JFK, BKK)_.\n"
            "Riprova:",
            parse_mode="Markdown",
        )
        return DESTINATION
    if destination == context.user_data["origin"]:
        await update.message.reply_text(
            "❌ Destinazione uguale alla partenza. Inserisci un aeroporto diverso:"
        )
        return DESTINATION
    context.user_data["destination"] = destination
    await update.message.reply_text(
        f"✅ Destinazione: *{destination}*\n\n"
        "📅 *Passo 3 di 5 — Data di partenza*\n\n"
        "Inserisci la data in formato `YYYY-MM-DD`\n"
        "_(es. `2026-11-15`)_",
        parse_mode="Markdown",
    )
    return DEPARTURE


async def step_departure(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    date_str = update.message.text.strip()
    if not validate_date(date_str):
        await update.message.reply_text(
            "❌ Data non valida o già passata.\n"
            "Inserisci una data futura in formato `YYYY-MM-DD` _(es. `2026-11-15`)_:",
            parse_mode="Markdown",
        )
        return DEPARTURE
    context.user_data["departure_date"] = date_str
    await update.message.reply_text(
        f"✅ Partenza il *{date_str}*\n\n"
        "🔄 *Passo 4 di 5 — Tipo di volo*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✈️  Solo andata",      callback_data="oneway"),
            InlineKeyboardButton("🔄  Andata e ritorno", callback_data="roundtrip"),
        ]]),
    )
    return RETURN_TYPE


async def step_return_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "oneway":
        context.user_data["return_date"] = None
        await query.edit_message_text("✅ Solo andata ✈️")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "🔀 *Passo 5 di 5 — Scali massimi accettati*\n\n"
                "Scegli il numero massimo di scali per questa tratta:"
            ),
            parse_mode="Markdown",
            reply_markup=_stops_keyboard(),
        )
        return MAX_STOPS
    await query.edit_message_text(
        "✅ Andata e ritorno 🔄\n\n"
        "📅 *Passo 4b di 5 — Data di ritorno*\n\n"
        "Inserisci la data in formato `YYYY-MM-DD`\n"
        "_(es. `2026-11-30`)_",
        parse_mode="Markdown",
    )
    return RETURN_DATE


async def step_return_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    date_str  = update.message.text.strip()
    departure = context.user_data["departure_date"]
    if not validate_return_date(departure, date_str):
        await update.message.reply_text(
            f"❌ Data non valida o non successiva alla partenza _{departure}_.\n"
            "Inserisci in formato `YYYY-MM-DD`:",
            parse_mode="Markdown",
        )
        return RETURN_DATE
    context.user_data["return_date"] = date_str
    await update.message.reply_text(
        f"✅ Ritorno il *{date_str}*\n\n"
        "🔀 *Passo 5 di 5 — Scali massimi accettati*\n\n"
        "Scegli il numero massimo di scali per questa tratta:",
        parse_mode="Markdown",
        reply_markup=_stops_keyboard(),
    )
    return MAX_STOPS


async def step_max_stops(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    stops_map   = {"stops_0": 0,                "stops_1": 1,              "stops_any": None}
    stops_label = {"stops_0": "Solo diretto ✈️", "stops_1": "Max 1 scalo ↔️", "stops_any": "Qualsiasi 🌐"}
    max_stops   = stops_map[query.data]
    data        = context.user_data

    with get_session() as session:
        route = Route(
            origin=data["origin"],
            destination=data["destination"],
            departure_date=data["departure_date"],
            return_date=data.get("return_date"),
            max_stops=max_stops,
        )
        session.add(route)
        session.commit()
        session.refresh(route)
        route_id = route.id

    date_info = (
        f"{data['departure_date']} → {data['return_date']}"
        if data.get("return_date")
        else f"{data['departure_date']} (solo andata)"
    )
    await query.edit_message_text(
        f"✅ *Rotta aggiunta con ID {route_id}*\n\n"
        f"✈️  {data['origin']} → {data['destination']}\n"
        f"📅  {date_info}\n"
        f"🔀  Scali: {stops_label[query.data]}\n\n"
        f"Il bot monitorerà i *3 voli più economici* per questa rotta.\n"
        f"_Prossimi check automatici: {_fmt_check_times()} ({CHECK_TIMEZONE})_",
        parse_mode="Markdown",
    )
    logger.info(
        f"Nuova rotta {route_id}: {data['origin']}→{data['destination']} "
        f"il {data['departure_date']}, max_stops={max_stops}"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not authorized(update):
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Aggiunta rotta annullata.\n"
        "Usa /add per ricominciare quando vuoi."
    )
    return ConversationHandler.END


# ── /list ──────────────────────────────────────────────────────────────────────

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return

    with get_session() as session:
        routes = session.query(Route).filter(Route.is_active == True).all()
        if not routes:
            await update.message.reply_text(
                "Nessuna rotta attiva. Usa /add per iniziare a monitorare."
            )
            return

        stops_label = {0: "Solo diretto ✈️", 1: "Max 1 scalo ↔️", None: "Qualsiasi 🌐"}
        lines = ["*Rotte monitorate:*\n"]

        for r in routes:
            ret_info   = f" → {r.return_date}" if r.return_date else " (solo andata)"
            stops_info = stops_label.get(r.max_stops, f"Max {r.max_stops} scali")
            lines.append(
                f"*ID {r.id}* — {r.origin} → {r.destination}\n"
                f"  📅 {r.departure_date}{ret_info}\n"
                f"  🔀 {stops_info}"
            )

            monitored = (
                session.query(MonitoredFlight)
                .filter(
                    MonitoredFlight.route_id == r.id,
                    MonitoredFlight.is_active == True,
                )
                .order_by(MonitoredFlight.base_price.asc())
                .all()
            )

            if not monitored:
                lines.append("  ⏳ In attesa del primo check...\n")
                continue

            lines.append("  *Voli monitorati:*")
            for i, mf in enumerate(monitored, 1):
                last_check = (
                    session.query(FlightPriceCheck)
                    .filter(FlightPriceCheck.monitored_flight_id == mf.id)
                    .order_by(FlightPriceCheck.checked_at.desc())
                    .first()
                )
                airline_str  = mf.airline or "Sconosciuta"
                duration_str = _fmt_duration(mf.duration_minutes)

                if last_check:
                    change_pct = ((mf.base_price - last_check.price) / mf.base_price) * 100
                    trend      = f"📉 -{change_pct:.1f}%" if change_pct > 0 else f"📈 +{abs(change_pct):.1f}%"
                    price_info = f"Base: €{mf.base_price:.0f} | Ora: €{last_check.price:.0f} {trend}"
                else:
                    price_info = f"Base: €{mf.base_price:.0f} | N/D"

                lines.append(
                    f"  {i}. ✈️ {airline_str} — {price_info} | ⏱️ {duration_str}"
                )
            lines.append("")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /remove ────────────────────────────────────────────────────────────────────

async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    args = context.args or []
    if not args or not args[0].isdigit():
        await update.message.reply_text("❌ Uso: /remove ID  (es. /remove 3)")
        return

    route_id = int(args[0])
    with get_session() as session:
        route = session.query(Route).filter(
            Route.id == route_id, Route.is_active == True
        ).first()
        if not route:
            await update.message.reply_text(f"❌ Nessuna rotta attiva con ID {route_id}.")
            return
        route.is_active = False
        session.commit()
        await update.message.reply_text(
            f"✅ Rotta {route_id} ({route.origin}→{route.destination}) disattivata."
        )
        logger.info(f"Rotta {route_id} disattivata.")


# ── /check ─────────────────────────────────────────────────────────────────────

async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    await update.message.reply_text("🔍 Avvio controllo immediato per tutte le rotte...")
    await run_price_checks(context.application.bot)
    await update.message.reply_text("✅ Controllo completato.")


# ── /history ───────────────────────────────────────────────────────────────────

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    args = context.args or []
    if not args or not args[0].isdigit():
        await update.message.reply_text("❌ Uso: /history ID  (es. /history 3)")
        return

    route_id = int(args[0])
    with get_session() as session:
        route = session.query(Route).filter(Route.id == route_id).first()
        if not route:
            await update.message.reply_text(f"❌ Nessuna rotta con ID {route_id}.")
            return

        monitored = (
            session.query(MonitoredFlight)
            .filter(
                MonitoredFlight.route_id == route_id,
                MonitoredFlight.is_active == True,
            )
            .order_by(MonitoredFlight.base_price.asc())
            .all()
        )

        if not monitored:
            await update.message.reply_text(
                f"ℹ️ Nessun volo ancora monitorato per la rotta {route_id}.\n"
                f"_Prossimi check automatici: {_fmt_check_times()} ({CHECK_TIMEZONE})_",
                parse_mode="Markdown",
            )
            return

        lines = [
            f"*Storico prezzi — {route.origin} → {route.destination} (ID {route_id})*\n"
        ]
        for mf in monitored:
            airline_str  = mf.airline or "Sconosciuta"
            duration_str = _fmt_duration(mf.duration_minutes)
            lines.append(
                f"\n✈️ *{airline_str}* — Base: €{mf.base_price:.0f} | ⏱️ {duration_str}"
            )
            checks = (
                session.query(FlightPriceCheck)
                .filter(FlightPriceCheck.monitored_flight_id == mf.id)
                .order_by(FlightPriceCheck.checked_at.desc())
                .limit(10)
                .all()
            )
            if not checks:
                lines.append("  _Nessuna rilevazione ancora_")
            else:
                for c in checks:
                    lines.append(
                        f"  • {c.checked_at.strftime('%Y-%m-%d %H:%M')} — €{c.price:.0f}"
                    )

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /cancel globale ─────────────────────────────────────────────────────────────

async def cmd_cancel_global(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not authorized(update):
        return
    await update.message.reply_text("ℹ️ Nessuna operazione in corso da annullare.")


# ── Callback: proposta nuovo volo più economico ────────────────────────────────

async def handle_proposal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Gestisce la risposta ai bottoni della notifica "nuovo volo più economico".
    Pattern callback_data:
        prop_rep:<id>  →  Sostituisci il volo più costoso con il nuovo
        prop_add:<id>  →  Aggiungi il nuovo senza rimuovere nulla
        prop_ign:<id>  →  Ignora
    """
    query = update.callback_query
    await query.answer()

    if not authorized(update):
        await query.edit_message_text("⛔ Non autorizzato.")
        return

    parts = query.data.split(":")
    if len(parts) != 2 or not parts[1].isdigit():
        await query.edit_message_text("⚠️ Dati di callback non validi.")
        return

    action      = parts[0]
    proposal_id = int(parts[1])

    with get_session() as session:
        proposal = (
            session.query(PendingFlightProposal)
            .filter(
                PendingFlightProposal.id == proposal_id,
                PendingFlightProposal.resolved == False,
            )
            .first()
        )
        if not proposal:
            await query.edit_message_text(
                "⚠️ Questa proposta non è più disponibile (già risolta o scaduta)."
            )
            return

        new_airline  = proposal.airline or "Sconosciuta"
        new_price    = proposal.price
        new_currency = proposal.currency

        if action == "prop_rep":
            old_mf      = session.query(MonitoredFlight).filter(
                MonitoredFlight.id == proposal.replace_flight_id
            ).first()
            old_airline = old_mf.airline if old_mf else "Sconosciuta"
            if old_mf:
                old_mf.is_active = False
            session.add(MonitoredFlight(
                route_id=proposal.route_id,
                airline=proposal.airline,
                base_price=proposal.price,
                base_price_currency=proposal.currency,
                duration_minutes=proposal.duration_minutes,
                deep_link=proposal.deep_link,
                is_active=True,
            ))
            proposal.resolved = True
            session.commit()
            await query.edit_message_text(
                f"✅ *Volo aggiornato*\n\n"
                f"♻️ _{old_airline}_ rimosso dal monitoraggio.\n"
                f"✈️ *{new_airline}* ({new_currency}{new_price:.0f}) ora monitorato.",
                parse_mode="Markdown",
            )
            logger.info(
                f"Proposta {proposal_id}: sostituito '{old_airline}' con '{new_airline}' "
                f"(rotta {proposal.route_id})"
            )

        elif action == "prop_add":
            session.add(MonitoredFlight(
                route_id=proposal.route_id,
                airline=proposal.airline,
                base_price=proposal.price,
                base_price_currency=proposal.currency,
                duration_minutes=proposal.duration_minutes,
                deep_link=proposal.deep_link,
                is_active=True,
            ))
            proposal.resolved = True
            session.commit()
            await query.edit_message_text(
                f"✅ *Volo aggiunto*\n\n"
                f"➕ *{new_airline}* ({new_currency}{new_price:.0f}) "
                f"aggiunto al monitoraggio.\n"
                f"_Ora hai {_count_monitored(session, proposal.route_id)} voli monitorati "
                f"per questa rotta._",
                parse_mode="Markdown",
            )
            logger.info(
                f"Proposta {proposal_id}: aggiunto '{new_airline}' "
                f"(rotta {proposal.route_id})"
            )

        else:  # prop_ign
            proposal.resolved = True
            session.commit()
            await query.edit_message_text(
                f"❌ Proposta ignorata.\n_{new_airline}_ non aggiunto al monitoraggio."
            )
            logger.info(f"Proposta {proposal_id}: ignorata (rotta {proposal.route_id})")


def _count_monitored(session, route_id: int) -> int:
    """Helper: conta i voli attivi monitorati per una rotta."""
    return (
        session.query(MonitoredFlight)
        .filter(
            MonitoredFlight.route_id == route_id,
            MonitoredFlight.is_active == True,
        )
        .count()
    )


# ── Application builder ────────────────────────────────────────────────────────

async def _post_init(app: Application) -> None:
    """Popola il menu comandi Telegram."""
    await app.bot.set_my_commands([
        BotCommand("start",   "Mostra i comandi disponibili"),
        BotCommand("add",     "Aggiungi una nuova rotta (guidato)"),
        BotCommand("list",    "Mostra le rotte e i voli monitorati"),
        BotCommand("remove",  "Disattiva una rotta per ID"),
        BotCommand("check",   "Forza un controllo immediato"),
        BotCommand("history", "Storico prezzi per una rotta"),
        BotCommand("cancel",  "Annulla l'operazione in corso"),
    ])


def build_application() -> Application:
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )

    conv_add = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add_start)],
        states={
            ORIGIN:      [MessageHandler(filters.TEXT & ~filters.COMMAND, step_origin)],
            DESTINATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_destination)],
            DEPARTURE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, step_departure)],
            RETURN_TYPE: [CallbackQueryHandler(step_return_type, pattern="^(oneway|roundtrip)$")],
            RETURN_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, step_return_date)],
            MAX_STOPS:   [CallbackQueryHandler(step_max_stops, pattern="^stops_")],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(conv_add)
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("list",    cmd_list))
    app.add_handler(CommandHandler("remove",  cmd_remove))
    app.add_handler(CommandHandler("check",   cmd_check))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("cancel",  cmd_cancel_global))
    app.add_handler(CallbackQueryHandler(
        handle_proposal_callback,
        pattern=r"^prop_(rep|add|ign):\d+$",
    ))

    return app
