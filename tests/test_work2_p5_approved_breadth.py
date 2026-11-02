"""Approved P5 breadth minimum, using the actually measured independent 30/300s counts.

These fast tests validate the production predicate; they are NOT P5 acceptance.
"""
import pytest

from src.v2.source_paid_cold_comparison import _p5_twofold_paid_breadth


@pytest.mark.parametrize("n30,n300,expected", [
    (439, 3138, True),    # real Work2 paid 30/300 s Action #41506985519
    (439, 878, True),     # inclusive exact 2x boundary
    (439, 877, False),    # one below boundary
    (439, 0, False),
    (0, 3138, False),
    (-1, 3138, False),
    (True, 2, False),
    (439, True, False),
])
def test_p5_twofold_source_paid_candidate_breadth(n30, n300, expected):
    assert _p5_twofold_paid_breadth(n30, n300) is expected
