import logging
from datetime import datetime, timedelta, date
from telegram import Bot
from db import (
    get_session, Route, MonitoredFlight,
    FlightPriceCheck, AlertLog, PendingFlightProposal,
)
from api_client import get_top_flights
from alerter import send_flight_price_drop_alert, send_new_cheaper_flight_alert
from config import ALERT_COOLDOWN_HOURS

logger = logging.getLogger(__name__)


async def run_price_checks(bot: Bot) -> None:
    """
    Funzione principale chiamata dallo scheduler ogni CHECK_INTERVAL_HOURS ore.
    Prima disattiva le rotte scadute, poi itera su quelle ancora attive.
    Ogni rotta viene gestita in modo indipendente: un errore non blocca le altre.
    """
    with get_session() as session:

        # ── Cleanup automatico rotte scadute ──────────────────────────────
        today_str = date.today().isoformat()
        expired = (
            session.query(Route)
            .filter(Route.is_active == True, Route.departure_date < today_str)
            .all()
        )
        for r in expired:
            r.is_active = False
            logger.info(
                f"Rotta {r.id} ({r.origin}→{r.destination} il {r.departure_date}) "
                f"disattivata automaticamente: data di partenza passata."
            )
        if expired:
            session.commit()

        # ── Check rotte attive ────────────────────────────────────────────
        active_routes = session.query(Route).filter(Route.is_active == True).all()
        logger.info(
            f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC] "
            f"Avvio check: {len(active_routes)} rotte attive "
            f"({len(expired)} scadute e disattivate)"
        )
        for route in active_routes:
            try:
                await _check_single_route(bot, session, route)
            except Exception as e:
                logger.error(f"Errore sul check della rotta {route.id}: {e}", exc_info=True)


async def _check_single_route(bot: Bot, session, route: Route) -> None:
    """
    Gestisce il ciclo di vita completo di un singolo check in 3 fasi:

    FASE 1 – Inizializzazione: al primo check non ci sono voli monitorati,
             vengono salvati i top-3 come base di riferimento.

    FASE 2 – Verifica cali: per ogni volo monitorato confronta il prezzo
             corrente con il base_price; invia alert se calo >= 20%.
             Include auto-calibrazione del base_price dopo 7 giorni.

    FASE 3 – Nuovi voli: cerca tra tutti i voli disponibili uno non ancora
             monitorato che costi meno del più costoso tra i monitorati;
             se trovato, notifica con bottoni interattivi (sostituisci/aggiungi/ignora).
    """
    # Recupera fino a 10 voli per avere margine di trovare alternative più economiche
    all_flights = await get_top_flights(
        route.origin, route.destination,
        route.departure_date, route.return_date,
        route.max_stops, n=10,
    )
    if not all_flights:
        logger.warning(f"Nessun dato di prezzo per la rotta {route.id}")
        return

    all_flights.sort(key=lambda f: f["price"])   # garanzia: ordine crescente di prezzo

    # Carica i voli monitorati attivi per questa rotta
    monitored = (
        session.query(MonitoredFlight)
        .filter(MonitoredFlight.route_id == route.id, MonitoredFlight.is_active == True)
        .order_by(MonitoredFlight.base_price.asc())
        .all()
    )

    # ── FASE 1: Inizializzazione ──────────────────────────────────────────
    if not monitored:
        top3 = all_flights[:3]
        for f in top3:
            session.add(MonitoredFlight(
                route_id=route.id,
                airline=f["airline"],
                base_price=f["price"],
                base_price_currency=f["currency"],
                duration_minutes=f.get("duration_minutes"),
                deep_link=f["deep_link"],
            ))
        session.commit()
        logger.info(
            f"Rotta {route.id}: {len(top3)} voli monitorati inizializzati "
            f"({', '.join(f['airline'] for f in top3)})"
        )
        return

    # ── FASE 2: Verifica cali di prezzo ──────────────────────────────────
    # Costruisce indice airline → miglior prezzo corrente tra i risultati API
    current_by_airline: dict[str, dict] = {}
    for f in all_flights:
        a = f["airline"]
        if a not in current_by_airline or f["price"] < current_by_airline[a]["price"]:
            current_by_airline[a] = f

    for mf in monitored:
        current = current_by_airline.get(mf.airline)
        if current is None:
            logger.info(f"Volo monitorato {mf.id} ({mf.airline}): non presente nei risultati correnti")
            continue

        current_price = current["price"]

        # Salva sempre la rilevazione
        session.add(FlightPriceCheck(
            monitored_flight_id=mf.id,
            price=current_price,
            currency=current["currency"],
        ))
        session.commit()

        # Auto-calibrazione dopo 7 giorni: abbassa base_price se storicamente è calato
        days_monitored = (datetime.utcnow() - mf.created_at).days
        if days_monitored >= 7:
            historical_min = (
                session.query(FlightPriceCheck)
                .filter(FlightPriceCheck.monitored_flight_id == mf.id)
                .order_by(FlightPriceCheck.price.asc())
                .first()
            )
            if historical_min and historical_min.price < mf.base_price:
                logger.info(
                    f"Volo {mf.id} ({mf.airline}): auto-calibrazione "
                    f"€{mf.base_price:.2f} → €{historical_min.price:.2f}"
                )
                mf.base_price = historical_min.price
                session.commit()

        # Controlla calo >= 20%
        threshold = mf.base_price * 0.80
        if current_price > threshold:
            logger.info(
                f"Volo {mf.id} ({mf.airline}): €{current_price:.0f} — "
                f"nessun calo (soglia €{threshold:.0f})"
            )
            continue

        # Controlla cooldown anti-spam
        cooldown_start = datetime.utcnow() - timedelta(hours=ALERT_COOLDOWN_HOURS)
        recent_drop = (
            session.query(AlertLog)
            .filter(
                AlertLog.monitored_flight_id == mf.id,
                AlertLog.sent_at >= cooldown_start,
                AlertLog.alert_type == "price_drop",
            )
            .first()
        )
        if recent_drop:
            logger.info(f"Volo {mf.id} ({mf.airline}): calo rilevato ma in cooldown")
            continue

        # Invia alert e registra
        await send_flight_price_drop_alert(
            bot, route, mf,
            current_price, current["currency"],
            current["airline"], current["deep_link"],
        )
        session.add(AlertLog(
            route_id=route.id,
            monitored_flight_id=mf.id,
            alert_type="price_drop",
        ))
        session.commit()
        logger.info(f"Volo {mf.id} ({mf.airline}): alert price_drop inviato")

    # ── FASE 3: Cerca nuovi voli più economici non ancora monitorati ──────
    # Non procedere se c'è già una proposta aperta non risolta
    existing_proposal = (
        session.query(PendingFlightProposal)
        .filter(
            PendingFlightProposal.route_id == route.id,
            PendingFlightProposal.resolved == False,
        )
        .first()
    )
    if existing_proposal:
        logger.info(f"Rotta {route.id}: proposta in attesa di risposta — skip ricerca nuovi voli")
        return

    # Ricarica i monitorati: i base_price potrebbero essere stati auto-calibrati
    monitored = (
        session.query(MonitoredFlight)
        .filter(MonitoredFlight.route_id == route.id, MonitoredFlight.is_active == True)
        .all()
    )
    if not monitored:
        return

    monitored_airlines = {mf.airline for mf in monitored}
    most_expensive_mf  = max(monitored, key=lambda m: m.base_price)

    for flight in all_flights:
        if flight["airline"] in monitored_airlines:
            continue
        if flight["price"] >= most_expensive_mf.base_price:
            break   # lista ordinata: nessun volo successivo sarà più economico

        # Trovato un volo più economico — controlla cooldown per new_cheaper
        cooldown_start = datetime.utcnow() - timedelta(hours=ALERT_COOLDOWN_HOURS)
        recent_new = (
            session.query(AlertLog)
            .filter(
                AlertLog.route_id == route.id,
                AlertLog.sent_at >= cooldown_start,
                AlertLog.alert_type == "new_cheaper",
            )
            .first()
        )
        if recent_new:
            logger.info(f"Rotta {route.id}: nuovo volo trovato ma in cooldown per new_cheaper")
            break

        # Crea proposta nel DB e notifica utente con bottoni interattivi
        proposal = PendingFlightProposal(
            route_id=route.id,
            replace_flight_id=most_expensive_mf.id,
            airline=flight["airline"],
            price=flight["price"],
            currency=flight["currency"],
            duration_minutes=flight.get("duration_minutes"),
            deep_link=flight["deep_link"],
        )
        session.add(proposal)
        session.commit()

        await send_new_cheaper_flight_alert(bot, route, most_expensive_mf, flight, proposal.id)
        session.add(AlertLog(route_id=route.id, alert_type="new_cheaper"))
        session.commit()
        logger.info(
            f"Rotta {route.id}: nuovo volo {flight['airline']} a €{flight['price']:.0f} "
            f"→ proposta {proposal.id} inviata"
        )
        break   # una sola proposta alla volta, attendi risposta utente