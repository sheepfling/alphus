import math
from typing import Protocol

import numpy as np
from geometry_types import Basis3, Frame, Vector3


class Angle(Protocol):
    radians: float


def ecef_delta_to_enu(
    dx: float, dy: float, dz: float, latitude: float, longitude: float
) -> tuple[float, float, float]:
    return (
        -math.sin(longitude) * dx + math.cos(longitude) * dy,
        -math.sin(latitude) * math.cos(longitude) * dx
        - math.sin(latitude) * math.sin(longitude) * dy
        + math.cos(latitude) * dz,
        math.cos(latitude) * math.cos(longitude) * dx
        + math.cos(latitude) * math.sin(longitude) * dy
        + math.sin(latitude) * dz,
    )


def ecef_to_ned_matrix(lat_rad: float, lon_rad: float) -> object:
    slat, clat = math.sin(lat_rad), math.cos(lat_rad)
    slon, clon = math.sin(lon_rad), math.cos(lon_rad)
    return np.array(
        [
            [-slat * clon, -slat * slon, clat],
            [-slon, clon, 0.0],
            [-clat * clon, -clat * slon, -slat],
        ]
    )


def geodetic_unit_vectors(longitude: Angle, latitude: Angle) -> object:
    cosine_latitude = math.cos(latitude.radians)
    sine_latitude = math.sin(latitude.radians)
    cosine_longitude = math.cos(longitude.radians)
    sine_longitude = math.sin(longitude.radians)
    first = Vector3(
        -sine_latitude * cosine_longitude,
        -sine_latitude * sine_longitude,
        cosine_latitude,
    )
    second = Vector3(-sine_longitude, cosine_longitude, 0.0)
    return Basis3(
        first,
        second,
        first.cross(second),
        parent_frame=Frame.ECFC,
        child_frame=Frame.GEODETIC_HORIZON,
    )
