import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from calc import evaluate

def test_ezmedicom():
    r = evaluate("이지메디컴", 10_000_000_000, 0, 10_000_000_000,
                 {"대웅제약": 9_000_000_000})
    assert r["gift_tax_total"] == 1_559_826_490, r["gift_tax_total"]
    assert r["taxable"] is True

def test_daewoongpet():
    r = evaluate("대웅펫", 5_000_000_000, 0, 8_000_000_000,
                 {"대웅제약": 5_000_000_000})
    assert r["gift_tax_total"] == 22_634_130, r["gift_tax_total"]

if __name__ == "__main__":
    test_ezmedicom(); test_daewoongpet(); print("PASS")
