"""PR7 derived circuit metrics tests."""
import unittest
from diagnostics.circuit_telemetry import CircuitSample, derive


class CircuitTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.sample = CircuitSample(
            twi=31, two=34, tao=2, tsat_ps_actual=-2.5,
            tsat_pd_actual=32.6, td=47.1, ps_actual=0.6,
            pd_actual=2.2, compressor_actual_hz=40,
            compressor_target_hz=55, eev_level=320,
        )

    def test_expected_derived_metrics(self):
        result = derive(self.sample, r141_fresh=True, r241_fresh=True)
        self.assertEqual(result["water_delta_t"], 3)
        self.assertEqual(result["saturation_lift"], 35.1)
        self.assertEqual(result["ambient_evaporating_approach"], 4.5)
        self.assertEqual(result["discharge_condensing_gap"], 14.5)
        self.assertEqual(result["pressure_delta_mpa"], 1.6)
        self.assertEqual(result["compressor_frequency_error_hz"], 15)

    def test_stale_frames(self):
        self.assertIsNone(derive(self.sample, r141_fresh=False, r241_fresh=True))
        self.assertIsNone(derive(self.sample, r141_fresh=True, r241_fresh=False))

    def test_negative_sign_is_retained(self):
        sample = CircuitSample(**{**self.sample.__dict__, "two": 29, "twi": 34,
                                   "compressor_actual_hz": 60})
        result = derive(sample, r141_fresh=True, r241_fresh=True)
        self.assertEqual(result["water_delta_t"], -5)
        self.assertEqual(result["compressor_frequency_error_hz"], -5)

    def test_invalid_measurements(self):
        for bad in (float("nan"), float("inf"), None, "22", True):
            sample = CircuitSample(**{**self.sample.__dict__, "twi": bad})
            with self.assertRaises(ValueError):
                derive(sample, r141_fresh=True, r241_fresh=True)

    def test_pressure_limits(self):
        sample = CircuitSample(**{**self.sample.__dict__, "ps_actual": -0.2})
        with self.assertRaises(ValueError):
            derive(sample, r141_fresh=True, r241_fresh=True)


if __name__ == "__main__":
    unittest.main()
