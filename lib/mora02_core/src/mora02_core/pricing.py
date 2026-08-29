"""Money, in one place and in euros.

Upstream prices are quoted in US dollars - Anthropic per million tokens, the
image services per call - and the run log records ``cost_usd`` because that is
what the APIs report. Everything a human reads should be in euros, so the
conversion happens here rather than in every renderer, and it carries the date
of the rate it used.

A converted number that hides its rate pretends to a precision it does not have.
So the rate is named, dated, and overridable::

    MORA02_USD_EUR=0.87   # e.g. from your accountant's monthly rate

The default is the ECB reference rate of the day it was written down. It will
drift; that is expected, and the point of showing ``RATE_DATE`` next to any
figure derived from it.
"""

from __future__ import annotations

import os

# ECB reference rate, fetched 2026-08-29 for the quote of the previous banking day.
_DEFAULT_USD_EUR = 0.85889
RATE_DATE = "2026-08-28"


def usd_eur() -> float:
    """The rate in force: the environment's if set, else the dated default."""
    raw = os.environ.get("MORA02_USD_EUR")
    if not raw:
        return _DEFAULT_USD_EUR
    try:
        rate = float(raw)
    except ValueError:
        return _DEFAULT_USD_EUR
    return rate if rate > 0 else _DEFAULT_USD_EUR


def to_eur(usd: float | int | None) -> float | None:
    """Convert a dollar figure to euros. None stays None - no money is not zero money."""
    if usd is None:
        return None
    return round(float(usd) * usd_eur(), 6)


def eur_str(usd: float | int | None, *, places: int = 2) -> str:
    """A euro figure for display, or an em dash when there is nothing to show."""
    value = to_eur(usd)
    if value is None:
        return "—"
    # Small amounts would round to 0,00 € and read as free, which they are not.
    if 0 < value < 0.01:
        return "<0,01 €"
    return f"{value:.{places}f} €".replace(".", ",")


def rate_note() -> str:
    """One line naming the rate behind every converted figure."""
    return f"USD→EUR {usd_eur():.5f} (Stand {RATE_DATE})"
