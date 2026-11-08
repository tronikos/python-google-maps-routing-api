"""Tests for the Google Maps Routes API client."""

from __future__ import annotations

import datetime
import logging
import os
import re
from http import HTTPStatus
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from google_maps_routing_api import (
    GoogleMapsRoutingApi,
    GoogleMapsRoutingApiAuthError,
    GoogleMapsRoutingApiConnectionError,
    GoogleMapsRoutingApiConnectionTimeoutError,
    GoogleMapsRoutingApiResponseError,
    LatLng,
    Location,
    RoutingPreference,
    TrafficModel,
    TransitRoutingPreference,
    TransitTravelMode,
    TravelMode,
    Units,
    Waypoint,
)
from google_maps_routing_api.api import DEFAULT_FIELD_MASK

from .conftest import (
    API_KEY,
    DESTINATION_ADDRESS,
    ORIGIN_ADDRESS,
    ORIGIN_LAT,
    ORIGIN_LNG,
    REFERRER,
    MockServer,
    load_fixture,
)


async def test_compute_routes(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test computing a driving route between two addresses."""
    mock_server.add_response(load_fixture("compute_routes_drive"))

    result = await api.async_compute_routes(origin=ORIGIN_ADDRESS, destination=DESTINATION_ADDRESS)

    route = result.routes[0]
    assert route.duration == datetime.timedelta(seconds=581)
    assert route.static_duration == datetime.timedelta(seconds=516)
    assert route.distance_meters == 3197
    assert route.localized_values is not None
    assert route.localized_values.duration is not None
    assert route.localized_values.duration.text == "9 mins"
    leg = route.legs[0]
    assert leg.distance_meters == 3197
    assert leg.duration == datetime.timedelta(seconds=581)
    assert leg.static_duration == datetime.timedelta(seconds=516)
    assert leg.localized_values is not None
    assert leg.localized_values.duration is not None
    assert leg.localized_values.duration.text == "10 mins"
    assert leg.steps
    assert leg.steps[0].navigation_instruction is not None
    assert leg.steps[0].navigation_instruction.instructions
    assert mock_server.requests[0].path == "/directions/v2:computeRoutes"


async def test_compute_routes_metric(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test computing a route with metric units."""
    mock_server.add_response(load_fixture("compute_routes_drive_metric"))

    result = await api.async_compute_routes(origin=ORIGIN_ADDRESS, destination=DESTINATION_ADDRESS, units=Units.METRIC)

    route = result.routes[0]
    assert route.duration == datetime.timedelta(seconds=4256)
    assert route.static_duration == datetime.timedelta(seconds=2940)
    assert route.distance_meters == 60892
    assert route.localized_values is None
    leg = route.legs[0]
    assert leg.localized_values is not None
    assert leg.localized_values.distance is not None
    assert leg.localized_values.distance.text == "60.9 km"
    assert len(leg.steps) == 10


async def test_compute_routes_transit(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test computing transit routes, which come back without steps."""
    mock_server.add_response(load_fixture("compute_routes_transit"))

    result = await api.async_compute_routes(
        origin=ORIGIN_ADDRESS,
        destination=DESTINATION_ADDRESS,
        travel_mode=TravelMode.TRANSIT,
        compute_alternative_routes=True,
    )

    assert len(result.routes) == 6
    assert result.routes[0].duration == datetime.timedelta(seconds=3120)
    assert result.routes[0].distance_meters == 57866
    assert result.routes[1].duration == datetime.timedelta(seconds=3600)
    assert result.routes[0].legs[0].steps == []


async def test_request_headers(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test the API key, field mask, referrer and content type headers are sent."""
    mock_server.add_response(load_fixture("compute_routes_drive"))

    await api.async_compute_routes(origin=ORIGIN_ADDRESS, destination=DESTINATION_ADDRESS)

    request = mock_server.requests[0]
    assert request.headers["X-Goog-Api-Key"] == API_KEY
    assert request.headers["X-Goog-FieldMask"] == DEFAULT_FIELD_MASK
    assert request.headers[aiohttp.hdrs.REFERER] == REFERRER
    assert request.headers[aiohttp.hdrs.CONTENT_TYPE] == "application/json"
    assert request.json == {
        "origin": {"address": ORIGIN_ADDRESS},
        "destination": {"address": DESTINATION_ADDRESS},
        "travelMode": "DRIVE",
    }


async def test_no_referrer_header_when_unset(session: aiohttp.ClientSession, mock_server: MockServer) -> None:
    """Test the Referer header is omitted when no referrer is configured."""
    api = GoogleMapsRoutingApi(session=session, api_key=API_KEY)
    mock_server.add_response(load_fixture("compute_routes_drive"))

    await api.async_compute_routes(origin=ORIGIN_ADDRESS, destination=DESTINATION_ADDRESS)

    assert aiohttp.hdrs.REFERER not in mock_server.requests[0].headers


async def test_custom_field_mask(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test a custom field mask is sent, as a string or as a list."""
    mock_server.add_response(load_fixture("compute_routes_drive"))
    mock_server.add_response(load_fixture("compute_routes_drive"))

    await api.async_compute_routes(origin=ORIGIN_ADDRESS, destination=DESTINATION_ADDRESS, field_mask="routes.duration")
    await api.async_compute_routes(
        origin=ORIGIN_ADDRESS,
        destination=DESTINATION_ADDRESS,
        field_mask=["routes.duration", "routes.distanceMeters"],
    )

    first, second = mock_server.requests
    assert first.headers["X-Goog-FieldMask"] == "routes.duration"
    assert second.headers["X-Goog-FieldMask"] == "routes.duration,routes.distanceMeters"


async def test_waypoint_forms(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test waypoints given as coordinates, addresses, models or dicts."""
    for _ in range(4):
        mock_server.add_response(load_fixture("compute_routes_drive"))

    await api.async_compute_routes(origin=f"{ORIGIN_LAT},{ORIGIN_LNG}", destination=DESTINATION_ADDRESS)
    await api.async_compute_routes(origin=ORIGIN_ADDRESS, destination=DESTINATION_ADDRESS)
    await api.async_compute_routes(
        origin=Waypoint(location=Location(lat_lng=LatLng(latitude=ORIGIN_LAT, longitude=ORIGIN_LNG))),
        destination=DESTINATION_ADDRESS,
    )
    origin_dict = {"address": ORIGIN_ADDRESS}
    await api.async_compute_routes(origin=origin_dict, destination=DESTINATION_ADDRESS)

    lat_lng, address, model, passthrough = (request.json["origin"] for request in mock_server.requests)
    assert lat_lng == {"location": {"latLng": {"latitude": ORIGIN_LAT, "longitude": ORIGIN_LNG}}}
    assert address == {"address": ORIGIN_ADDRESS}
    assert model == {"location": {"latLng": {"latitude": ORIGIN_LAT, "longitude": ORIGIN_LNG}}}
    assert passthrough == {"address": ORIGIN_ADDRESS}


async def test_waypoint_with_whitespace(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test a "lat,lng" string with surrounding whitespace is still parsed as coordinates."""
    mock_server.add_response(load_fixture("compute_routes_drive"))

    await api.async_compute_routes(origin=f" {ORIGIN_LAT} , {ORIGIN_LNG} ", destination=DESTINATION_ADDRESS)

    assert mock_server.requests[0].json["origin"] == {
        "location": {"latLng": {"latitude": ORIGIN_LAT, "longitude": ORIGIN_LNG}}
    }


async def test_invalid_waypoint_type(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test an unsupported waypoint type raises a TypeError."""
    origin: Any = 42

    with pytest.raises(TypeError, match="Unsupported waypoint type"):
        await api.async_compute_routes(origin=origin, destination=DESTINATION_ADDRESS)


async def test_travel_options(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test travel options are serialized into the request payload."""
    mock_server.add_response(load_fixture("compute_routes_drive"))

    await api.async_compute_routes(
        origin=ORIGIN_ADDRESS,
        destination=DESTINATION_ADDRESS,
        travel_mode=TravelMode.TRANSIT,
        routing_preference=RoutingPreference.TRAFFIC_AWARE,
        departure_time=datetime.datetime(2026, 10, 22, 8, 0, tzinfo=datetime.UTC),
        arrival_time=datetime.datetime(2026, 10, 22, 9, 30, tzinfo=datetime.UTC),
        language_code="en",
        units=Units.IMPERIAL,
        avoid_tolls=True,
        avoid_highways=True,
        avoid_ferries=True,
        avoid_indoor=True,
        traffic_model=TrafficModel.BEST_GUESS,
        transit_routing_preference=TransitRoutingPreference.FEWER_TRANSFERS,
        allowed_travel_modes=[TransitTravelMode.BUS, TransitTravelMode.SUBWAY],
        compute_alternative_routes=True,
    )

    assert mock_server.requests[0].json == {
        "origin": {"address": ORIGIN_ADDRESS},
        "destination": {"address": DESTINATION_ADDRESS},
        "travelMode": "TRANSIT",
        "routingPreference": "TRAFFIC_AWARE",
        "departureTime": "2026-10-22T08:00:00+00:00",
        "arrivalTime": "2026-10-22T09:30:00+00:00",
        "languageCode": "en",
        "units": "IMPERIAL",
        "routeModifiers": {
            "avoidTolls": True,
            "avoidHighways": True,
            "avoidFerries": True,
            "avoidIndoor": True,
        },
        "trafficModel": "BEST_GUESS",
        "transitPreferences": {
            "routingPreference": "FEWER_TRANSFERS",
            "allowedTravelModes": ["BUS", "SUBWAY"],
        },
        "computeAlternativeRoutes": True,
    }


async def test_travel_options_as_strings(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test travel options given as plain strings are passed through to the payload."""
    mock_server.add_response(load_fixture("compute_routes_transit"))

    await api.async_compute_routes(
        origin=ORIGIN_ADDRESS,
        destination=DESTINATION_ADDRESS,
        travel_mode="TRANSIT",
        routing_preference="TRAFFIC_AWARE_OPTIMAL",
        units="METRIC",
        traffic_model="OPTIMISTIC",
        transit_routing_preference="LESS_WALKING",
        allowed_travel_modes=["RAIL"],
    )

    assert mock_server.requests[0].json == {
        "origin": {"address": ORIGIN_ADDRESS},
        "destination": {"address": DESTINATION_ADDRESS},
        "travelMode": "TRANSIT",
        "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
        "units": "METRIC",
        "trafficModel": "OPTIMISTIC",
        "transitPreferences": {
            "routingPreference": "LESS_WALKING",
            "allowedTravelModes": ["RAIL"],
        },
    }


async def test_transit_routing_preference_only(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test transit preferences with only a routing preference."""
    mock_server.add_response(load_fixture("compute_routes_transit"))

    await api.async_compute_routes(
        origin=ORIGIN_ADDRESS,
        destination=DESTINATION_ADDRESS,
        travel_mode=TravelMode.TRANSIT,
        transit_routing_preference=TransitRoutingPreference.LESS_WALKING,
    )

    assert mock_server.requests[0].json == {
        "origin": {"address": ORIGIN_ADDRESS},
        "destination": {"address": DESTINATION_ADDRESS},
        "travelMode": "TRANSIT",
        "transitPreferences": {"routingPreference": "LESS_WALKING"},
    }


async def test_transit_allowed_travel_modes_only(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test transit preferences with only allowed travel modes."""
    mock_server.add_response(load_fixture("compute_routes_transit"))

    await api.async_compute_routes(
        origin=ORIGIN_ADDRESS,
        destination=DESTINATION_ADDRESS,
        travel_mode=TravelMode.TRANSIT,
        allowed_travel_modes=[TransitTravelMode.RAIL],
    )

    assert mock_server.requests[0].json == {
        "origin": {"address": ORIGIN_ADDRESS},
        "destination": {"address": DESTINATION_ADDRESS},
        "travelMode": "TRANSIT",
        "transitPreferences": {"allowedTravelModes": ["RAIL"]},
    }


async def test_no_route(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test the empty response body returned when no route is found."""
    mock_server.add_response({})

    result = await api.async_compute_routes(origin="New York, NY", destination="London, UK")

    assert result.routes == []


@pytest.mark.parametrize(
    ("status", "payload", "expected_error", "expected_message", "expected_reason", "expected_api_status"),
    [
        (
            HTTPStatus.UNAUTHORIZED,
            {"error": {"message": "Unauthenticated.", "status": "UNAUTHENTICATED"}},
            GoogleMapsRoutingApiAuthError,
            "Unauthenticated.",
            None,
            "UNAUTHENTICATED",
        ),
        (
            HTTPStatus.FORBIDDEN,
            load_fixture("error_referrer_blocked"),
            GoogleMapsRoutingApiAuthError,
            "Requests from referer <empty> are blocked.",
            "API_KEY_HTTP_REFERRER_BLOCKED",
            "PERMISSION_DENIED",
        ),
        (
            HTTPStatus.BAD_REQUEST,
            load_fixture("error_invalid_key"),
            GoogleMapsRoutingApiAuthError,
            "API key not valid. Please pass a valid API key.",
            "API_KEY_INVALID",
            "INVALID_ARGUMENT",
        ),
        (
            HTTPStatus.BAD_REQUEST,
            load_fixture("error_bad_field_mask"),
            GoogleMapsRoutingApiResponseError,
            "Request contains an invalid argument.",
            None,
            "INVALID_ARGUMENT",
        ),
        (
            HTTPStatus.TOO_MANY_REQUESTS,
            {
                "error": {
                    "message": "Quota exceeded.",
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [{"reason": "RATE_LIMIT_EXCEEDED"}],
                }
            },
            GoogleMapsRoutingApiResponseError,
            "Quota exceeded.",
            "RATE_LIMIT_EXCEEDED",
            "RESOURCE_EXHAUSTED",
        ),
        (
            HTTPStatus.INTERNAL_SERVER_ERROR,
            {},
            GoogleMapsRoutingApiResponseError,
            "Unknown API error",
            None,
            None,
        ),
    ],
)
async def test_error_responses(
    api: GoogleMapsRoutingApi,
    mock_server: MockServer,
    status: HTTPStatus,
    payload: dict[str, Any],
    expected_error: type[GoogleMapsRoutingApiAuthError | GoogleMapsRoutingApiResponseError],
    expected_message: str,
    expected_reason: str | None,
    expected_api_status: str | None,
) -> None:
    """Test HTTP error responses are mapped to the right exception."""
    mock_server.add_response(payload, status=status)

    with pytest.raises(expected_error) as exc_info:
        await api.async_compute_routes(origin=ORIGIN_ADDRESS, destination=DESTINATION_ADDRESS)

    assert str(exc_info.value) == expected_message
    error = exc_info.value
    assert isinstance(error, (GoogleMapsRoutingApiAuthError, GoogleMapsRoutingApiResponseError))
    assert error.reason == expected_reason
    assert error.status == expected_api_status


@pytest.mark.parametrize(
    "payload",
    [
        {"error": {"code": 504, "message": "Deadline expired.", "status": "DEADLINE_EXCEEDED"}},
        "<html>504 Gateway Timeout</html>",
    ],
)
async def test_gateway_timeout_is_a_timeout_error(api: GoogleMapsRoutingApi, mock_server: MockServer, payload: Any) -> None:
    """Test an HTTP 504 is reported as a timeout, like a client side timeout."""
    mock_server.add_response(payload, status=HTTPStatus.GATEWAY_TIMEOUT)

    with pytest.raises(GoogleMapsRoutingApiConnectionTimeoutError, match="Timeout") as exc_info:
        await api.async_compute_routes(origin=ORIGIN_ADDRESS, destination=DESTINATION_ADDRESS)

    assert isinstance(exc_info.value, TimeoutError)


async def test_empty_success_body_has_no_routes(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test a successful response without a JSON object doesn't crash."""
    mock_server.add_response(None)

    response = await api.async_compute_routes(origin=ORIGIN_ADDRESS, destination=DESTINATION_ADDRESS)

    assert response.routes == []


async def test_empty_error_body(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test an error response without a JSON object is still mapped to an exception."""
    mock_server.add_response(None, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    with pytest.raises(GoogleMapsRoutingApiResponseError, match="Unknown API error"):
        await api.async_compute_routes(origin=ORIGIN_ADDRESS, destination=DESTINATION_ADDRESS)


async def test_non_json_response(api: GoogleMapsRoutingApi, mock_server: MockServer) -> None:
    """Test a non-JSON body is reported as a connection error."""
    mock_server.add_response("<html>502 Bad Gateway</html>", status=HTTPStatus.BAD_GATEWAY)

    with pytest.raises(GoogleMapsRoutingApiConnectionError) as exc_info:
        await api.async_compute_routes(origin=ORIGIN_ADDRESS, destination=DESTINATION_ADDRESS)

    # Callers log these errors, and tracebacks render chained exceptions with str()
    assert API_KEY not in str(exc_info.value)
    assert exc_info.value.__cause__ is not None
    assert API_KEY not in str(exc_info.value.__cause__)


@pytest.mark.parametrize(
    ("raised", "expected_error", "expected_message"),
    [
        (TimeoutError(), GoogleMapsRoutingApiConnectionTimeoutError, "Timeout"),
        (aiohttp.ClientError("boom"), GoogleMapsRoutingApiConnectionError, "boom"),
    ],
)
async def test_connection_errors(
    api: GoogleMapsRoutingApi,
    monkeypatch: pytest.MonkeyPatch,
    raised: Exception,
    expected_error: type[Exception],
    expected_message: str,
) -> None:
    """Test transport failures are reported as connection errors."""

    def raise_error(*args: Any, **kwargs: Any) -> Any:
        raise raised

    monkeypatch.setattr(api.session, "post", raise_error)

    with pytest.raises(expected_error, match=re.escape(expected_message)) as exc_info:
        await api.async_compute_routes(origin=ORIGIN_ADDRESS, destination=DESTINATION_ADDRESS)

    if isinstance(raised, TimeoutError):
        assert isinstance(exc_info.value, TimeoutError)


async def test_custom_timeout(session: aiohttp.ClientSession) -> None:
    """Test the timeout is configurable."""
    api = GoogleMapsRoutingApi(session=session, api_key=API_KEY, timeout=30)

    assert api.timeout.total == 30


async def test_api_key_is_not_logged(
    api: GoogleMapsRoutingApi,
    mock_server: MockServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test the API key never makes it into the debug logs."""
    mock_server.add_response(load_fixture("compute_routes_drive"))

    with caplog.at_level(logging.DEBUG, logger="google_maps_routing_api"):
        await api.async_compute_routes(origin=ORIGIN_ADDRESS, destination=DESTINATION_ADDRESS)

    assert "computeRoutes" in caplog.text
    assert API_KEY not in caplog.text


def _load_dotenv() -> dict[str, str]:
    """Load credentials from .env or environment variables."""
    env: dict[str, str] = {}
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.is_file():
        for raw_line in env_file.read_text().splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    for key in ("GOOGLE_API_KEY", "GOOGLE_REFERRER"):
        if val := os.environ.get(key):
            env[key] = val
    return env


@pytest.mark.network
async def test_live_compute_routes(session: aiohttp.ClientSession) -> None:
    """Test computing routes against the live Google Maps Routes API using .env credentials."""
    env = _load_dotenv()
    api_key = env.get("GOOGLE_API_KEY")
    if not api_key:
        pytest.skip("GOOGLE_API_KEY not set in .env or environment")
    client = GoogleMapsRoutingApi(
        session=session,
        api_key=api_key,
        referrer=env.get("GOOGLE_REFERRER"),
    )
    response = await client.async_compute_routes(
        origin=ORIGIN_ADDRESS,
        destination=DESTINATION_ADDRESS,
    )
    assert len(response.routes) >= 1
    route = response.routes[0]
    assert route.duration is not None
    assert route.duration.total_seconds() > 0
    assert route.distance_meters is not None
    assert route.distance_meters > 0
