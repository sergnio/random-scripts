"""Exact 2025 Form 1040 line 16 tax, following the IRS Tax Table and the Qualified Dividends and Capital Gain Tax Worksheet."""
import math

# (top of bracket, rate)
BRACKETS = {
    "single": [(11_925, 0.10), (48_475, 0.12), (103_350, 0.22), (197_300, 0.24), (250_525, 0.32), (626_350, 0.35), (math.inf, 0.37)],
    "married_filing_jointly": [(23_850, 0.10), (96_950, 0.12), (206_700, 0.22), (394_600, 0.24), (501_050, 0.32), (751_600, 0.35), (math.inf, 0.37)],
    "married_filing_separately": [(11_925, 0.10), (48_475, 0.12), (103_350, 0.22), (197_300, 0.24), (250_525, 0.32), (375_800, 0.35), (math.inf, 0.37)],
    "head_of_household": [(17_000, 0.10), (64_850, 0.12), (103_350, 0.22), (197_300, 0.24), (250_500, 0.32), (626_350, 0.35), (math.inf, 0.37)],
}
BRACKETS["qualifying_surviving_spouse"] = BRACKETS["married_filing_jointly"]

# (top of 0% rate, top of 15% rate) for qualified dividends and long-term capital gains
CAPITAL_GAIN_THRESHOLDS = {
    "single": (48_350, 533_400),
    "married_filing_jointly": (96_700, 600_050),
    "married_filing_separately": (48_350, 300_000),
    "head_of_household": (64_750, 566_700),
    "qualifying_surviving_spouse": (96_700, 600_050),
}
FILING_STATUSES = sorted(BRACKETS)


def _round_dollars(amount):
    return int(math.floor(amount + 0.5))


def _bracket_tax(income, brackets):
    tax, bottom = 0.0, 0
    for top, rate in brackets:
        if income <= bottom:
            break
        tax += (min(income, top) - bottom) * rate
        bottom = top
    return tax


def _tax_table_midpoint(income):
    if income < 5:
        return 2.5
    if income < 25:
        return 10 if income < 15 else 20
    row_width = 25 if income < 3_000 else 50
    return income // row_width * row_width + row_width / 2


def regular_tax(taxable_income, filing_status):
    """Tax Table below $100,000 (tax at the middle of each row), Tax Computation Worksheet at or above."""
    income = taxable_income if taxable_income >= 100_000 else _tax_table_midpoint(taxable_income)
    return _round_dollars(_bracket_tax(income, BRACKETS[filing_status]))


def line_16_tax(filing_status, taxable_income, qualified_dividends_and_capital_gain=0):
    taxable_income = max(0, int(taxable_income))
    preferential = min(max(0, qualified_dividends_and_capital_gain), taxable_income)
    ordinary = taxable_income - preferential
    zero_rate_top, fifteen_rate_top = CAPITAL_GAIN_THRESHOLDS[filing_status]

    taxed_at_0 = max(0, min(taxable_income, zero_rate_top) - ordinary)
    taxed_at_15 = min(preferential - taxed_at_0, max(0, min(taxable_income, fifteen_rate_top) - ordinary - taxed_at_0))
    taxed_at_20 = preferential - taxed_at_0 - taxed_at_15
    worksheet_tax = taxed_at_15 * 0.15 + taxed_at_20 * 0.20 + regular_tax(ordinary, filing_status)
    tax_without_worksheet = regular_tax(taxable_income, filing_status)

    return {
        "line_16_tax": min(_round_dollars(worksheet_tax), tax_without_worksheet),
        "ordinary_income": ordinary,
        "qualified_dividends_and_capital_gain_taxed_at_0_percent": taxed_at_0,
        "taxed_at_15_percent": taxed_at_15,
        "taxed_at_20_percent": taxed_at_20,
        "method": "IRS Tax Table" if taxable_income < 100_000 else "Tax Computation Worksheet",
        "note": "Does not cover the Schedule D Tax Worksheet (28% collectibles gain or unrecaptured section 1250 gain), Form 8615 (kiddie tax), or foreign earned income exclusion.",
    }
