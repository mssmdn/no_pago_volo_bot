import asyncio
import logging
import aiohttp
from config import TRAVELPAYOUTS_TOKEN, SERPAPI_KEY

logger = logging.getLogger(__name__)

MAX_RETRIES  = 3
BASE_BACKOFF = 2   # secondi base per exponential backoff: 2s, 4s, 8s


# ── Utility ───────────────────────────────────────────────────────────────────

async def _fetch_with_backoff(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict,
    params: dict,
) -> dict | None:
    """GET con retry ed exponential backoff. Restituisce JSON o None dopo 3 fallimenti."""
    for attempt in range(MAX_RETRIES):
        try:
            async with session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status == 200:
                    return await response.json()
                logger.warning(f"API ha risposto {response.status} (tentativo {attempt + 1})")
        except aiohttp.ClientError as e:
            logger.warning(f"Errore di rete (tentativo {attempt + 1}): {e}")

        wait = BASE_BACKOFF ** (attempt + 1)
        logger.info(f"Riprovo tra {wait}s...")
        await asyncio.sleep(wait)

    return None


def _build_google_flights_url(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None,
) -> str:
    """Costruisce un link diretto a Google Flights per la rotta richiesta."""
    if return_date:
        fragment = (
            f"{origin}.{destination}.{departure_date}"
            f"*{destination}.{origin}.{return_date}"
            ";c:EUR;e:1"
        )
    else:
        fragment = f"{origin}.{destination}.{departure_date};c:EUR;e:1;t:f"

    return f"https://www.google.com/travel/flights?hl=it#flt={fragment}"


# ── Punto di ingresso pubblico ─────────────────────────────────────────────────

async def get_top_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None,
    max_stops: int | None = None,
    n: int = 10,
) -> list[dict] | None:
    """
    Restituisce fino a n voli ordinati per prezzo crescente.
    Ogni elemento del risultato contiene:
        {"price", "currency", "airline", "duration_minutes", "deep_link"}
    duration_minutes è None quando non disponibile (es. da Aviasales).
    Prima tenta Aviasales, poi SerpAPI come fallback.
    """
    results = await _fetch_aviasales(origin, destination, departure_date, return_date, max_stops, n)
    if results is None:
        logger.warning("Aviasales: nessun dato → passo a SerpAPI Google Flights...")
        results = await _fetch_serpapi(origin, destination, departure_date, return_date, max_stops, n)
    return results


# ── API primaria: Travelpayouts / Aviasales Data API ──────────────────────────

async def _fetch_aviasales(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None,
    max_stops: int | None,
    n: int,
) -> list[dict] | None:
    """
    Aviasales /v1/prices/cheap — cache aggiornata ogni 7 giorni.
    Restituisce una lista di voli ordinati per prezzo crescente.
    Nota: questa API non fornisce la durata del volo (duration_minutes=None).
    """
    params = {
        "origin":             origin,
        "destination":        destination,
        "depart_date":        departure_date,
        "token":              TRAVELPAYOUTS_TOKEN,
        "currency":           "EUR",
        "show_to_affiliates": "false",
    }
    if return_date:
        params["return_date"] = return_date

    async with aiohttp.ClientSession() as session:
        data = await _fetch_with_backoff(
            session,
            "https://api.travelpayouts.com/v1/prices/cheap",
            {},
            params,
        )

    if not data or not data.get("success"):
        return None

    dest_data = data.get("data", {}).get(destination, {})
    if not dest_data:
        logger.info(f"Aviasales: nessun prezzo in cache per {origin}→{destination} il {departure_date}")
        return None

    if max_stops is not None:
        dest_data = {
            k: v for k, v in dest_data.items()
            if k.isdigit() and int(k) <= max_stops
        }
        if not dest_data:
            logger.info(
                f"Aviasales: nessun volo con max {max_stops} scalo/i "
                f"per {origin}→{destination} — passo al fallback"
            )
            return None

    deep_link     = _build_google_flights_url(origin, destination, departure_date, return_date)
    sorted_flights = sorted(dest_data.values(), key=lambda f: f.get("price", float("inf")))

    results = []
    for f in sorted_flights[:n]:
        price = f.get("price")
        if price is None:
            continue
        results.append({
            "price":            float(price),
            "currency":         "EUR",
            "airline":          f.get("airline", "Unknown"),
            "duration_minutes": None,   # non disponibile in questa API
            "deep_link":        deep_link,
        })
        logger.info(
            f"Aviasales: {origin}→{destination} il {departure_date} "
            f"= EUR {price:.0f} ({f.get('airline', '?')})"
        )

    return results if results else None


# ── API di fallback: SerpAPI Google Flights ────────────────────────────────────

async def _fetch_serpapi(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None,
    max_stops: int | None,
    n: int,
) -> list[dict] | None:
    """
    Fallback: SerpAPI Google Flights — 250 ricerche/mese gratuite.
    Restituisce voli con durata totale (total_duration in minuti) inclusa.
    """
    if not SERPAPI_KEY:
        logger.warning("SERPAPI_KEY non impostata: fallback non disponibile.")
        return None

    params = {
        "engine":        "google_flights",
        "departure_id":  origin,
        "arrival_id":    destination,
        "outbound_date": departure_date,
        "currency":      "EUR",
        "hl":            "it",
        "api_key":       SERPAPI_KEY,
        "sort_by":       "2",
        "type":          "2" if not return_date else "1",
    }
    if return_date:
        params["return_date"] = return_date
    if max_stops is not None:
        params["stops"] = str(max_stops)

    async with aiohttp.ClientSession() as session:
        data = await _fetch_with_backoff(session, "https://serpapi.com/search", {}, params)

    if not data:
        return None

    all_raw = data.get("best_flights", []) + data.get("other_flights", [])
    if not all_raw:
        logger.info(f"SerpAPI: nessun volo trovato per {origin}→{destination} il {departure_date}")
        return None

    deep_link   = _build_google_flights_url(origin, destination, departure_date, return_date)
    sorted_raw  = sorted(all_raw, key=lambda f: f.get("price", float("inf")))

    results = []
    for f in sorted_raw[:n]:
        price = f.get("price")
        if price is None:
            continue
        legs     = f.get("flights", [])
        airline  = legs[0].get("airline", "Unknown") if legs else "Unknown"
        duration = f.get("total_duration")   # int (minuti totali inclusi scali) o None
        results.append({
            "price":            float(price),
            "currency":         "EUR",
            "airline":          airline,
            "duration_minutes": duration,
            "deep_link":        deep_link,
        })
        logger.info(
            f"SerpAPI: {origin}→{destination} il {departure_date} "
            f"= EUR {price:.0f} ({airline}, {duration}min)"
        )

    return results if results else None