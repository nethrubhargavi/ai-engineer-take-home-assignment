import unittest

from evaluate import canonical_name, compare, value_key


class ValueKeyTests(unittest.TestCase):
    def test_indian_grouping_matches_ungrouped_integer(self):
        self.assertEqual(value_key("2,29,000"), value_key("229000"))

    def test_indian_grouping_matches_decimal_number(self):
        self.assertEqual(value_key("2,29,000"), value_key(229000.0))

    def test_ordinary_decimals_match_across_formatting(self):
        self.assertEqual(value_key("13.50"), value_key(13.5))

    def test_qualitative_values_are_case_insensitive(self):
        self.assertEqual(value_key("Negative"), value_key("negative"))

    def test_qualitative_value_does_not_become_a_number(self):
        self.assertNotEqual(value_key("Negative"), value_key(0))


class NameAliasTests(unittest.TestCase):
    def setUp(self):
        self.gold = [
            {"test_name": "Cholesterol - LDL", "value": "80", "unit": "mg/dL"},
            {"test_name": "Glucose - PP", "value": "80", "unit": "mg/dL"},
        ]
        # Both tests intentionally share the same value and unit.
        self.extracted = [
            {"test_name": "Postprandial Glucose", "value": 80.0, "unit": "mg/dL"},
            {"test_name": "LDL Cholesterol", "value": 80.0, "unit": "mg/dL"},
        ]

    def test_aliases_pair_tests_with_identical_values_and_units(self):
        issues = compare(self.gold, self.extracted)

        self.assertEqual(issues["missing_tests"], [])
        self.assertEqual(issues["extra_tests"], [])
        self.assertEqual(issues["wrong_values"], [])
        self.assertEqual(issues["wrong_units"], [])
        self.assertEqual(issues["wrong_names"], [])

    def test_value_error_stays_with_the_named_test(self):
        extracted = [dict(row) for row in self.extracted]
        extracted[1]["value"] = 81.0

        issues = compare(self.gold, extracted)

        self.assertEqual(issues["missing_tests"], [])
        self.assertEqual(issues["extra_tests"], [])
        self.assertEqual(issues["wrong_values"], [
            {"test": "Cholesterol - LDL", "gold": "80", "extracted": 81.0}
        ])


class ExplicitAliasMapTests(unittest.TestCase):
    def test_explicit_global_aliases_share_canonical_names(self):
        aliases = [
            ("Cholesterol - Total", "S. Cholesterol"),
            ("Cholesterol - HDL", "HDL-C"),
            ("Cholesterol - VLDL", "VLDL"),
            ("TG", "Triglycerides"),
            ("TC/HDL Ratio", "Chol/HDL"),
            ("LDL-C (Direct)", "LDL Cholesterol (Direct)"),
            ("Aspartate Aminotransferase", "Aspartate Aminotransferase (AST)"),
            ("Alanine Aminotransferase", "Alanine Aminotransferase (ALT)"),
            ("ALP", "Alkaline Phosphatase (ALP)"),
            ("Protein Total", "Total Protein"),
            ("T3", "Total T3"),
            ("T4", "Total T4"),
            ("TSH (Ultrasensitive)", "Thyroid Stimulating Hormone"),
            ("Vit D Total", "Vitamin D Total"),
            ("Vit B12", "Cyanocobalamin (Vitamin B12)"),
            ("Glycated Hb", "Glycated Hemoglobin (HbA1c)"),
            ("FBS", "Fasting Blood Sugar (FBS)"),
            ("PPBS", "Postprandial Blood Sugar (PPBS)"),
        ]

        for first, second in aliases:
            with self.subTest(first=first, second=second):
                self.assertEqual(canonical_name(first), canonical_name(second))

    def test_urinalysis_aliases_are_scoped_to_their_report(self):
        self.assertEqual(
            canonical_name("Albumin", "report_06"),
            canonical_name("Urine Albumin", "report_06"),
        )
        self.assertNotEqual(
            canonical_name("Albumin", "report_11"),
            canonical_name("Urine Albumin", "report_11"),
        )
        issues = compare(
            [{"test_name": "Albumin", "value": "Negative", "unit": None}],
            [{"test_name": "Urine Albumin", "value": "Negative", "unit": None}],
            "report_06",
        )
        self.assertEqual(issues["missing_tests"], [])
        self.assertEqual(issues["extra_tests"], [])
        self.assertEqual(issues["wrong_names"], [])

    def test_alias_pairing_still_reports_wrong_value_and_unit(self):
        issues = compare(
            [{"test_name": "Cholesterol - Total", "value": "188", "unit": "mg/dL"}],
            [{"test_name": "S. Cholesterol", "value": 189.0, "unit": "mmol/L"}],
        )

        self.assertEqual(issues["missing_tests"], [])
        self.assertEqual(issues["extra_tests"], [])
        self.assertEqual(issues["wrong_names"], [])
        self.assertEqual(len(issues["wrong_values"]), 1)
        self.assertEqual(len(issues["wrong_units"]), 1)

    def test_direct_ldl_does_not_alias_to_ordinary_ldl(self):
        issues = compare(
            [{"test_name": "LDL-C (Direct)", "value": "80", "unit": "mg/dL"}],
            [{"test_name": "LDL Cholesterol", "value": 80.0, "unit": "mg/dL"}],
        )

        self.assertEqual(len(issues["missing_tests"]), 1)
        self.assertEqual(len(issues["extra_tests"]), 1)
        self.assertEqual(issues["wrong_names"], [])


if __name__ == "__main__":
    unittest.main()
