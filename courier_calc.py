"""PH courier rate calculator — J&T, LBC, Ninja Van, JRS, 2GO.

Approximate published rates (Metro Manila origin → various destinations).
Rates change — verify with the courier before quoting customers. These are
ballparks to budget your COGS, not for invoicing.

Last updated: late 2025. Refresh data periodically.
"""
from __future__ import annotations

# Zone definitions
ZONES = {
    "Metro Manila":   ["Metro Manila", "NCR"],
    "Luzon":          ["Cavite", "Laguna", "Batangas", "Rizal", "Bulacan",
                       "Pampanga", "Baguio", "Pangasinan", "La Union", "Ilocos",
                       "Bicol", "Nueva Ecija"],
    "Visayas":        ["Cebu", "Iloilo", "Bacolod", "Tacloban / Leyte",
                       "Dumaguete", "Aklan / Boracay"],
    "Mindanao":       ["Davao", "Cagayan de Oro", "Zamboanga",
                       "General Santos", "Butuan", "Iligan", "Cotabato"],
}

# Weight bands (kg) → rate per zone (PHP)
# Source: averaged J&T standard / LBC PUMP / Ninja Van COD rates
RATE_TABLE = {
    # (courier, zone, weight_max_kg) -> price_php
    "J&T Express": {
        "Metro Manila":  {0.5: 75, 1: 85, 3: 100, 5: 135, 10: 215},
        "Luzon":         {0.5: 110, 1: 125, 3: 165, 5: 220, 10: 340},
        "Visayas":       {0.5: 130, 1: 165, 3: 230, 5: 305, 10: 510},
        "Mindanao":      {0.5: 150, 1: 195, 3: 270, 5: 360, 10: 600},
    },
    "LBC": {
        "Metro Manila":  {0.5: 90, 1: 110, 3: 140, 5: 175, 10: 280},
        "Luzon":         {0.5: 130, 1: 155, 3: 200, 5: 270, 10: 410},
        "Visayas":       {0.5: 160, 1: 200, 3: 280, 5: 365, 10: 600},
        "Mindanao":      {0.5: 185, 1: 235, 3: 320, 5: 420, 10: 700},
    },
    "Ninja Van": {
        "Metro Manila":  {0.5: 70, 1: 80, 3: 95, 5: 130, 10: 200},
        "Luzon":         {0.5: 100, 1: 115, 3: 155, 5: 210, 10: 320},
        "Visayas":       {0.5: 120, 1: 155, 3: 220, 5: 290, 10: 485},
        "Mindanao":      {0.5: 140, 1: 185, 3: 260, 5: 345, 10: 575},
    },
    "JRS Express": {
        "Metro Manila":  {0.5: 100, 1: 120, 3: 160, 5: 200, 10: 310},
        "Luzon":         {0.5: 140, 1: 170, 3: 225, 5: 295, 10: 445},
        "Visayas":       {0.5: 175, 1: 220, 3: 305, 5: 400, 10: 660},
        "Mindanao":      {0.5: 200, 1: 255, 3: 350, 5: 460, 10: 765},
    },
}

# COD fee (charged to seller) — percentage of order value
COD_FEES = {
    "J&T Express": 0.025,  # 2.5%
    "LBC":         0.030,
    "Ninja Van":   0.025,
    "JRS Express": 0.030,
}


def get_zone(location: str | None) -> str | None:
    """Map a PH location label (e.g. 'Cebu') to a courier zone."""
    if not location:
        return None
    loc_low = location.lower()
    for zone, members in ZONES.items():
        for m in members:
            if m.lower() in loc_low or loc_low in m.lower():
                return zone
    # PH-wide / unknown: assume Luzon as conservative default
    if "ph" in loc_low or "philippines" in loc_low:
        return "Luzon"
    return None


def quote(weight_kg: float, destination: str,
          courier: str | None = None) -> list[dict]:
    """Quote shipping rates for one package.

    Args:
        weight_kg: package weight in kg
        destination: PH location (e.g. "Cebu", "Metro Manila", "Davao")
        courier: specific courier to quote, or None for all

    Returns:
        List of {courier, zone, weight_kg, price_php} sorted by price ascending.
        Empty list if destination can't be mapped to a zone.
    """
    zone = get_zone(destination)
    if not zone:
        return []

    out: list[dict] = []
    couriers = [courier] if courier and courier in RATE_TABLE else list(RATE_TABLE.keys())
    for c in couriers:
        bands = RATE_TABLE[c].get(zone, {})
        if not bands:
            continue
        # Find the smallest band that covers this weight
        price = None
        for band_kg in sorted(bands.keys()):
            if weight_kg <= band_kg:
                price = bands[band_kg]
                break
        # Above max band → use a per-kg overage estimate on top of the max
        if price is None:
            max_band = max(bands.keys())
            max_price = bands[max_band]
            overage_kg = weight_kg - max_band
            price = max_price + overage_kg * (max_price / max_band) * 0.6  # rough
        out.append({
            "courier": c,
            "zone": zone,
            "weight_kg": weight_kg,
            "price_php": round(price, 2),
        })

    out.sort(key=lambda x: x["price_php"])
    return out


def cod_fee(courier: str, order_value_php: float) -> float:
    """Calculate COD handling fee for an order value."""
    return round(order_value_php * COD_FEES.get(courier, 0.025), 2)


def all_destinations() -> list[str]:
    """List of all supported destinations (for UI dropdown)."""
    return sorted({m for members in ZONES.values() for m in members})


def all_couriers() -> list[str]:
    return sorted(RATE_TABLE.keys())
