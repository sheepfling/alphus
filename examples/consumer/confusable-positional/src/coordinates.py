from dataclasses import dataclass


def screen_point(x: float, y: float) -> tuple[float, float]:
    """The advisory reviews this short same-type positional interface."""
    return x, y


@dataclass(frozen=True)
class Latitude:
    degrees: float


@dataclass(frozen=True)
class Longitude:
    degrees: float


def geographic_point(latitude: Latitude, longitude: Longitude) -> tuple[float, float]:
    """Distinct domain types preserve the meaning of these two coordinates."""
    return latitude.degrees, longitude.degrees
