"""Which countries the app has curated data for.

Each country lives in its own folder under app/data/countries/<code>/, with
an admin.json (divisions and districts), a destinations.json (the curated
spots, and the country's own name) and an optional catalog_seed.json. A new
country is added by dropping that folder in -- this registry discovers it,
and nothing here changes.

The active country for a single-country deployment is HOME_COUNTRY; the
data is keyed by country code throughout so more can run alongside it.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import PROJECT_ROOT, get_env_meta_info


COUNTRIES_DIR = PROJECT_ROOT / "app" / "data" / "countries"


@dataclass(frozen=True)
class Country:
    code: str  # ISO 3166-1 alpha-2, uppercased
    name: str
    directory: Path

    @property
    def admin_path(self) -> Path:
        return self.directory / "admin.json"

    @property
    def destinations_path(self) -> Path:
        return self.directory / "destinations.json"

    @property
    def catalog_seed_path(self) -> Path:
        return self.directory / "catalog_seed.json"


@lru_cache(maxsize=1)
def supported_countries() -> dict[str, Country]:
    """Every country with a data folder, keyed by uppercased code.

    A folder is only counted when its destinations.json names the country,
    so a half-built directory does not register as supported.
    """
    found: dict[str, Country] = {}

    if not COUNTRIES_DIR.is_dir():
        return found

    for directory in sorted(COUNTRIES_DIR.iterdir()):
        destinations = directory / "destinations.json"

        if not destinations.is_file():
            continue

        try:
            with destinations.open(encoding="utf-8") as handle:
                meta = json.load(handle).get("country", {})
        except (OSError, ValueError):
            continue

        code = str(meta.get("code", directory.name)).upper()
        name = meta.get("name")

        if not name:
            continue

        found[code] = Country(code=code, name=name, directory=directory)

    return found


def get_country(code: str | None) -> Country | None:
    if not code:
        return None

    return supported_countries().get(code.upper())


def is_supported(code: str | None) -> bool:
    return get_country(code) is not None


def home_country() -> Country:
    """The configured active country.

    Falls back to any one that exists if HOME_COUNTRY has no data, so a
    misconfigured code never leaves the app with no country at all.
    """
    countries = supported_countries()
    configured = get_env_meta_info().home_country.upper()

    if configured in countries:
        return countries[configured]

    # Deterministic fallback keeps behaviour predictable when misconfigured.
    return next(iter(sorted(countries.values(), key=lambda c: c.code)))
