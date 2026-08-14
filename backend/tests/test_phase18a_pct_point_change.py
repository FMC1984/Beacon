"""Phase 18A: percentage-point-change primitive. Two already-fractional
percentages (e.g. mention share, Share of Voice) must be compared as a POINT
difference, never the relative pct_change() ratio - 26% -> 32% is "+6 pts",
not "+23%"."""

from app.services.reporting import compare_points, pct_point_change


def test_point_change_is_the_difference_not_the_ratio():
    assert pct_point_change(0.32, 0.26) == 0.06
    assert pct_point_change(0.26, 0.32) == -0.06


def test_point_change_null_when_either_side_missing():
    assert pct_point_change(None, 0.26) is None
    assert pct_point_change(0.32, None) is None
    assert pct_point_change(None, None) is None


def test_point_change_zero_baseline_is_not_a_ratio_blowup():
    # previous=0 would make pct_change() undefined/null; point change is
    # still a well-defined difference.
    assert pct_point_change(0.10, 0.0) == 0.10


def test_compare_points_envelope_shape_and_direction():
    env = compare_points(0.32, 0.26)
    assert env == {
        "current": 0.32, "previous": 0.26, "point_change": 0.06, "direction": "up",
    }
    assert compare_points(0.26, 0.32)["direction"] == "down"
    assert compare_points(0.30, 0.30)["direction"] == "flat"
    assert compare_points(None, 0.30) == {
        "current": None, "previous": 0.30, "point_change": None, "direction": None,
    }
