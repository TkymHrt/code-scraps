"""既知形状を画素化し、長手軸に沿う側辺長と傾きへの安定性を確認する。"""

import math
import unittest
from unittest.mock import patch

import cv2 as cv
import numpy as np
from test_refactored_workflow import load_refactored

IMAGE_SIZE = 1200
BOUNDS = (0, 0, IMAGE_SIZE, IMAGE_SIZE)
CENTER = np.array([600.0, 600.0])


def raster_contour(points):
    mask = np.zeros((IMAGE_SIZE, IMAGE_SIZE), np.uint8)
    cv.fillPoly(mask, [np.rint(points).astype(np.int32)], 255)
    contours, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_NONE)
    contour = max(contours, key=cv.contourArea).reshape(-1, 2).astype(np.float64)
    return contour, mask


def specimen(angle_degrees, left_amplitude_mm=0.0, right_amplitude_mm=0.0):
    """0.25 mm/pxで、35 mm周期の左右独立した波形を画素化する。"""
    angle = math.radians(angle_degrees)
    direction = np.array([math.sin(angle), math.cos(angle)])
    normal = np.array([direction[1], -direction[0]])
    distance_px = np.linspace(-420, 420, 1681)
    phase = 2 * math.pi * distance_px * 0.25 / 35
    left_px = -60 - left_amplitude_mm / 0.25 * np.cos(phase)
    right_px = 60 + right_amplitude_mm / 0.25 * np.cos(phase)
    left_points = CENTER + distance_px[:, None] * direction + left_px[:, None] * normal
    right_points = (
        CENTER + distance_px[:, None] * direction + right_px[:, None] * normal
    )
    polygon = np.concatenate([left_points, right_points[::-1]])
    contour, mask = raster_contour(polygon)
    interval = np.array([CENTER - 280 * direction, CENTER + 280 * direction])
    return contour, mask, interval, (CENTER.copy(), direction)


def known_side_length(amplitude_mm):
    distance_mm = np.linspace(-70, 70, 20001)
    derivative = amplitude_mm * 2 * math.pi / 35
    slope = derivative * np.sin(2 * math.pi * distance_mm / 35)
    return float(np.trapezoid(np.sqrt(1 + slope**2), distance_mm))


class PolygonRegionTests(unittest.TestCase):
    def setUp(self):
        self.script = load_refactored("02_measure_edge_lengths_gui.py")
        self.image = np.zeros((100, 100, 3), np.uint8)

    def test_multiple_polygons_and_background_foreground_precedence(self):
        regions = {
            cv.GC_PR_FGD: [
                [(0.1, 0.1), (0.5, 0.1), (0.1, 0.5)],
                [(0.6, 0.6), (0.9, 0.6), (0.9, 0.9), (0.6, 0.9)],
            ],
            cv.GC_BGD: [[(0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4)]],
            cv.GC_FGD: [[(0.25, 0.25), (0.35, 0.25), (0.35, 0.35), (0.25, 0.35)]],
        }
        labels = self.script["initial_mask"](self.image, regions)
        self.assertEqual(labels[15, 15], cv.GC_PR_FGD)
        self.assertEqual(labels[75, 75], cv.GC_PR_FGD)
        self.assertEqual(labels[22, 22], cv.GC_BGD)
        self.assertEqual(labels[30, 30], cv.GC_FGD)
        self.assertEqual(labels[50, 50], cv.GC_PR_BGD)

    def test_invalid_polygon_coordinates_and_zero_area_are_rejected(self):
        polygons = [
            [(0.1, 0.1), (0.5, 0.5)],
            [(0.1, 0.1), (0.3, 0.3), (0.5, 0.5)],
            [(0.1, 0.1), (1.1, 0.1), (0.1, 0.5)],
            [(0.1, 0.1), (math.nan, 0.1), (0.1, 0.5)],
        ]
        for polygon in polygons:
            with self.subTest(polygon=polygon):
                regions = {cv.GC_PR_FGD: [polygon], cv.GC_BGD: [], cv.GC_FGD: []}
                with self.assertRaises(ValueError):
                    self.script["initial_mask"](self.image, regions)


class AxisGeometryTests(unittest.TestCase):
    def setUp(self):
        self.script = load_refactored("02_measure_edge_lengths_gui.py")

    def test_tilted_straight_sides_remain_140_mm(self):
        for angle in (-40, -20, 0, 20, 40):
            with self.subTest(angle=angle):
                contour, _mask, interval, true_axis = specimen(angle)
                axis = self.script["estimate_axis"](contour, BOUNDS, interval)
                direction_error = math.degrees(
                    math.acos(float(np.clip(np.dot(axis[1], true_axis[1]), -1, 1)))
                )
                self.assertLess(direction_error, 0.25)
                row = self.script["measure_contour"](contour, BOUNDS, interval, axis)
                self.assertAlmostEqual(row["interval_length_mm"], 140, delta=0.01)
                for edge in ("left", "right"):
                    self.assertAlmostEqual(row[f"{edge}_mm"], 140, delta=0.35)
                    self.assertLess(abs(row[f"{edge}_excess_percent"]), 0.25)

    def test_contour_midpoints_correct_axis_from_off_center_interval_anchors(self):
        contour, _mask, interval, true_axis = specimen(20)
        direction = true_axis[1]
        normal = np.array([direction[1], -direction[0]])
        interval[0] += 20 * normal
        interval[1] -= 20 * normal
        seed = self.script["manual_axis"](interval)
        initial_error = math.degrees(math.acos(float(np.dot(seed[1], direction))))
        self.assertGreater(initial_error, 4)
        axis = self.script["estimate_axis"](contour, BOUNDS, interval)
        final_error = math.degrees(
            math.acos(float(np.clip(np.dot(axis[1], direction), -1, 1)))
        )
        self.assertLess(final_error, 0.1)
        row = self.script["measure_contour"](contour, BOUNDS, interval, axis)
        self.assertAlmostEqual(row["interval_length_mm"], 140, delta=0.01)
        for edge in ("left", "right"):
            self.assertAlmostEqual(row[f"{edge}_mm"], 140, delta=0.35)

    def test_grabcut_auto_axis_and_lengths_on_tilted_high_contrast_images(self):
        for angle in (-30, 30):
            for shape, amplitudes in (("straight", (0, 0)), ("ripple", (4, 7))):
                with self.subTest(angle=angle, shape=shape):
                    _contour, mask, interval, true_axis = specimen(angle, *amplitudes)
                    image = np.full((IMAGE_SIZE, IMAGE_SIZE, 3), 25, np.uint8)
                    image[mask > 0] = 210
                    original = image.copy()
                    origin, direction = true_axis
                    normal = np.array([direction[1], -direction[0]])
                    enclosure = np.array(
                        [
                            origin - 440 * direction - 120 * normal,
                            origin - 440 * direction + 120 * normal,
                            origin + 440 * direction + 120 * normal,
                            origin + 440 * direction - 120 * normal,
                        ]
                    )
                    foreground = np.array(
                        [
                            origin - 30 * direction - 12 * normal,
                            origin - 30 * direction + 12 * normal,
                            origin + 30 * direction + 12 * normal,
                            origin + 30 * direction - 12 * normal,
                        ]
                    )
                    regions = {
                        cv.GC_PR_FGD: [(enclosure / (IMAGE_SIZE - 1)).tolist()],
                        cv.GC_BGD: [],
                        cv.GC_FGD: [(foreground / (IMAGE_SIZE - 1)).tolist()],
                    }
                    contour, bounds = self.script["extract_specimen"](image, regions)
                    extracted_mask = np.zeros(mask.shape, np.uint8)
                    cv.fillPoly(extracted_mask, [contour.astype(np.int32)], 255)
                    np.testing.assert_array_equal(extracted_mask, mask)
                    np.testing.assert_array_equal(image, original)
                    axis = self.script["estimate_axis"](contour, bounds, interval)
                    row = self.script["measure_contour"](
                        contour, bounds, interval, axis
                    )
                    self.assertAlmostEqual(row["interval_length_mm"], 140, delta=0.01)
                    for edge, amplitude in zip(("left", "right"), amplitudes):
                        expected_mm = known_side_length(amplitude)
                        self.assertAlmostEqual(
                            row[f"{edge}_mm"], expected_mm, delta=expected_mm * 0.012
                        )

    def test_unequal_ripples_match_known_lengths_and_survive_tilt(self):
        expected = {"left": known_side_length(4), "right": known_side_length(7)}
        measured = {"left": [], "right": []}
        for angle in (-40, -20, 0, 20, 40):
            contour, _mask, interval, true_axis = specimen(angle, 4, 7)
            auto_axis = self.script["estimate_axis"](contour, BOUNDS, interval)
            for axis_name, axis in (("manual", true_axis), ("auto", auto_axis)):
                with self.subTest(angle=angle, axis=axis_name):
                    row = self.script["measure_contour"](
                        contour, BOUNDS, interval, axis
                    )
                    self.assertAlmostEqual(row["interval_length_mm"], 140, delta=0.01)
                    self.assertGreater(
                        row["right_excess_percent"], row["left_excess_percent"]
                    )
                    self.assertGreater(row["left_excess_percent"], 8)
                    for edge in ("left", "right"):
                        measured[edge].append(row[f"{edge}_mm"])
                        self.assertAlmostEqual(
                            row[f"{edge}_mm"],
                            expected[edge],
                            delta=expected[edge] * 0.012,
                        )
                        expected_percent = (
                            row[f"{edge}_mm"] / row["interval_length_mm"] - 1
                        ) * 100
                        self.assertAlmostEqual(
                            row[f"{edge}_excess_percent"], expected_percent
                        )
        for edge in ("left", "right"):
            self.assertLess(max(measured[edge]) - min(measured[edge]), 0.7)

    def test_smoothing_reduces_raster_staircase_overestimate(self):
        contour, _mask, interval, axis = specimen(40)
        measure = self.script["measure_contour"]
        smoothed = measure(contour, BOUNDS, interval, axis)
        with patch.dict(
            measure.__globals__,
            {"SMOOTHING_WIDTH_MM": 0.0, "EVALUATION_INTERVAL_MM": 0.25},
        ):
            raw = measure(contour, BOUNDS, interval, axis)
        for edge in ("left", "right"):
            self.assertGreater(raw[f"{edge}_mm"], 140.5)
            self.assertLess(
                abs(smoothed[f"{edge}_mm"] - 140), abs(raw[f"{edge}_mm"] - 140)
            )

    def test_reference_length_uses_axis_projection_and_exact_last_sample(self):
        contour, _mask, _interval, axis = specimen(35)
        origin, direction = axis
        normal = np.array([direction[1], -direction[0]])
        interval = np.array(
            [
                origin - 274.6 * direction + 24 * normal,
                origin + 274.6 * direction - 18 * normal,
            ]
        )
        row = self.script["measure_contour"](contour, BOUNDS, interval, axis)
        self.assertAlmostEqual(row["interval_length_mm"], 137.3, places=8)
        self.assertAlmostEqual(row["left_mm"], 137.3, delta=0.35)
        self.assertAlmostEqual(row["right_mm"], 137.3, delta=0.35)
        self.assertEqual(row["mm_per_px"], 0.25)
        self.assertEqual(row["evaluation_interval_mm"], 1.0)
        self.assertEqual(row["smoothing_width_mm"], 2.0)

    def test_reentrant_side_keeps_continuous_path_length_between_simple_cuts(self):
        left_local = np.array(
            [
                [-60, -420],
                [-60, -200],
                [-100, -120],
                [-130, -160],
                [-150, -100],
                [-60, -40],
                [-60, 420],
            ],
            np.float64,
        )
        right_local = np.array([[60, -420], [60, 420]], np.float64)
        measured_left = np.vstack(([-60, -280], left_local[1:-1], [-60, 280]))
        segment_lengths = np.linalg.norm(np.diff(measured_left, axis=0), axis=1)
        expected_left_mm = float(segment_lengths.sum()) * 0.25
        measure = self.script["measure_contour"]
        for angle in (-35, 0, 35):
            with self.subTest(angle=angle):
                radians = math.radians(angle)
                direction = np.array([math.sin(radians), math.cos(radians)])
                normal = np.array([direction[1], -direction[0]])
                local = np.concatenate([left_local, right_local[::-1]])
                contour = (
                    CENTER + local[:, 0, None] * normal + local[:, 1, None] * direction
                )
                interval = np.array(
                    [CENTER - 280 * direction, CENTER + 280 * direction]
                )
                axis = (CENTER.copy(), direction)
                with patch.dict(
                    measure.__globals__,
                    {"SMOOTHING_WIDTH_MM": 0.0, "EVALUATION_INTERVAL_MM": 0.05},
                ):
                    fine = measure(contour, BOUNDS, interval, axis)
                self.assertAlmostEqual(fine["interval_length_mm"], 140, places=8)
                self.assertAlmostEqual(fine["left_mm"], expected_left_mm, delta=0.15)
                self.assertAlmostEqual(fine["right_mm"], 140, delta=0.01)
                smoothed = measure(contour, BOUNDS, interval, axis)
                self.assertGreater(smoothed["left_mm"], expected_left_mm * 0.94)
                self.assertGreater(smoothed["left_mm"] - smoothed["right_mm"], 25)
                self.assertAlmostEqual(smoothed["right_mm"], 140, delta=0.01)

    def test_manual_axis_endpoint_order_preserves_dr_op_and_lengths(self):
        contour, _mask, interval, axis = specimen(-35, 4, 7)
        points = np.array([axis[0] - 200 * axis[1], axis[0] + 200 * axis[1]])
        forward = self.script["manual_axis"](points)
        backward = self.script["manual_axis"](points[::-1])
        np.testing.assert_allclose(forward[1], backward[1], atol=1e-12)
        self.assertGreater(forward[1][1], 0)
        row_forward = self.script["measure_contour"](contour, BOUNDS, interval, forward)
        row_backward = self.script["measure_contour"](
            contour, BOUNDS, interval, backward
        )
        for column in ("interval_length_mm", "left_mm", "right_mm"):
            self.assertAlmostEqual(row_forward[column], row_backward[column], places=8)

    def test_axis_changes_with_interval_and_ignores_bending_outside_it(self):
        distance_px = np.linspace(-420, 420, 1681)
        center_x = np.zeros_like(distance_px)
        center_x[distance_px < -100] = 0.65 * (distance_px[distance_px < -100] + 100)
        center_x[distance_px > 100] = 0.65 * (distance_px[distance_px > 100] - 100)
        left = CENTER + np.column_stack([center_x - 45, distance_px])
        right = CENTER + np.column_stack([center_x + 45, distance_px])
        contour, _mask = raster_contour(np.concatenate([left, right[::-1]]))
        central_interval = CENTER + np.array([[0, -70], [0, 70]])
        bent_interval = CENTER + np.array([[65, 200], [162.5, 350]])
        central = self.script["estimate_axis"](contour, BOUNDS, central_interval)
        bent = self.script["estimate_axis"](contour, BOUNDS, bent_interval)
        self.assertAlmostEqual(central[1][0], 0, delta=0.005)
        expected_direction = np.array([0.65, 1]) / math.hypot(0.65, 1)
        np.testing.assert_allclose(bent[1], expected_direction, atol=0.01)
        self.assertGreater(abs(bent[1][0] - central[1][0]), 0.5)

    def test_invalid_axis_interval_settings_and_missing_sections_are_rejected(self):
        contour, _mask, interval, axis = specimen(0)
        for points in (
            np.array([[1, 1], [1, 1]]),
            np.array([[1, 1], [math.inf, 1]]),
        ):
            with self.subTest(points=points), self.assertRaises(ValueError):
                self.script["manual_axis"](points)
        for invalid_interval in (
            np.array([[580, 400], [620, 400]]),
            np.array([[600, 0], [600, 1199]]),
            np.array([[600, math.nan], [600, 800]]),
        ):
            with self.subTest(interval=invalid_interval), self.assertRaises(ValueError):
                self.script["measure_contour"](contour, BOUNDS, invalid_interval, axis)
        for name, value in (
            ("MM_PER_PX", 0),
            ("EVALUATION_INTERVAL_MM", 0),
            ("EVALUATION_INTERVAL_MM", math.nan),
            ("SMOOTHING_WIDTH_MM", -1),
        ):
            with self.subTest(name=name, value=value):
                measure = self.script["measure_contour"]
                with patch.dict(measure.__globals__, {name: value}):
                    with self.assertRaises(ValueError):
                        measure(contour, BOUNDS, interval, axis)

    def test_clipped_side_and_disjoint_cross_section_are_rejected(self):
        axis = (CENTER.copy(), np.array([0.0, 1.0]))
        interval = np.array([[600, 350], [600, 650]])
        clipped = np.array([[0, 200], [100, 200], [100, 800], [0, 800]], np.float64)
        with self.assertRaises(ValueError):
            self.script["measure_contour"](clipped, BOUNDS, interval, axis)
        # 下だけでつながる二股の試料。左右端を結んで空隙を隠してはならない。
        split = np.array(
            [
                [450, 200],
                [500, 200],
                [500, 700],
                [700, 700],
                [700, 200],
                [750, 200],
                [750, 800],
                [450, 800],
            ],
            np.float64,
        )
        with self.assertRaises(ValueError):
            self.script["measure_contour"](split, BOUNDS, interval, axis)


if __name__ == "__main__":
    unittest.main()
