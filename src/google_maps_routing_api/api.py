"""API for Google Maps Routes."""

from __future__ import annotations

import logging
import re
from enum import Enum
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import aiohttp

from .exceptions import (
    GoogleMapsRoutingApiAuthError,
    GoogleMapsRoutingApiConnectionError,
    GoogleMapsRoutingApiConnectionTimeoutError,
    GoogleMapsRoutingApiResponseError,
)
from .model import (
    ComputeRoutesResponse,
    RoutingPreference,
    TrafficModel,
    TransitRoutingPreference,
    TransitTravelMode,
    TravelMode,
    Units,
    Waypoint,
)

if TYPE_CHECKING:
    import datetime as dt

_LOGGER = logging.getLogger(__name__)

_BASE_URL = "https://routes.googleapis.com"
_ENDPOINT = "directions/v2:computeRoutes"
DEFAULT_FIELD_MASK = (
    "routes.duration,routes.distanceMeters,routes.staticDuration,routes.localizedValues,"
    "routes.legs.distanceMeters,routes.legs.duration,routes.legs.staticDuration,"
    "routes.legs.localizedValues,routes.legs.steps.navigationInstruction.instructions"
)
_LAT_LNG_PATTERN = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*$")


def _enum_value(value: Enum | str) -> str:
    """Return the string value the API expects for an enum member or a plain string."""
    return value.value if isinstance(value, Enum) else value


class GoogleMapsRoutingApi:
    """Class to interact with the Google Maps Routes API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        referrer: str | None = None,
        timeout: int = 10,
    ) -> None:
        """Initialize the Google Maps Routes API client."""
        self.session = session
        self.api_key = api_key
        self.referrer = referrer
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    @staticmethod
    def _waypoint_to_dict(waypoint: object) -> dict[str, Any]:
        """Convert a waypoint into the JSON object the API expects.

        Waypoints can be given as a Waypoint model, a "lat,lng" string, an address
        string, or an already-built dict which is passed through unchanged.
        """
        if isinstance(waypoint, Waypoint):
            return waypoint.to_dict()
        if isinstance(waypoint, str):
            if _LAT_LNG_PATTERN.match(waypoint):
                lat, lng = waypoint.split(",")
                return {"location": {"latLng": {"latitude": float(lat), "longitude": float(lng)}}}
            return {"address": waypoint}
        if isinstance(waypoint, dict):
            return waypoint
        raise TypeError(f"Unsupported waypoint type: {type(waypoint).__name__}")

    @staticmethod
    def _build_payload(
        origin: Waypoint | str | dict[str, Any],
        destination: Waypoint | str | dict[str, Any],
        travel_mode: TravelMode | str,
        routing_preference: RoutingPreference | str | None,
        departure_time: dt.datetime | None,
        arrival_time: dt.datetime | None,
        language_code: str | None,
        units: Units | str | None,
        avoid_tolls: bool,
        avoid_highways: bool,
        avoid_ferries: bool,
        avoid_indoor: bool,
        traffic_model: TrafficModel | str | None,
        transit_routing_preference: TransitRoutingPreference | str | None,
        allowed_travel_modes: list[TransitTravelMode | str] | None,
        compute_alternative_routes: bool,
    ) -> dict[str, Any]:
        """Build the JSON payload for a computeRoutes request."""
        payload: dict[str, Any] = {
            "origin": GoogleMapsRoutingApi._waypoint_to_dict(origin),
            "destination": GoogleMapsRoutingApi._waypoint_to_dict(destination),
            "travelMode": _enum_value(travel_mode),
        }
        if routing_preference is not None:
            payload["routingPreference"] = _enum_value(routing_preference)
        if departure_time is not None:
            payload["departureTime"] = departure_time.isoformat()
        if arrival_time is not None:
            payload["arrivalTime"] = arrival_time.isoformat()
        if language_code is not None:
            payload["languageCode"] = language_code
        if units is not None:
            payload["units"] = _enum_value(units)
        if avoid_tolls or avoid_highways or avoid_ferries or avoid_indoor:
            payload["routeModifiers"] = {
                "avoidTolls": avoid_tolls,
                "avoidHighways": avoid_highways,
                "avoidFerries": avoid_ferries,
                "avoidIndoor": avoid_indoor,
            }
        if traffic_model is not None:
            payload["trafficModel"] = _enum_value(traffic_model)
        if transit_routing_preference is not None or allowed_travel_modes:
            transit_preferences: dict[str, Any] = {}
            if transit_routing_preference is not None:
                transit_preferences["routingPreference"] = _enum_value(transit_routing_preference)
            if allowed_travel_modes:
                transit_preferences["allowedTravelModes"] = [_enum_value(mode) for mode in allowed_travel_modes]
            payload["transitPreferences"] = transit_preferences
        if compute_alternative_routes:
            payload["computeAlternativeRoutes"] = True
        return payload

    async def async_compute_routes(
        self,
        *,
        origin: Waypoint | str | dict[str, Any],
        destination: Waypoint | str | dict[str, Any],
        travel_mode: TravelMode | str = TravelMode.DRIVE,
        routing_preference: RoutingPreference | str | None = None,
        departure_time: dt.datetime | None = None,
        arrival_time: dt.datetime | None = None,
        language_code: str | None = None,
        units: Units | str | None = None,
        avoid_tolls: bool = False,
        avoid_highways: bool = False,
        avoid_ferries: bool = False,
        avoid_indoor: bool = False,
        traffic_model: TrafficModel | str | None = None,
        transit_routing_preference: TransitRoutingPreference | str | None = None,
        allowed_travel_modes: list[TransitTravelMode | str] | None = None,
        compute_alternative_routes: bool = False,
        field_mask: str | list[str] | None = None,
    ) -> ComputeRoutesResponse:
        """Compute routes using the Google Routes API.

        See https://developers.google.com/maps/documentation/routes/reference/rest/v2/top-level/Console/computeRoutes

        departure_time and arrival_time must be timezone-aware datetimes and are
        serialized as RFC 3339 timestamps.
        """
        payload = self._build_payload(
            origin,
            destination,
            travel_mode,
            routing_preference,
            departure_time,
            arrival_time,
            language_code,
            units,
            avoid_tolls,
            avoid_highways,
            avoid_ferries,
            avoid_indoor,
            traffic_model,
            transit_routing_preference,
            allowed_travel_modes,
            compute_alternative_routes,
        )

        mask = ",".join(field_mask) if isinstance(field_mask, list) else field_mask
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": mask or DEFAULT_FIELD_MASK,
        }
        if self.referrer:
            headers[aiohttp.hdrs.REFERER] = self.referrer

        url = f"{_BASE_URL}/{_ENDPOINT}"
        # The API key is only sent in a header, never in the payload, so it is safe to log.
        _LOGGER.debug("POST %s with payload: %s", url, payload)
        try:
            async with self.session.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            ) as resp:
                _LOGGER.debug("Got %s for %s", resp.status, url)
                status_code = resp.status
                body = None if status_code == HTTPStatus.GATEWAY_TIMEOUT else await resp.json()
        except TimeoutError as err:
            raise GoogleMapsRoutingApiConnectionTimeoutError("Timeout") from err
        except aiohttp.ClientError as err:
            raise GoogleMapsRoutingApiConnectionError(err) from err

        if status_code == HTTPStatus.GATEWAY_TIMEOUT:
            raise GoogleMapsRoutingApiConnectionTimeoutError("Timeout")
        res: dict[str, Any] = body if isinstance(body, dict) else {}
        if status_code != HTTPStatus.OK:
            error_data = res.get("error", {})
            error_msg = error_data.get("message", "Unknown API error")
            status = error_data.get("status")
            reason = next(
                (detail.get("reason") for detail in error_data.get("details", []) if detail.get("reason")),
                None,
            )
            if status_code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN) or reason == "API_KEY_INVALID":
                raise GoogleMapsRoutingApiAuthError(error_msg, status=status, reason=reason)
            raise GoogleMapsRoutingApiResponseError(error_msg, status=status, reason=reason)
        return ComputeRoutesResponse.from_dict(res)
