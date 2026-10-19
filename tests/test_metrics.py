import unittest
from datetime import datetime, timedelta

from experiment.metrics import calculate_trial_metrics, compute_aggregates


class TestMetrics(unittest.TestCase):
    def test_calculate_trial_metrics_success(self) -> None:
        t0 = datetime(2026, 10, 20, 12, 0, 0)
        t_inject = t0
        t_detect = t0 + timedelta(milliseconds=250)
        t_recover = t0 + timedelta(milliseconds=350)

        events = [
            {"trial_id": "test_01", "fault_type": "process_kill", "event": "INJECTED", "timestamp": t_inject.isoformat()},
            {"trial_id": "test_01", "fault_type": "process_kill", "event": "DETECTED", "timestamp": t_detect.isoformat()},
            {"trial_id": "test_01", "fault_type": "process_kill", "event": "RECOVERED", "timestamp": t_recover.isoformat()},
        ]

        metrics = calculate_trial_metrics("test_01", events=events)
        self.assertEqual(metrics["trial_id"], "test_01")
        self.assertEqual(metrics["fault_type"], "process_kill")
        self.assertAlmostEqual(metrics["mttd_sec"], 0.25, places=3)
        self.assertAlmostEqual(metrics["mttr_sec"], 0.35, places=3)
        self.assertTrue(metrics["success"])

    def test_calculate_trial_metrics_missing_detected(self) -> None:
        t0 = datetime(2026, 10, 20, 12, 0, 0)
        events = [
            {"trial_id": "test_02", "fault_type": "process_kill", "event": "INJECTED", "timestamp": t0.isoformat()},
            {"trial_id": "test_02", "fault_type": "process_kill", "event": "RECOVERED", "timestamp": (t0 + timedelta(seconds=1)).isoformat()},
        ]

        metrics = calculate_trial_metrics("test_02", events=events)
        self.assertIsNone(metrics["mttd_sec"])
        self.assertAlmostEqual(metrics["mttr_sec"], 1.0, places=3)
        self.assertTrue(metrics["success"])

    def test_calculate_trial_metrics_missing_recovered(self) -> None:
        t0 = datetime(2026, 10, 20, 12, 0, 0)
        events = [
            {"trial_id": "test_03", "fault_type": "cpu_hog", "event": "INJECTED", "timestamp": t0.isoformat()},
            {"trial_id": "test_03", "fault_type": "cpu_hog", "event": "DETECTED", "timestamp": (t0 + timedelta(milliseconds=500)).isoformat()},
        ]

        metrics = calculate_trial_metrics("test_03", events=events)
        self.assertAlmostEqual(metrics["mttd_sec"], 0.5, places=3)
        self.assertIsNone(metrics["mttr_sec"])
        self.assertFalse(metrics["success"])

    def test_calculate_trial_metrics_empty_events(self) -> None:
        metrics = calculate_trial_metrics("empty_trial", events=[])
        self.assertEqual(metrics["trial_id"], "empty_trial")
        self.assertEqual(metrics["fault_type"], "unknown")
        self.assertIsNone(metrics["mttd_sec"])
        self.assertIsNone(metrics["mttr_sec"])
        self.assertFalse(metrics["success"])

    def test_compute_aggregates_empty(self) -> None:
        agg = compute_aggregates([])
        self.assertEqual(agg["count"], 0)
        self.assertEqual(agg["success_count"], 0)
        self.assertEqual(agg["success_rate"], 0.0)
        self.assertEqual(agg["mttd_mean"], 0.0)
        self.assertEqual(agg["mttr_mean"], 0.0)

    def test_compute_aggregates_known_values(self) -> None:
        trial_metrics = [
            {"trial_id": "t1", "fault_type": "pk", "mttd_sec": 0.2, "mttr_sec": 0.3, "success": True},
            {"trial_id": "t2", "fault_type": "pk", "mttd_sec": 0.4, "mttr_sec": 0.5, "success": True},
            {"trial_id": "t3", "fault_type": "pk", "mttd_sec": 0.6, "mttr_sec": None, "success": False},
        ]

        agg = compute_aggregates(trial_metrics)
        self.assertEqual(agg["count"], 3)
        self.assertEqual(agg["success_count"], 2)
        self.assertAlmostEqual(agg["success_rate"], (2 / 3) * 100.0, places=2)
        self.assertAlmostEqual(agg["mttd_mean"], 0.4, places=3)
        self.assertAlmostEqual(agg["mttd_median"], 0.4, places=3)
        self.assertAlmostEqual(agg["mttd_min"], 0.2, places=3)
        self.assertAlmostEqual(agg["mttd_max"], 0.6, places=3)
        self.assertAlmostEqual(agg["mttr_mean"], 0.4, places=3)
        self.assertAlmostEqual(agg["mttr_median"], 0.4, places=3)
        self.assertAlmostEqual(agg["mttr_min"], 0.3, places=3)
        self.assertAlmostEqual(agg["mttr_max"], 0.5, places=3)


if __name__ == "__main__":
    unittest.main()
