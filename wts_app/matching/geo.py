"""Distance between voting places.

The Commission re-publishes coordinates for the same hall between elections and
they drift by a few metres, so voting places are matched by proximity rather
than by address text.
"""

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_METRES = 6_371_008.8

# What the results worker uses (election-results-manager, persistence.py).
# Kept the same so that Django and the worker agree about what counts as the
# same place.
DEFAULT_THRESHOLD_METRES = 50


def distance_metres(one, other):
    """Great-circle distance between two ``(latitude, longitude)`` pairs.

    Haversine rather than geodesic. Over tens of metres the two differ by well
    under a metre, which is far inside any threshold worth using, and this
    avoids a dependency for a single comparison.
    """
    lat1, lon1 = one
    lat2, lon2 = other
    if None in (lat1, lon1, lat2, lon2):
        return None

    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lon2 - lon1)

    a = (sin(delta_phi / 2) ** 2
         + cos(phi1) * cos(phi2) * sin(delta_lambda / 2) ** 2)
    return 2 * EARTH_RADIUS_METRES * asin(sqrt(a))


def nearest(point, places, threshold_metres=DEFAULT_THRESHOLD_METRES):
    """The closest place within ``threshold_metres``, and how far away it is.

    ``places`` is an iterable of objects carrying ``latitude`` and ``longitude``.
    Returns ``(place, metres)`` or ``(None, None)``.
    """
    best = None
    best_distance = None

    for place in places:
        metres = distance_metres(point, (place.latitude, place.longitude))
        if metres is None or metres > threshold_metres:
            continue
        if best_distance is None or metres < best_distance:
            best, best_distance = place, metres

    return best, best_distance
