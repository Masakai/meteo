from meteor_detector_common import calculate_confidence, calculate_heading_variance, calculate_linearity


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


def test_calculate_heading_variance_straight_line_is_near_zero():
    xs = [0, 10, 20, 30, 40]
    ys = [0, 10, 20, 30, 40]
    variance = calculate_heading_variance(xs, ys)
    assert variance < 1e-6


def test_calculate_heading_variance_zigzag_is_high():
    xs = [0, 10, 20, 30, 40, 50]
    ys = [0, 10, 0, 10, 0, 10]
    variance = calculate_heading_variance(xs, ys)
    assert variance > 0.5


def test_calculate_heading_variance_insufficient_points_returns_zero():
    # 点数不足（角度差を1つも計算できない）はfail-open用に0.0を返す
    assert calculate_heading_variance([], []) == 0.0
    assert calculate_heading_variance([0], [0]) == 0.0
    assert calculate_heading_variance([0, 10], [0, 10]) == 0.0


def test_calculate_confidence_caps_to_one():
    confidence = calculate_confidence(
        length=1000,
        speed=1000,
        linearity=1.0,
        brightness=255,
        duration=1000,
    )
    assert 0.0 <= confidence <= 1.0
