from meteor_detector_common import calculate_confidence, calculate_linearity


def test_calculate_linearity_straight_line():
    xs = [0, 10, 20, 30]
    ys = [0, 10, 20, 30]
    linearity = calculate_linearity(xs, ys)
    assert linearity > 0.99


def test_calculate_linearity_non_line():
    xs = [0, 10, 20, 30]
    ys = [0, 5, 0, 5]
    linearity = calculate_linearity(xs, ys)
    assert linearity < 0.99


def test_calculate_confidence_caps_to_one():
    confidence = calculate_confidence(
        length=1000,
        speed=1000,
        linearity=1.0,
        brightness=255,
        duration=1000,
    )
    assert 0.0 <= confidence <= 1.0
