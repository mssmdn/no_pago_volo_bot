import re
from datetime import date, datetime

# Regex per codici IATA aeroportuali: esattamente 3 lettere maiuscole
_IATA_RE = re.compile(r'^[A-Z]{3}$')

def validate_iata(code: str) -> bool:
    """Restituisce True se il codice è un IATA valido (es. MXP, GRU, EZE)."""
    return bool(_IATA_RE.match(code))

def validate_date(date_str: str) -> bool:
    """
    Restituisce True se la stringa è una data futura in formato YYYY-MM-DD.
    Una data di oggi è considerata non valida (il volo deve essere nel futuro).
    """
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        return d > date.today()
    except ValueError:
        return False

def validate_return_date(departure_str: str, return_str: str) -> bool:
    """
    Restituisce True se la data di ritorno è valida e successiva alla partenza.
    """
    try:
        dep = datetime.strptime(departure_str, "%Y-%m-%d").date()
        ret = datetime.strptime(return_str, "%Y-%m-%d").date()
        return ret > dep
    except ValueError:
        return False
