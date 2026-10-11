"""Pressure-altitude to MSL correction for ADS-B barometric altitude.

ADS-B/Mode S `alt_baro` ("baro" or "pressure altitude") is the aircraft's height
above the standard datum plane defined by setting 29.92 inHg into the altimeter,
NOT its height above mean sea level. On a day when the actual sea-level pressure
differs from the 29.92 standard, alt_baro reads low (high pressure) or high (low
pressure) relative to true MSL altitude by a predictable amount: roughly 1,000 ft
of altimeter error per 1 inHg of pressure difference (a standard aviation rule of
thumb -- each 0.01 inHg below 29.92 "standard" corresponds to about 10 ft of
altitude the gauge under-reads relative to true MSL, and vice versa above 29.92).
Track A must apply this correction before comparing a helicopter's ADS-B altitude
to the MSL-referenced protected-volume ceilings/floors in this `geo/` package
(e.g. the 1,300 ft MSL Hudson Class B floor) -- otherwise, on a high-pressure day
like 2026-10-10 (KLGA altimeter ~30.3-30.5 inHg most of the day), every helicopter
appears several hundred feet lower than it actually is, which would mask real
Class-B-floor and approach-protected-volume incursions.
"""

STANDARD_ALTIMETER_INHG = 29.92
FT_PER_INHG = 1000.0


def baro_to_msl(alt_baro_ft: float, altimeter_inhg: float) -> float:
    """Correct a barometric (29.92-referenced) altitude to approximate MSL altitude.

    alt_msl ~= alt_baro + (altimeter_setting - 29.92) * 1000

    This is the standard linear approximation (not a full ISA non-linear
    correction); it is accurate to within a few tens of feet over the small
    altimeter-setting deviations seen in day-to-day NYC-area weather and is
    the correction Track A should apply to every ADS-B `alt_baro` sample
    before testing it against the MSL ceilings/floors in this package.
    """
    return alt_baro_ft + (altimeter_inhg - STANDARD_ALTIMETER_INHG) * FT_PER_INHG
