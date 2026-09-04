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


# What a model costs is asked in two places -- the Pilot's own cost tracking
# and the agent envelope -- and each used to carry its own table. They
# disagreed: the same model was priced at 5.00/25.00 in one and 15.00/75.00 in
# the other, a factor of three, so the answer depended on which file the reader
# opened (review 2, section E). The registry in llm.models is the table; this
# reads it by the API model name, which is what a turn reports back.
#
# Cache reads bill at a share of the input rate. Measured on a research turn:
# the last call reported ONE input token and 3031 output, everything else read
# from cache -- pricing input alone reports a cost about an order of magnitude
# too low, which is the kind of wrong number that gets believed because it is
# pleasant.
CACHE_READ_SHARE = 0.10


# (input, output) US dollars per million tokens, by the API model name -- the
# name a turn reports back, not the short key the dropdown uses. THIS is the
# table; llm.models fills its own cost fields from it, so a price is written
# down once. A model that is not here reports no cost rather than a guessed
# one, which is why the two entries that only one of the old tables carried
# (claude-opus-4-7, -4-8) are absent: their numbers came from the table that
# disagreed, and a plausible number nobody checked is worse than none.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-6": (15.00, 75.00),
}


def rate_for(model_name: str | None) -> tuple[float, float] | None:
    """(input, output) US dollars per million tokens, or None if unknown.

    None rather than a guess: a model nobody priced reports no cost, which is
    honest, where a plausible number is not.
    """
    return PRICES.get(str(model_name or "").strip().lower())


def usd_last_call(model_name: str | None, *, tokens_in: int | None,
                  tokens_out: int | None = 0, tokens_cache_read: int | None = 0
                  ) -> float | None:
    """What one model call cost in US dollars, or None if it cannot be priced."""
    rate = rate_for(model_name)
    if rate is None or tokens_in is None:
        return None
    return ((tokens_in / 1e6) * rate[0]
            + ((tokens_cache_read or 0) / 1e6) * rate[0] * CACHE_READ_SHARE
            + ((tokens_out or 0) / 1e6) * rate[1])


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
    return f"USD→EUR {usd_eur():.5f} (as of {RATE_DATE})"
