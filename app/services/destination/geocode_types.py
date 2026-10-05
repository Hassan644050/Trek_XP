from dataclasses import dataclass


@dataclass
class GeoResult:
    name: str
    latitude: float
    longitude: float
    country: str | None
    country_code: str | None
    timezone: str | None
    # Which service resolved the place, reported in the response's sources.
    source: str = "open_meteo_geocoding"
