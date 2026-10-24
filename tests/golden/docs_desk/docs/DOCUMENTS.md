# PDF documents of Desk

Generated from the spec. The service renders PDFs (invoices, receipts, statements, certificates ...)
from **templates that are plain data**, with a small engine that draws the page directly. There is no
HTML, no browser and no expression language in the path, so a document can never fetch a URL, read a
file or run code.

## Templates in this project

| Id | Title | Needs | Who may render |
|---|---|---|---|
| `invoice` | Invoice | data in the request | admin, staff |
| `receipt` | Receipt | data in the request | admin, staff |
| `certificate` | Certificate | data in the request | admin |
| `ticket_summary` | Ticket summary | a stored Ticket record | customer, staff |

## Calling it

```bash
# what can I render?
curl -H "Authorization: Bearer $TOKEN" /documents

# Invoice: the data the placeholders read
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"data": {...}}' /documents/invoice/render -o invoice.pdf
# Receipt: the data the placeholders read
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"data": {...}}' /documents/receipt/render -o receipt.pdf
# Certificate: the data the placeholders read
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"data": {...}}' /documents/certificate/render -o certificate.pdf
# Ticket summary: the record's own values are available as row.<field>; `extra` adds more (never overrides row)
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"extra": {}}' /documents/ticket_summary/records/<record id> -o ticket_summary.pdf
```

Every route needs sign-in and one of the template's roles (an empty role list means nobody) and is rate
limited per client. A stored-record route applies the **same access rules as `GET` of that entity**: a
record the caller cannot read is a 404, never a PDF. Responses are `application/pdf` with
`Cache-Control: no-store`. Nothing about a document (its data or text) is logged, only the template id and
the size.

## Template format

`app/documents/data.py` holds each template as data: `page` (A4 or Letter, orientation, margin), optional
`header` and `footer` (`{{page}}` and `{{pages}}` give page numbers), and a list of `blocks`:

| Block | Fields |
|---|---|
| `heading` | `text`, `level` 1-3 |
| `paragraph` | `text` (a new line starts a new line) |
| `kv` | `rows`: `{label, value}` pairs |
| `table` | `source` (a list in the data), `columns`: `{header, value, align, width}`; each row's values are `{{item.field}}` |
| `totals` | `rows`: `{label, value}`, right aligned |
| `spacer`, `rule`, `page_break` | `height_mm` for the spacer |
| `image` | `data_base64` (PNG or JPEG), `width_mm`, `align` |
| `signature` | `text` under a signing line |
| `qr` | `value`, `size_mm` |

Placeholders are `{{ path.to.value }}` or `{{ path | formatter:argument }}`:

| Formatter | Does |
|---|---|
| `money:EUR` or `money:@currency` | `1,234.50 EUR` (the amount rounded half up to the currency's minor unit; `@currency` reads the code from the data) |
| `number` | `1,234.50` |
| `date` / `date:%d %B %Y` | formats an ISO date or time (codes `%Y %y %m %d %e %b %B %H %M %j`) |
| `upper`, `lower` | case |
| `default:text` | the text when the value is missing or empty |

A path looks things up in the data by name and by list position (`items.0.description`); it cannot call
anything. A missing value is empty. Whatever a placeholder resolves to is escaped before drawing, so data
containing `<b>` or `&` is printed as text and never interpreted.

## Totals are recomputed

For templates with a `compute` list (invoice, receipt, quote, purchase order), the engine computes
`totals.subtotal`, `totals.tax_total`, `totals.total` and `totals.tax_breakdown` from the line items
(`quantity`, `unit_price`, optional `discount`, `tax_rate` in percent) with exact decimal arithmetic. Tax is
computed per rate on the summed net amount and rounded half up to the currency's minor unit. **Any totals
sent by the caller are ignored.**

## Limits

At most 200 blocks, 500 rows per table and per list, 5000 characters per text, 50 pages,
200 KB per image (4000 pixels at most). Beyond a limit the request is refused with
`422 invalid_document`.

## Same input, same bytes

The output is deterministic (fixed metadata, no timestamps), so a stored document can be rendered again and
compared by hash. PDF bytes can change when the `reportlab` version changes: pin it for archival.

## What is not here

* **Structured e-invoices.** Several countries require an e-invoice in a structured format (Factur-X /
  ZUGFeRD, XRechnung, Peppol BIS) rather than a bare PDF; dates and thresholds differ by country and keep
  moving, so check the tax authority of the countries you invoice in. This engine produces the readable
  PDF only; embedding the XML (PDF/A-3) is not implemented.
* **PDF/A and tagged (accessible) PDF.** Not produced.
* **Fonts:** the Bitstream Vera family that ships with ReportLab. Latin scripts only. Arabic and Indic
  scripts need shaping and CJK needs glyph coverage; neither is supported.
* **Numbering:** this service does not assign invoice numbers. Where numbering must be gapless (some
  countries require it), allocate numbers in your own code inside a transaction and pass the number in.
* **Stored documents:** documents are rendered on request and not stored. To keep one, save the PDF with
  the file-upload feature or your own storage, together with the SHA-256 of the bytes.
