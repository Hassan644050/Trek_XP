import json
from functools import lru_cache
from pathlib import Path

from app.models.context import CountryInfo


PLUGS_PATH = Path(__file__).resolve().parents[2] / "data" / "plugs.json"


@lru_cache(maxsize=1)
def load_plug_data() -> dict:
    """Read the plug dataset once and keep it in memory.

    Local lookup rather than an API call: the data barely changes, so this
    costs nothing per request and has no failure mode of its own.
    """
    try:
        with PLUGS_PATH.open(encoding="utf-8") as handle:
            data = json.load(handle)

    except (OSError, ValueError):
        return {}

    return {
        code: entry
        for code, entry in data.items()
        if not code.startswith("_")
    }


def get_country_info(
    country_code: str | None,
    country_name: str | None = None,
) -> CountryInfo:
    entry = load_plug_data().get((country_code or "").upper())

    if not entry:
        return CountryInfo(
            country_name=country_name,
            country_code=country_code,
            available=False,
        )

    return CountryInfo(
        country_name=country_name,
        country_code=country_code,
        plug_types=entry.get("plug_types", []),
        voltage=entry.get("voltage"),
        frequency=entry.get("frequency"),
        available=True,
    )
