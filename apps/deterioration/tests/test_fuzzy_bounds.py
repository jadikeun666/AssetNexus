"""
formulas.md §3 — Fuzzy Markov Bounds. engineering-rules.md §7: setiap
formula punya test dengan expected value dihitung tangan.
"""
import pytest

from apps.deterioration.services_fuzzy import CentroidDefuzzificationService


class TestCentroidDefuzzification:
    def test_centroid_one_hot_cs1_equals_cs1_midpoint(self):
        """Distribusi one-hot di CS1 -> centroid harus persis midpoint CS1
        (95.0), tanpa kontribusi state lain."""
        service = CentroidDefuzzificationService()
        result = service.centroid({"CS1": 1.0, "CS2": 0.0, "CS3": 0.0, "CS4": 0.0, "CS5": 0.0})
        assert result == pytest.approx(95.0)

    def test_centroid_one_hot_cs5_equals_cs5_midpoint(self):
        service = CentroidDefuzzificationService()
        result = service.centroid({"CS1": 0.0, "CS2": 0.0, "CS3": 0.0, "CS4": 0.0, "CS5": 1.0})
        assert result == pytest.approx(12.0)

    def test_centroid_hand_computed_mixed_distribution(self):
        """Dihitung tangan:
        0.10*95.0 + 0.20*79.5 + 0.40*59.5 + 0.20*37.0 + 0.10*12.0
        = 9.5 + 15.9 + 23.8 + 7.4 + 1.2
        = 57.8
        """
        service = CentroidDefuzzificationService()
        result = service.centroid({
            "CS1": 0.10,
            "CS2": 0.20,
            "CS3": 0.40,
            "CS4": 0.20,
            "CS5": 0.10,
        })
        assert result == pytest.approx(57.8)

    def test_centroid_of_upper_bound_exceeds_centroid_of_lower_bound_example(self):
        """Sanity check konseptual (formulas.md §3.2): jika distribusi
        'upper' bootstrap condong ke state lebih baik (skor lebih tinggi)
        dibanding 'lower', maka centroid(upper) > centroid(lower) --
        properti ini yang membuat confidence_width = centroid(upper) -
        centroid(lower) selalu >= 0 secara sehat (bukan negatif)."""
        service = CentroidDefuzzificationService()
        upper_leaning_good = service.centroid({"CS1": 0.5, "CS2": 0.5, "CS3": 0.0, "CS4": 0.0, "CS5": 0.0})
        lower_leaning_bad = service.centroid({"CS1": 0.0, "CS2": 0.0, "CS3": 0.0, "CS4": 0.5, "CS5": 0.5})
        assert upper_leaning_good > lower_leaning_bad
