"""Coding fixture: contains a deliberate off-by-one bug.

`grid_points_below_limit` should return every reading strictly below the
limit, but the comparison includes equality, so a reading exactly at the
limit is wrongly reported as a breach. The tests below fail until it is fixed.
"""


def grid_points_below_limit(readings: dict[str, float], limit: float) -> list[str]:
    """Return the grid points whose measured thickness is below `limit`."""
    breaches = []
    for point, thickness in readings.items():
        if thickness <= limit:  # BUG: should be `<`
            breaches.append(point)
    return breaches


READINGS = {"G-01": 9.4, "G-05": 7.1, "G-06": 6.8, "G-09": 8.0}


def test_strictly_below_limit():
    assert grid_points_below_limit(READINGS, 8.0) == ["G-05", "G-06"]


def test_reading_exactly_at_limit_is_not_a_breach():
    assert "G-09" not in grid_points_below_limit(READINGS, 8.0)


def test_no_breaches_when_limit_is_low():
    assert grid_points_below_limit(READINGS, 6.0) == []
