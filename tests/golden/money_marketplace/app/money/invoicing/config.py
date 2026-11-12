"""Invoicing settings (generated from the spec: change them in the builder). Plain data, integers only."""

# who may read / write; an empty tuple means any signed-in user
READ_ROLES: tuple[str, ...] = ('admin', 'member',)
WRITE_ROLES: tuple[str, ...] = ('admin',)
NUMBER_PREFIX = "MKT-"
PAYMENT_TERMS_DAYS = 14
AGING_BUCKETS_DAYS: tuple[int, ...] = (30, 60, 90, )
# ledger account codes. For a currency other than the plain code's own, the account is `<code>.<CUR>`.
RECEIVABLE_ACCOUNT = "receivables"
PAYABLE_ACCOUNT = "payables"
REVENUE_ACCOUNT = "sales"
EXPENSE_ACCOUNT = "expenses"
TAX_ACCOUNT = "tax"
CASH_ACCOUNT = "bank"
COMMISSION_BP = 1250  # the platform's share of a payout, in basis points
SELLER_PAYABLE_ACCOUNT = "seller_payable"
COMMISSION_ACCOUNT = "commission"
MAX_AMOUNT_MINOR = 2**53 - 1
MAX_LINES = 200
MULTI_TENANT = True
