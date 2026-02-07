"""RF Tactical Monitor - CoT XML Templates.

Build Cursor-on-Target (CoT) XML payloads.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional


def _format_time(dt: datetime) -> str:
    """Format datetime in CoT ISO-8601 UTC format."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _build_event(
    uid: str,
    cot_type: str,
    lat: float,
    lon: float,
    alt_m: float,
    remarks: Optional[str] = None,
    callsign: Optional[str] = None,
    course_deg: Optional[float] = None,
    speed_mps: Optional[float] = None,
) -> bytes:
    """Build a generic CoT event XML payload.

    Args:
        uid: Unique identifier for the event.
        cot_type: CoT type string.
        lat: Latitude in degrees.
        lon: Longitude in degrees.
        alt_m: Altitude in meters.
        remarks: Optional remarks string.
        callsign: Optional callsign string.
        course_deg: Optional course heading in degrees.
        speed_mps: Optional speed in meters per second.

    Returns:
        CoT XML payload as UTF-8 bytes.
    """
    now = datetime.now(timezone.utc)
    stale = now + timedelta(seconds=120)

    detail_parts = []
    if callsign:
        detail_parts.append(f"<contact callsign=\"{callsign}\"/>")
    if remarks:
        detail_parts.append(f"<remarks>{remarks}</remarks>")
    if course_deg is not None or speed_mps is not None:
        detail_parts.append(
            "<track "
            + (f"course=\"{course_deg:.1f}\" " if course_deg is not None else "")
            + (f"speed=\"{speed_mps:.1f}\"" if speed_mps is not None else "")
            + "/>")

    detail_xml = "".join(detail_parts)

    event_xml = (
        f"<event version=\"2.0\" uid=\"{uid}\" type=\"{cot_type}\" "
        f"time=\"{_format_time(now)}\" start=\"{_format_time(now)}\" "
        f"stale=\"{_format_time(stale)}\" how=\"m-g\">"
        f"<point lat=\"{lat:.6f}\" lon=\"{lon:.6f}\" hae=\"{alt_m:.1f}\" ce=\"50.0\" le=\"50.0\"/>"
        f"<detail>{detail_xml}</detail>"
        "</event>"
    )
    return event_xml.encode("utf-8")


def build_aircraft_cot(
    icao: str,
    callsign: Optional[str],
    lat: float,
    lon: float,
    alt_m: float,
    speed_mps: Optional[float],
    course_deg: Optional[float],
    military: bool = False,
) -> bytes:
    """Build CoT for aircraft.

    Args:
        icao: Aircraft ICAO hex string.
        callsign: Callsign if available.
        lat: Latitude in degrees.
        lon: Longitude in degrees.
        alt_m: Altitude in meters.
        speed_mps: Speed in meters per second.
        course_deg: Course in degrees.
        military: True for military aircraft type.

    Returns:
        CoT XML payload as UTF-8 bytes.
    """
    cot_type = "a-f-A-M-F" if military else "a-n-A-C-F"
    uid = f"aircraft-{icao.upper()}"
    return _build_event(
        uid=uid,
        cot_type=cot_type,
        lat=lat,
        lon=lon,
        alt_m=alt_m,
        callsign=callsign,
        course_deg=course_deg,
        speed_mps=speed_mps,
    )


def build_sensor_cot(
    uid: str,
    callsign: str,
    lat: float,
    lon: float,
    remarks: Optional[str] = None,
) -> bytes:
    """Build CoT for sensor point.

    Args:
        uid: Unique identifier for the sensor.
        callsign: Sensor callsign or label.
        lat: Latitude in degrees.
        lon: Longitude in degrees.
        remarks: Optional remarks.

    Returns:
        CoT XML payload as UTF-8 bytes.
    """
    return _build_event(
        uid=uid,
        cot_type="b-m-p-s-p-i",
        lat=lat,
        lon=lon,
        alt_m=0.0,
        callsign=callsign,
        remarks=remarks,
    )