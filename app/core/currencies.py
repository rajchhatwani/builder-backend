"""Currencies the payments module supports, and how many decimals their minor unit has.

Deliberately conservative. Left out on purpose, because a provider treats them as special cases that
a generic "multiply by 10^exponent" gets wrong: three-decimal currencies (BHD, JOD, KWD, OMR, TND:
Stripe wants amounts divisible by 10), and ISK, UGX, HUF, TWD (zero- or two-decimal depending on
whether you read ISO 4217 or the provider's rules). Adding one needs its own tests against the
provider, so it is a deliberate step, not a table edit.
"""

# ISO 4217 code -> number of decimals of the minor unit (2 = cents, 0 = no minor unit).
EXPONENTS: dict[str, int] = {
    # two decimals
    "AED": 2,
    "AUD": 2,
    "BGN": 2,
    "BRL": 2,
    "CAD": 2,
    "CHF": 2,
    "CZK": 2,
    "DKK": 2,
    "EUR": 2,
    "GBP": 2,
    "HKD": 2,
    "IDR": 2,
    "ILS": 2,
    "INR": 2,
    "MXN": 2,
    "MYR": 2,
    "NOK": 2,
    "NZD": 2,
    "PHP": 2,
    "PLN": 2,
    "RON": 2,
    "SAR": 2,
    "SEK": 2,
    "SGD": 2,
    "THB": 2,
    "TRY": 2,
    "USD": 2,
    "ZAR": 2,
    # no minor unit
    "CLP": 0,
    "JPY": 0,
    "KRW": 0,
    "PYG": 0,
    "RWF": 0,
    "VND": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
}

# Razorpay settles in INR; other currencies need international payments enabled on the account.
RAZORPAY_CURRENCIES = frozenset({"INR", "USD", "EUR", "GBP", "SGD", "AED", "AUD", "CAD", "HKD"})

# Largest single amount (minor units) accepted for each provider: both document an 8-digit cap.
PROVIDER_MAX_AMOUNT_MINOR = {"stripe": 99_999_999, "razorpay": 99_999_999}


def supported(provider: str) -> frozenset[str]:
    if provider == "razorpay":
        return RAZORPAY_CURRENCIES & frozenset(EXPONENTS)
    return frozenset(EXPONENTS)
