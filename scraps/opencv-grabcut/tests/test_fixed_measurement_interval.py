"""固定長区間が軸の自動推定・手動変更でも維持されることを確認する。"""

import math
import unittest
from unittest.mock import patch

import numpy as np
from test_axis_measurement import (
    BOUNDS,
    CENTER,
    known_side_length,
    raster_contour,
    specimen,
)
from test_refactored_workflow import load_refactored


class FixedIntervalTests(unittest.TestCase):
    def setUp(self):
        self.script = load_refactored("02_measure_edge_lengths_gui.py")
        self.fixed_points = self.script["fixed_interval_points"]
        self.manual_axis = self.script["manual_axis"]
        self.vertical_axis = self.manual_axis(CENTER + np.array([[0, -50], [0, 50]]))

    def test_automatic_fit_keeps_selected_length_and_center_on_every_iteration(self):
        estimate = self.script["estimate_axis"]
        original_sections = estimate.__globals__["section_edges"]
        for angle in (-40, -20, 0, 20, 40):
            with self.subTest(angle=angle):
                contour, _mask, _interval, true_axis = specimen(angle)
                seed = self.fixed_points(CENTER, 137.3, self.vertical_axis)
                sampled_sections = []

                def record_sections(contour, bounds, axis, positions, outermost=False):
                    sampled_sections.append((axis, positions.copy()))
                    return original_sections(
                        contour, bounds, axis, positions, outermost=outermost
                    )

                with patch.dict(
                    estimate.__globals__, {"section_edges": record_sections}
                ):
                    axis = estimate(contour, BOUNDS, seed, fixed_length_mm=137.3)
                self.assertEqual(len(sampled_sections), 3)
                for fitted_axis, positions in sampled_sections:
                    origin, direction = fitted_axis
                    self.assertAlmostEqual(
                        (positions[-1] - positions[0]) * 0.25, 137.3, places=8
                    )
                    self.assertAlmostEqual(
                        (positions[-1] + positions[0]) / 2,
                        float((CENTER - origin) @ direction),
                        places=8,
                    )
                points = self.fixed_points(CENTER, 137.3, axis)
                np.testing.assert_allclose(points.mean(axis=0), CENTER, atol=1e-10)
                direction_error = math.degrees(
                    math.acos(float(np.clip(np.dot(axis[1], true_axis[1]), -1, 1)))
                )
                self.assertLess(direction_error, 0.25)
                row = self.script["measure_contour"](contour, BOUNDS, points, axis)
                self.assertAlmostEqual(row["interval_length_mm"], 137.3, places=8)
                for edge in ("left", "right"):
                    self.assertAlmostEqual(row[f"{edge}_mm"], 137.3, delta=0.35)
                    self.assertLess(abs(row[f"{edge}_excess_percent"]), 0.25)

    def test_fixed_140_mm_ripples_match_known_lengths_after_automatic_fit(self):
        for angle in (-40, -20, 0, 20, 40):
            with self.subTest(angle=angle):
                contour, _mask, _interval, _true_axis = specimen(angle, 4, 7)
                seed = self.fixed_points(CENTER, 140, self.vertical_axis)
                axis = self.script["estimate_axis"](
                    contour, BOUNDS, seed, fixed_length_mm=140
                )
                points = self.fixed_points(CENTER, 140, axis)
                row = self.script["measure_contour"](contour, BOUNDS, points, axis)
                self.assertAlmostEqual(row["interval_length_mm"], 140, places=8)
                for edge, amplitude in (("left", 4), ("right", 7)):
                    expected_mm = known_side_length(amplitude)
                    self.assertAlmostEqual(
                        row[f"{edge}_mm"], expected_mm, delta=expected_mm * 0.012
                    )
                    expected_percent = (row[f"{edge}_mm"] / 140 - 1) * 100
                    self.assertAlmostEqual(
                        row[f"{edge}_excess_percent"], expected_percent, places=8
                    )

    def test_manual_axis_direction_changes_keep_length_and_selected_center(self):
        center = CENTER + np.array([12.0, -18.0])
        for angle in (-40, -20, 0, 20, 40):
            with self.subTest(angle=angle):
                radians = math.radians(angle)
                direction = np.array([math.sin(radians), math.cos(radians)])
                axis_center = CENTER + np.array([80.0, 40.0])
                manual_points = np.array(
                    [axis_center - 70 * direction, axis_center + 70 * direction]
                )
                axis = self.manual_axis(manual_points)
                points = self.fixed_points(center, 137.3, axis)
                np.testing.assert_allclose(points.mean(axis=0), center, atol=1e-10)
                start, end = self.script["interval_positions"](points, axis)
                self.assertAlmostEqual((end - start) * 0.25, 137.3, places=8)
                np.testing.assert_allclose(
                    points[1] - points[0], direction * (137.3 / 0.25), atol=1e-10
                )

    def test_changing_length_keeps_center_and_measures_the_requested_length(self):
        contour, _mask, _interval, _true_axis = specimen(30)
        center = CENTER + np.array([8.0, 15.0])
        for length_mm in (137.3, 80.0, 150.0):
            with self.subTest(length_mm=length_mm):
                seed = self.fixed_points(center, length_mm, self.vertical_axis)
                axis = self.script["estimate_axis"](
                    contour, BOUNDS, seed, fixed_length_mm=length_mm
                )
                points = self.fixed_points(center, length_mm, axis)
                np.testing.assert_allclose(points.mean(axis=0), center, atol=1e-10)
                row = self.script["measure_contour"](contour, BOUNDS, points, axis)
                self.assertAlmostEqual(row["interval_length_mm"], length_mm, places=8)
                self.assertAlmostEqual(row["left_mm"], length_mm, delta=0.35)
                self.assertAlmostEqual(row["right_mm"], length_mm, delta=0.35)

    def test_moving_fixed_interval_reestimates_the_local_axis(self):
        distance_px = np.linspace(-420, 420, 1681)
        center_x = np.zeros_like(distance_px)
        center_x[distance_px < -100] = 0.65 * (distance_px[distance_px < -100] + 100)
        center_x[distance_px > 100] = 0.65 * (distance_px[distance_px > 100] - 100)
        left = CENTER + np.column_stack([center_x - 45, distance_px])
        right = CENTER + np.column_stack([center_x + 45, distance_px])
        contour, _mask = raster_contour(np.concatenate([left, right[::-1]]))
        directions = []
        for center in (CENTER, CENTER + np.array([113.75, 275.0])):
            seed = self.fixed_points(center, 35, self.vertical_axis)
            axis = self.script["estimate_axis"](
                contour, BOUNDS, seed, fixed_length_mm=35
            )
            points = self.fixed_points(center, 35, axis)
            row = self.script["measure_contour"](contour, BOUNDS, points, axis)
            self.assertAlmostEqual(row["interval_length_mm"], 35, places=8)
            directions.append(axis[1])
        np.testing.assert_allclose(directions[0], [0, 1], atol=0.005)
        expected_direction = np.array([0.65, 1]) / math.hypot(0.65, 1)
        np.testing.assert_allclose(directions[1], expected_direction, atol=0.01)
        self.assertGreater(abs(directions[1][0] - directions[0][0]), 0.5)

    def test_interval_beyond_specimen_is_rejected_without_shortening(self):
        contour, _mask, _interval, axis = specimen(0)
        for center, length_mm in ((CENTER, 220), (CENTER + [0, 300], 140)):
            with self.subTest(center=center, length_mm=length_mm):
                points = self.fixed_points(center, length_mm, axis)
                start, end = self.script["interval_positions"](points, axis)
                self.assertAlmostEqual((end - start) * 0.25, length_mm, places=8)
                with self.assertRaises(ValueError):
                    self.script["estimate_axis"](
                        contour, BOUNDS, points, fixed_length_mm=length_mm
                    )
                with self.assertRaises(ValueError):
                    self.script["measure_contour"](contour, BOUNDS, points, axis)

    def test_invalid_and_subpixel_lengths_are_rejected(self):
        for length_mm in (0, -1, math.nan, math.inf, -math.inf, 0.125):
            with self.subTest(length_mm=length_mm), self.assertRaises(ValueError):
                self.fixed_points(CENTER, length_mm, self.vertical_axis)

    def test_invalid_scale_is_rejected(self):
        for scale in (0, -1, math.nan, math.inf):
            with self.subTest(scale=scale):
                with patch.dict(self.fixed_points.__globals__, {"MM_PER_PX": scale}):
                    with self.assertRaises(ValueError):
                        self.fixed_points(CENTER, 140, self.vertical_axis)

    def test_invalid_center_is_rejected(self):
        for center in ([600], [600, 600, 600], [math.nan, 600], [600, math.inf]):
            with self.subTest(center=center), self.assertRaises(ValueError):
                self.fixed_points(center, 140, self.vertical_axis)


if __name__ == "__main__":
    unittest.main()
