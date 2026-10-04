import unittest

from app.services.bag_status import calculate_bag_status


class BagStatusTests(unittest.TestCase):
    REQUIRED = ["English", "Mathematics", "Science", "Computer Science", "Tamil"]

    def test_zero_books_scanned(self):
        r = calculate_bag_status(self.REQUIRED, [])
        self.assertEqual((r["packed_count"], r["required_count"], r["percentage"], r["ready"]), (0, 5, 0, False))
        self.assertEqual(r["missing_books"], self.REQUIRED)

    def test_partial_packing_matches_the_spec_example(self):
        r = calculate_bag_status(self.REQUIRED, ["English", "Mathematics", "Computer Science"])
        self.assertEqual((r["required_count"], r["packed_count"], len(r["missing_books"]), r["percentage"]), (5, 3, 2, 60))
        self.assertEqual(r["status"], "BAG NOT READY")
        self.assertEqual(r["missing_books"], ["Science", "Tamil"])

    def test_full_packing(self):
        r = calculate_bag_status(self.REQUIRED, self.REQUIRED)
        self.assertTrue(r["ready"])
        self.assertEqual((r["percentage"], r["status"]), (100, "BAG READY"))

    def test_extra_books_never_count_towards_readiness(self):
        r = calculate_bag_status(self.REQUIRED, ["English", "Art"])
        self.assertEqual(r["extra_books"], ["Art"])
        self.assertEqual(r["packed_count"], 1)
        self.assertFalse(r["ready"])

    def test_duplicates_and_case_are_ignored(self):
        r = calculate_bag_status(["English", "Tamil"], ["english", "ENGLISH", " English "])
        self.assertEqual((r["packed_count"], r["percentage"]), (1, 50))

    def test_empty_day_has_nothing_to_pack(self):
        r = calculate_bag_status([], [])
        self.assertEqual((r["required_count"], r["percentage"], r["ready"]), (0, 100, True))


if __name__ == "__main__":
    unittest.main()
