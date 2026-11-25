from fractions import Fraction

import pytest

from logic.errors import BusinessError
from logic.identifiers import imei_check_digit, luhn_valid, normalize_identifier, split_identifiers, validate_identifier
from logic.money import allocate, money, percent_of, round_half_up


def test_round_half_up_rounds_halves_away_from_banker_rounding():
    assert round_half_up(Fraction(21, 2)) == 11  # 10.5 -> 11, not 10
    assert round_half_up(Fraction(20, 4)) == 5
    assert round_half_up(12.5) == 13


def test_percent_of_uses_exact_arithmetic():
    assert percent_of(105, 10) == 11
    assert percent_of(1000, 12.5) == 125
    assert percent_of(9_198_000, 10) == 919_800


@pytest.mark.parametrize(
    "total, weights",
    [
        (100, [1, 1, 1]),
        (10, [3, 7]),
        (1, [5, 5, 5, 5]),
        (999_999, [4_599_000, 299_000, 299_000]),
        (7, [0, 2, 0, 5]),
    ],
)
def test_allocate_always_sums_exactly_to_total(total, weights):
    shares = allocate(total, weights)
    assert sum(shares) == total
    assert all(s >= 0 for s in shares)
    for share, weight in zip(shares, weights):
        if weight == 0:
            assert share == 0


def test_money_formats_indonesian_style():
    assert money(4_599_000) == "Rp 4.599.000"
    assert money(-5_000) == "-Rp 5.000"
    assert money(0) == "Rp 0"


def test_known_valid_imei_passes_luhn_and_validation():
    assert luhn_valid("490154203237518")
    assert validate_identifier("490154203237518", "imei") == "490154203237518"
    assert not luhn_valid("490154203237519")


def test_bad_imei_checksum_is_rejected():
    with pytest.raises(BusinessError, match="checksum"):
        validate_identifier("490154203237519", "imei")


def test_imei_must_be_fifteen_digits():
    with pytest.raises(BusinessError, match="15 digits"):
        validate_identifier("12345", "imei")


def test_check_digit_helper_round_trips():
    body = "49015420323751"
    assert imei_check_digit(body) == 8
    assert luhn_valid(body + str(imei_check_digit(body)))


def test_normalize_identifier_strips_imei_spacing_and_upcases_serials():
    assert normalize_identifier(" 4901 5420-3237 518 ", "imei") == "490154203237518"
    assert normalize_identifier(" c9x2k7m4qd ", "serial") == "C9X2K7M4QD"


def test_serial_format_is_checked():
    assert validate_identifier("C9X2K7M4QD", "serial") == "C9X2K7M4QD"
    with pytest.raises(BusinessError):
        validate_identifier("a!", "serial")


def test_split_identifiers_accepts_lines_commas_and_semicolons():
    assert split_identifiers("A1B2C3D4\nE5F6G7H8, J9K1L2M3;  \n") == ["A1B2C3D4", "E5F6G7H8", "J9K1L2M3"]
