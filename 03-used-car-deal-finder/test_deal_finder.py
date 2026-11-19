import argparse
import json
import unittest
from pathlib import Path

from deal_finder import normalize_blocket, normalize_craigslist, passes, rank, score_deals

HERE = Path(__file__).parent


def flags(**kw):
    base = dict(min_year=None, max_price=None, max_mileage=None, fuel=None, transmission=None, keyword=None)
    return argparse.Namespace(**{**base, **kw})


def cars(source, normalize):
    return [normalize(r) for r in json.loads((HERE / "sample" / f"{source}.json").read_text())]


class DealFinderTests(unittest.TestCase):
    def test_blocket_mil_is_converted_to_km(self):
        car = normalize_blocket({"price": 1, "year": 2018, "mileage": 8500, "mileage_unit": "mil", "brand": "Volvo", "model": "V60"})
        self.assertEqual(car["mileage"], 85000)
        plain = normalize_blocket({"price": 1, "mileage": 8500, "mileage_unit": "km"})
        self.assertEqual(plain["mileage"], 8500)

    def test_craigslist_group_and_odometer(self):
        car = cars("craigslist", normalize_craigslist)[0]
        self.assertEqual(car["group"], "toyota tacoma")
        self.assertEqual(car["mileage"], 120000)
        self.assertEqual(car["year"], 2012)

    def test_filters_drop_cars_without_the_filtered_value(self):
        c = cars("blocket", normalize_blocket)
        self.assertFalse(any(passes(x, flags()) and x["price"] is None for x in c))  # no price -> never passes
        self.assertEqual(len([x for x in c if passes(x, flags())]), 6)
        self.assertEqual(len([x for x in c if passes(x, flags(min_year=2018))]), 4)
        self.assertEqual(len([x for x in c if passes(x, flags(fuel="diesel", transmission="automatisk"))]), 3)
        self.assertEqual(len([x for x in c if passes(x, flags(max_mileage=80000))]), 2)
        self.assertEqual(len([x for x in c if passes(x, flags(keyword=["volvo", "v60"]))]), 5)

    def test_ranks_the_cheap_car_first_and_needs_three_comparables(self):
        c = [x for x in cars("blocket", normalize_blocket) if passes(x, flags())]
        deals = rank(c, 10)
        self.assertEqual(deals[0]["url"], "https://cars.example/blocket/4")
        self.assertGreater(deals[0]["discount"], 20)
        saab = [x for x in score_deals(c) if x["group"].startswith("saab")][0]
        self.assertIsNone(saab["discount"])  # one Saab: no comparables, so no verdict

    def test_craigslist_deal(self):
        c = [x for x in cars("craigslist", normalize_craigslist) if passes(x, flags())]
        self.assertEqual(rank(c, 10)[0]["url"], "https://cars.example/cl/4")


if __name__ == "__main__":
    unittest.main()
