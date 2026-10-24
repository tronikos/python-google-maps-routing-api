"""Models for the Google Maps Routes API."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from enum import StrEnum

from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin

_LOGGER = logging.getLogger(__name__)


class ApiStrEnum(StrEnum):
    """A StrEnum that tolerates values the API added after this library was released.

    Google keeps adding values to these enums. Rather than failing to parse the whole
    response, an unknown value falls back to the first member, which is by convention
    the ``*_UNSPECIFIED`` one.
    """

    @classmethod
    def _missing_(cls, value: object) -> ApiStrEnum:
        """Fall back to the unspecified member for values not known to this library."""
        unspecified = next(iter(cls))
        _LOGGER.warning(
            "Unknown %s value %r returned by the API, falling back to %s. "
            "Please report this at https://github.com/tronikos/python-google-maps-routing-api/issues",
            cls.__name__,
            value,
            unspecified,
        )
        return unspecified


class BaseModel(DataClassJSONMixin):
    """Base class for all models."""

    class Config(BaseConfig):
        """Serialize using the camelCase names the API uses, so models round-trip."""

        serialize_by_alias = True
        allow_deserialization_not_by_alias = True
        omit_none = True


def _parse_duration(value: str) -> datetime.timedelta:
    """Parse a proto JSON Duration like "581s" or "581.500s"."""
    return datetime.timedelta(seconds=float(value.removesuffix("s")))


def _serialize_duration(value: datetime.timedelta) -> str:
    """Serialize a timedelta into the proto JSON Duration format, like "581s"."""
    seconds = value.total_seconds()
    if seconds.is_integer():
        return f"{int(seconds)}s"
    return f"{seconds}s"


class TravelMode(ApiStrEnum):
    """A travel mode.

    See https://developers.google.com/maps/documentation/routes/reference/rest/v2/top-level/Console/computeRoutes
    """

    TRAVEL_MODE_UNSPECIFIED = "TRAVEL_MODE_UNSPECIFIED"
    DRIVE = "DRIVE"
    BICYCLE = "BICYCLE"
    WALK = "WALK"
    TWO_WHEELER = "TWO_WHEELER"
    TRANSIT = "TRANSIT"


class RoutingPreference(ApiStrEnum):
    """An enum that specifies factors to take into consideration when calculating routes.

    See https://developers.google.com/maps/documentation/routes/reference/rest/v2/top-level/Console/computeRoutes
    """

    ROUTING_PREFERENCE_UNSPECIFIED = "ROUTING_PREFERENCE_UNSPECIFIED"
    TRAFFIC_UNAWARE = "TRAFFIC_UNAWARE"
    TRAFFIC_AWARE = "TRAFFIC_AWARE"
    TRAFFIC_AWARE_OPTIMAL = "TRAFFIC_AWARE_OPTIMAL"


class Units(ApiStrEnum):
    """A unit of measurement.

    See https://developers.google.com/maps/documentation/routes/reference/rest/v2/top-level/Console/computeRoutes
    """

    UNITS_UNSPECIFIED = "UNITS_UNSPECIFIED"
    METRIC = "METRIC"
    IMPERIAL = "IMPERIAL"


class TrafficModel(ApiStrEnum):
    """The assumptions to use when calculating time in traffic.

    See https://developers.google.com/maps/documentation/routes/reference/rest/v2/top-level/Console/computeRoutes
    """

    TRAFFIC_MODEL_UNSPECIFIED = "TRAFFIC_MODEL_UNSPECIFIED"
    BEST_GUESS = "BEST_GUESS"
    PESSIMISTIC = "PESSIMISTIC"
    OPTIMISTIC = "OPTIMISTIC"


class TransitRoutingPreference(ApiStrEnum):
    """Specifies preferences for transit routes.

    See https://developers.google.com/maps/documentation/routes/reference/rest/v2/top-level/Console/computeRoutes
    """

    TRANSIT_ROUTING_PREFERENCE_UNSPECIFIED = "TRANSIT_ROUTING_PREFERENCE_UNSPECIFIED"
    LESS_WALKING = "LESS_WALKING"
    FEWER_TRANSFERS = "FEWER_TRANSFERS"


class TransitTravelMode(ApiStrEnum):
    """A transit travel mode.

    See https://developers.google.com/maps/documentation/routes/reference/rest/v2/top-level/Console/computeRoutes
    """

    TRANSIT_TRAVEL_MODE_UNSPECIFIED = "TRANSIT_TRAVEL_MODE_UNSPECIFIED"
    BUS = "BUS"
    SUBWAY = "SUBWAY"
    TRAIN = "TRAIN"
    LIGHT_RAIL = "LIGHT_RAIL"
    RAIL = "RAIL"


@dataclass
class LocalizedText(BaseModel):
    """Localized variant of a text in a particular language."""

    text: str | None = None
    """Localized string in the language corresponding to languageCode below."""

    language_code: str | None = field(default=None, metadata={"alias": "languageCode"})
    """The text's BCP-47 language code, such as "en-US" or "sr-Latn"."""


@dataclass
class RouteLocalizedValues(BaseModel):
    """Text representations of certain properties of a route."""

    distance: LocalizedText | None = None
    """The travel distance represented as text."""

    duration: LocalizedText | None = None
    """The duration taking traffic conditions into consideration, represented as text."""

    static_duration: LocalizedText | None = field(default=None, metadata={"alias": "staticDuration"})
    """The duration without taking traffic conditions into consideration, represented as text."""


@dataclass
class RouteLegLocalizedValues(BaseModel):
    """Text representations of certain properties of a leg of a route."""

    distance: LocalizedText | None = None
    """The travel distance of the leg represented as text."""

    duration: LocalizedText | None = None
    """The duration of the leg taking traffic conditions into consideration, represented as text."""

    static_duration: LocalizedText | None = field(default=None, metadata={"alias": "staticDuration"})
    """The duration of the leg without taking traffic conditions into consideration, represented as text."""


@dataclass
class NavigationInstruction(BaseModel):
    """A navigation instruction, for example turn left or merge."""

    maneuver: str | None = None
    """The navigation maneuver, for example TURN_LEFT."""

    instructions: str | None = None
    """The instructions for navigating this step, rendered as a text string."""


@dataclass
class RouteLegStep(BaseModel):
    """A leg step, the smallest unit of a route."""

    navigation_instruction: NavigationInstruction | None = field(default=None, metadata={"alias": "navigationInstruction"})
    """The navigation instructions for this step."""


@dataclass
class RouteLeg(BaseModel):
    """A leg, the part of a route between one waypoint and the next."""

    distance_meters: int | None = field(default=None, metadata={"alias": "distanceMeters"})
    """The travel distance of the leg, in meters."""

    duration: datetime.timedelta | None = field(
        default=None, metadata={"deserialize": _parse_duration, "serialize": _serialize_duration}
    )
    """The length of time needed to travel the leg, taking traffic conditions into consideration."""

    static_duration: datetime.timedelta | None = field(
        default=None,
        metadata={"alias": "staticDuration", "deserialize": _parse_duration, "serialize": _serialize_duration},
    )
    """The duration of traveling the leg, calculated without taking traffic conditions into consideration."""

    localized_values: RouteLegLocalizedValues | None = field(default=None, metadata={"alias": "localizedValues"})
    """Text representations of certain properties of the leg."""

    steps: list[RouteLegStep] = field(default_factory=list)
    """The steps of the leg."""


@dataclass
class Route(BaseModel):
    """A route, consisting of a series of connected road segments joining an origin and a destination."""

    distance_meters: int | None = field(default=None, metadata={"alias": "distanceMeters"})
    """The travel distance of the route, in meters."""

    duration: datetime.timedelta | None = field(
        default=None, metadata={"deserialize": _parse_duration, "serialize": _serialize_duration}
    )
    """The length of time needed to travel the route, taking traffic conditions into consideration."""

    static_duration: datetime.timedelta | None = field(
        default=None,
        metadata={"alias": "staticDuration", "deserialize": _parse_duration, "serialize": _serialize_duration},
    )
    """The duration of traveling the route, calculated without taking traffic conditions into consideration."""

    localized_values: RouteLocalizedValues | None = field(default=None, metadata={"alias": "localizedValues"})
    """Text representations of certain properties of the route."""

    legs: list[RouteLeg] = field(default_factory=list)
    """The legs that make up the route."""


@dataclass
class ComputeRoutesResponse(BaseModel):
    """ComputeRoutes response message.

    See https://developers.google.com/maps/documentation/routes/reference/rest/v2/top-level/Console/computeRoutes
    """

    routes: list[Route] = field(default_factory=list)
    """The computed routes, up to three when computeAlternativeRoutes is set."""


@dataclass
class LatLng(BaseModel):
    """A latitude/longitude pair on the Earth, represented as degrees."""

    latitude: float
    """The latitude in degrees. It must be in the range [-90.0, +90.0]."""

    longitude: float
    """The longitude in degrees. It must be in the range [-180.0, +180.0]."""


@dataclass
class Location(BaseModel):
    """A point on the Earth, with an optional heading."""

    lat_lng: LatLng = field(metadata={"alias": "latLng"})
    """The latitude and longitude of the waypoint."""

    heading: int | None = None
    """The compass heading associated with the direction of the flow of traffic, in degrees."""


@dataclass
class Waypoint(BaseModel):
    """A waypoint, encapsulating a route waypoint.

    Only one of location, placeId and address is set.
    """

    location: Location | None = None
    """A point on the Earth, with an optional heading."""

    place_id: str | None = field(default=None, metadata={"alias": "placeId"})
    """The POI Place Id associated with the waypoint."""

    address: str | None = None
    """A human readable address or a plus code, for example "Mountain View, CA"."""
