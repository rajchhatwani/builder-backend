"""The ten built-in document templates, with the reasoning for each and sample data for previews.

A template is the plain-data structure `doc_engine` renders. Picking one in the dashboard copies it into
the project's spec, where it can be edited freely; nothing here is referenced at run time.

Why these ten (research notes, 2026-10-24): documents that applications generate most are the ones a
transaction leaves behind. Billing and commerce lead (invoices, receipts, quotes, purchase orders,
packing slips) because every SaaS subscription, marketplace, web shop and field-service app has to give
customers and accountants a record; logistics adds packing slips and labels; fintech and utilities add
statements; education and HR add certificates and letters; events and travel add tickets; operations and
analytics add reports. Invoices are the document under regulatory pressure: e-invoicing mandates are
being phased in across Europe (Belgium from 2026, France from September 2026 for large and mid-sized
companies, Poland's KSeF in 2026, Germany's receiving duty since 2025 with sending duties from 2027
and 2028) and in India (GST e-invoice). Many of those regimes need a *structured* invoice (XML, for
example Factur-X, ZUGFeRD, XRechnung or Peppol) rather than a bare PDF. This engine produces the
human-readable PDF only; embedding the XML (PDF/A-3) is a documented follow-up, see MASTER_PLAN.md L40.
Dates and thresholds differ by source: check the tax authority of the countries you sell in.
"""

import copy
from typing import Any

PARTIES = [
    {"label": "From", "value": "{{seller.name}}\n{{seller.address}}\n{{seller.tax_id}}"},
    {"label": "To", "value": "{{buyer.name}}\n{{buyer.address}}\n{{buyer.tax_id}}"},
]

LINE_ITEMS: dict[str, Any] = {
    "type": "table",
    "source": "items",
    "columns": [
        {"header": "Description", "value": "{{item.description}}", "width": 5},
        {"header": "Qty", "value": "{{item.quantity | number}}", "align": "right", "width": 1},
        {
            "header": "Unit price",
            "value": "{{item.unit_price | money:@currency}}",
            "align": "right",
            "width": 2,
        },
        {"header": "Tax %", "value": "{{item.tax_rate | default:0}}", "align": "right", "width": 1},
        {
            "header": "Amount",
            "value": "{{item.line_total | money:@currency}}",
            "align": "right",
            "width": 2,
        },
    ],
}

MONEY_TOTALS: dict[str, Any] = {
    "type": "totals",
    "rows": [
        {"label": "Subtotal", "value": "{{totals.subtotal | money:@currency}}"},
        {"label": "Tax", "value": "{{totals.tax_total | money:@currency}}"},
        {"label": "Total", "value": "{{totals.total | money:@currency}}"},
    ],
}

SELLER = {
    "name": "Northwind Trading Ltd",
    "address": "12 Harbour Road, Dublin 2, Ireland",
    "tax_id": "VAT IE1234567X",
}
BUYER = {
    "name": "Contoso GmbH",
    "address": "Hauptstrasse 5, 10115 Berlin, Germany",
    "tax_id": "VAT DE123456789",
}
ITEMS = [
    {
        "description": "Annual subscription, Team plan",
        "quantity": 1,
        "unit_price": "1200.00",
        "tax_rate": 23,
    },
    {
        "description": "Onboarding workshop (2 hours)",
        "quantity": 2,
        "unit_price": "150.00",
        "tax_rate": 23,
    },
    {"description": "Extra seats", "quantity": 5, "unit_price": "19.90", "tax_rate": 23},
]


def _page(**extra: Any) -> dict[str, Any]:
    return {"size": "A4", "orientation": "portrait", "margin_mm": 18, **extra}


LIBRARY: dict[str, dict[str, Any]] = {
    "invoice": {
        "title": "Invoice",
        "industries": ["SaaS", "Services", "Marketplaces", "Field service", "Healthcare billing"],
        "why": "The legal record of a sale. Numbered, dated, with tax shown per rate; many countries now "
        "also require a structured e-invoice alongside the PDF.",
        "compute": "items",
        "template": {
            "title": "Invoice {{number}}",
            "page": _page(),
            "footer": "{{seller.name}} - page {{page}} of {{pages}}",
            "blocks": [
                {"type": "heading", "text": "Invoice {{number}}"},
                {
                    "type": "kv",
                    "rows": [
                        {"label": "Issue date", "value": "{{issue_date | date:%d %B %Y}}"},
                        {"label": "Due date", "value": "{{due_date | date:%d %B %Y}}"},
                        {"label": "Reference", "value": "{{reference}}"},
                    ],
                },
                {"type": "kv", "rows": PARTIES},
                {"type": "rule"},
                LINE_ITEMS,
                MONEY_TOTALS,
                {
                    "type": "paragraph",
                    "text": "Payment terms: {{payment_terms | default:Due within 30 days}}.",
                },
                {"type": "paragraph", "text": "{{notes}}"},
            ],
        },
        "sample": {
            "number": "INV-2026-0042",
            "issue_date": "2026-10-24",
            "due_date": "2026-11-23",
            "reference": "PO 7781",
            "currency": "EUR",
            "seller": SELLER,
            "buyer": BUYER,
            "items": ITEMS,
            "payment_terms": "Due within 30 days, bank transfer",
            "notes": "Thank you for your business.",
        },
    },
    "receipt": {
        "title": "Receipt",
        "industries": ["Retail", "Hospitality", "Subscriptions", "Donations"],
        "why": "Proof of payment, usually smaller and faster than an invoice; customers expect one by email.",
        "compute": "items",
        "template": {
            "title": "Receipt {{number}}",
            "page": _page(margin_mm=14),
            "blocks": [
                {"type": "heading", "text": "Receipt", "level": 1},
                {
                    "type": "kv",
                    "rows": [
                        {"label": "Receipt no.", "value": "{{number}}"},
                        {"label": "Paid on", "value": "{{paid_at | date:%d %B %Y %H:%M}}"},
                        {"label": "Method", "value": "{{payment_method}}"},
                        {"label": "Received from", "value": "{{buyer.name}}"},
                    ],
                },
                LINE_ITEMS,
                MONEY_TOTALS,
                {"type": "paragraph", "text": "Paid in full. {{seller.name}}, {{seller.tax_id}}."},
            ],
        },
        "sample": {
            "number": "R-90211",
            "paid_at": "2026-10-24T14:32:00",
            "payment_method": "Card ending 4242",
            "currency": "EUR",
            "seller": SELLER,
            "buyer": BUYER,
            "items": ITEMS[:2],
        },
    },
    "quote": {
        "title": "Quote",
        "industries": ["Agencies", "Construction", "Manufacturing", "IT services"],
        "why": "A priced offer that becomes an order when accepted: validity date, terms and an acceptance line.",
        "compute": "items",
        "template": {
            "title": "Quote {{number}}",
            "page": _page(),
            "footer": "Quote {{number}} - page {{page}} of {{pages}}",
            "blocks": [
                {"type": "heading", "text": "Quote {{number}}"},
                {
                    "type": "kv",
                    "rows": [
                        {"label": "Prepared for", "value": "{{buyer.name}}"},
                        {"label": "Date", "value": "{{issue_date | date:%d %B %Y}}"},
                        {"label": "Valid until", "value": "{{valid_until | date:%d %B %Y}}"},
                    ],
                },
                LINE_ITEMS,
                MONEY_TOTALS,
                {
                    "type": "paragraph",
                    "text": "{{terms | default:Prices exclude delivery. Work starts on written acceptance.}}",
                },
                {"type": "signature", "text": "Accepted by (name, signature, date)"},
            ],
        },
        "sample": {
            "number": "Q-2026-118",
            "issue_date": "2026-10-24",
            "valid_until": "2026-11-24",
            "currency": "EUR",
            "seller": SELLER,
            "buyer": BUYER,
            "items": ITEMS,
        },
    },
    "purchase_order": {
        "title": "Purchase order",
        "industries": ["Procurement", "Manufacturing", "Retail", "Construction"],
        "why": "Commits the buyer to an order before delivery; the number is quoted on the supplier's invoice.",
        "compute": "items",
        "template": {
            "title": "Purchase order {{number}}",
            "page": _page(),
            "blocks": [
                {"type": "heading", "text": "Purchase order {{number}}"},
                {
                    "type": "kv",
                    "rows": [
                        {"label": "Order date", "value": "{{issue_date | date:%d %B %Y}}"},
                        {"label": "Vendor", "value": "{{seller.name}}\n{{seller.address}}"},
                        {"label": "Ship to", "value": "{{buyer.name}}\n{{buyer.address}}"},
                        {"label": "Delivery by", "value": "{{delivery_date | date:%d %B %Y}}"},
                    ],
                },
                LINE_ITEMS,
                MONEY_TOTALS,
                {"type": "signature", "text": "Authorised by"},
            ],
        },
        "sample": {
            "number": "PO-5530",
            "issue_date": "2026-10-24",
            "delivery_date": "2026-11-10",
            "currency": "EUR",
            "seller": SELLER,
            "buyer": BUYER,
            "items": ITEMS,
        },
    },
    "packing_slip": {
        "title": "Packing slip",
        "industries": ["E-commerce", "Logistics", "Wholesale"],
        "why": "Goes in the box: what was shipped, to whom, without prices. A QR code links the parcel to its record.",
        "compute": None,
        "template": {
            "title": "Packing slip {{order_number}}",
            "page": _page(),
            "blocks": [
                {"type": "heading", "text": "Packing slip"},
                {
                    "type": "kv",
                    "rows": [
                        {"label": "Order", "value": "{{order_number}}"},
                        {"label": "Ship to", "value": "{{ship_to.name}}\n{{ship_to.address}}"},
                        {"label": "Carrier", "value": "{{carrier}}"},
                        {"label": "Tracking", "value": "{{tracking}}"},
                    ],
                },
                {
                    "type": "table",
                    "source": "items",
                    "columns": [
                        {"header": "SKU", "value": "{{item.sku}}", "width": 2},
                        {"header": "Item", "value": "{{item.description}}", "width": 5},
                        {
                            "header": "Qty",
                            "value": "{{item.quantity}}",
                            "align": "right",
                            "width": 1,
                        },
                    ],
                },
                {"type": "qr", "value": "{{tracking}}"},
            ],
        },
        "sample": {
            "order_number": "SO-33120",
            "carrier": "DHL Express",
            "tracking": "JD014600003SE",
            "ship_to": {"name": "Contoso GmbH", "address": "Hauptstrasse 5, 10115 Berlin"},
            "items": [
                {"sku": "TS-001", "description": "T-shirt, blue, M", "quantity": 2},
                {"sku": "MG-114", "description": "Mug, white", "quantity": 4},
            ],
        },
    },
    "statement": {
        "title": "Account statement",
        "industries": ["Banking", "Fintech", "Utilities", "B2B credit"],
        "why": "A period summary with opening and closing balance; customers and auditors reconcile against it.",
        "compute": None,
        "template": {
            "title": "Statement {{period}}",
            "page": _page(),
            "footer": "Statement {{period}} - page {{page}} of {{pages}}",
            "blocks": [
                {"type": "heading", "text": "Statement {{period}}"},
                {
                    "type": "kv",
                    "rows": [
                        {"label": "Account", "value": "{{account.name}} ({{account.number}})"},
                        {
                            "label": "Opening balance",
                            "value": "{{opening_balance | money:@currency}}",
                        },
                        {
                            "label": "Closing balance",
                            "value": "{{closing_balance | money:@currency}}",
                        },
                    ],
                },
                {
                    "type": "table",
                    "source": "transactions",
                    "columns": [
                        {"header": "Date", "value": "{{item.date | date}}", "width": 2},
                        {"header": "Description", "value": "{{item.description}}", "width": 5},
                        {
                            "header": "Amount",
                            "value": "{{item.amount | money:@currency}}",
                            "align": "right",
                            "width": 2,
                        },
                        {
                            "header": "Balance",
                            "value": "{{item.balance | money:@currency}}",
                            "align": "right",
                            "width": 2,
                        },
                    ],
                },
            ],
        },
        "sample": {
            "period": "October 2026",
            "currency": "EUR",
            "account": {"name": "Contoso GmbH", "number": "DE89 3704 0044 0532 0130 00"},
            "opening_balance": "1250.00",
            "closing_balance": "2189.50",
            "transactions": [
                {
                    "date": "2026-10-03",
                    "description": "Invoice INV-2026-0042",
                    "amount": "1980.00",
                    "balance": "3230.00",
                },
                {
                    "date": "2026-10-11",
                    "description": "Card payment",
                    "amount": "-640.50",
                    "balance": "2589.50",
                },
                {
                    "date": "2026-10-20",
                    "description": "Refund",
                    "amount": "-400.00",
                    "balance": "2189.50",
                },
            ],
        },
    },
    "certificate": {
        "title": "Certificate",
        "industries": ["Education", "Training", "HR", "Events"],
        "why": "Issued once, shown many times: a recipient, an achievement, a signature, and a QR code to verify it.",
        "compute": None,
        "template": {
            "title": "Certificate for {{recipient}}",
            "page": _page(orientation="landscape", margin_mm=24),
            "blocks": [
                {"type": "spacer", "height_mm": 14},
                {"type": "heading", "text": "Certificate of completion", "level": 1},
                {"type": "paragraph", "text": "This certifies that"},
                {"type": "heading", "text": "{{recipient}}", "level": 2},
                {
                    "type": "paragraph",
                    "text": "has successfully completed {{course}} on {{completed_on | date:%d %B %Y}}.",
                },
                {"type": "spacer", "height_mm": 12},
                {"type": "signature", "text": "{{issuer}}"},
                {"type": "qr", "value": "{{verify_url}}", "size_mm": 24},
            ],
        },
        "sample": {
            "recipient": "Priya Sharma",
            "course": "Advanced Data Modelling",
            "completed_on": "2026-10-20",
            "issuer": "Northwind Academy",
            "verify_url": "https://example.com/verify/9f3a2c",
        },
    },
    "report": {
        "title": "Report",
        "industries": ["Analytics", "Operations", "Healthcare", "Finance"],
        "why": "A summary of figures for a period or a case, to read, archive or send on.",
        "compute": None,
        "template": {
            "title": "{{title}}",
            "page": _page(),
            "header": "{{organisation}}",
            "footer": "{{title}} - page {{page}} of {{pages}}",
            "blocks": [
                {"type": "heading", "text": "{{title}}"},
                {"type": "paragraph", "text": "{{summary}}"},
                {
                    "type": "kv",
                    "rows": [
                        {"label": "Period", "value": "{{period}}"},
                        {"label": "Prepared by", "value": "{{author}}"},
                    ],
                },
                {"type": "rule"},
                {
                    "type": "table",
                    "source": "rows",
                    "columns": [
                        {"header": "Metric", "value": "{{item.metric}}", "width": 4},
                        {
                            "header": "Value",
                            "value": "{{item.value}}",
                            "align": "right",
                            "width": 2,
                        },
                        {
                            "header": "Change",
                            "value": "{{item.change}}",
                            "align": "right",
                            "width": 2,
                        },
                    ],
                },
            ],
        },
        "sample": {
            "title": "Quarterly operations report",
            "organisation": "Northwind Trading Ltd",
            "summary": "Orders grew in all regions. Delivery times improved after the new warehouse opened.",
            "period": "Q3 2026",
            "author": "Operations team",
            "rows": [
                {"metric": "Orders", "value": "12,480", "change": "+8.2%"},
                {"metric": "On-time delivery", "value": "96.4%", "change": "+1.9 pts"},
                {"metric": "Returns", "value": "2.1%", "change": "-0.3 pts"},
            ],
        },
    },
    "letter": {
        "title": "Letter",
        "industries": ["Legal", "HR", "Government", "Any customer communication"],
        "why": "Formal correspondence: offer letters, notices, confirmations; plain text blocks with a signature.",
        "compute": None,
        "template": {
            "title": "{{subject}}",
            "page": _page(margin_mm=25),
            "blocks": [
                {"type": "paragraph", "text": "{{sender.name}}\n{{sender.address}}"},
                {"type": "spacer", "height_mm": 8},
                {"type": "paragraph", "text": "{{recipient.name}}\n{{recipient.address}}"},
                {"type": "spacer", "height_mm": 8},
                {"type": "paragraph", "text": "{{date | date:%d %B %Y}}"},
                {"type": "heading", "text": "{{subject}}", "level": 3},
                {"type": "paragraph", "text": "{{body}}"},
                {"type": "paragraph", "text": "Kind regards,"},
                {"type": "signature", "text": "{{sender.name}}"},
            ],
        },
        "sample": {
            "sender": {"name": "Northwind Trading Ltd", "address": "12 Harbour Road, Dublin 2"},
            "recipient": {"name": "Priya Sharma", "address": "4 Park Lane, Cork"},
            "date": "2026-10-24",
            "subject": "Confirmation of your appointment",
            "body": "We are pleased to confirm your appointment as Data Analyst, starting on 2 November 2026.\n\nPlease bring a photo ID on your first day.",
        },
    },
    "ticket": {
        "title": "Ticket",
        "industries": ["Events", "Travel", "Venues", "Transport"],
        "why": "A scannable proof of entry: who, what, when, where, and a QR code the door can check.",
        "compute": None,
        "template": {
            "title": "Ticket {{ticket_no}}",
            "page": _page(size="A4", margin_mm=30),
            "blocks": [
                {"type": "heading", "text": "{{event}}"},
                {
                    "type": "kv",
                    "rows": [
                        {"label": "Date", "value": "{{starts_at | date:%d %B %Y, %H:%M}}"},
                        {"label": "Venue", "value": "{{venue}}"},
                        {"label": "Holder", "value": "{{holder}}"},
                        {"label": "Seat", "value": "{{seat | default:General admission}}"},
                        {"label": "Ticket", "value": "{{ticket_no}}"},
                    ],
                },
                {"type": "qr", "value": "{{ticket_no}}", "size_mm": 45},
                {
                    "type": "paragraph",
                    "text": "Show this code at the entrance. One entry per ticket.",
                },
            ],
        },
        "sample": {
            "event": "Autumn Jazz Night",
            "starts_at": "2026-11-14T20:00:00",
            "venue": "Town Hall, Main Street",
            "holder": "Priya Sharma",
            "seat": "Row C, seat 12",
            "ticket_no": "TKT-7F2A-9931",
        },
    },
}


def get(template_id: str) -> dict[str, Any]:
    """A deep copy of one library entry (callers may edit it)."""
    return copy.deepcopy(LIBRARY[template_id])


def catalogue() -> list[dict[str, Any]]:
    """What the dashboard shows in its gallery."""
    return [
        {
            "id": key,
            "title": entry["title"],
            "industries": entry["industries"],
            "why": entry["why"],
            "compute": entry["compute"],
        }
        for key, entry in LIBRARY.items()
    ]
