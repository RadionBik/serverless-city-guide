"""Tests for bearing module — pure math, no mocking needed."""

from city_guide.bearing import bearing, haversine


def test_haversine_same_point() -> None:
    assert haversine(51.5, -0.1, 51.5, -0.1) == 0.0


def test_haversine_known_distance() -> None:
    # London (51.5074, -0.1278) to Paris (48.8566, 2.3522) ≈ 343.5 km
    dist = haversine(51.5074, -0.1278, 48.8566, 2.3522)
    assert 340_000 < dist < 347_000


def test_haversine_short_distance() -> None:
    # Two points ~111m apart (0.001 degree latitude)
    dist = haversine(51.5000, -0.1000, 51.5010, -0.1000)
    assert 110 < dist < 112


def test_bearing_north() -> None:
    b = bearing(51.5, -0.1, 51.6, -0.1)
    assert b > 355 or b < 5  # roughly north


def test_bearing_east() -> None:
    b = bearing(51.5, -0.1, 51.5, 0.0)
    assert 85 < b < 95


def test_bearing_south() -> None:
    b = bearing(51.5, -0.1, 51.4, -0.1)
    assert 175 < b < 185


def test_bearing_west() -> None:
    b = bearing(51.5, -0.1, 51.5, -0.2)
    assert 265 < b < 275
