# Physical sample PDFs for invoice review

**All identities, accounts, invoices, orders, and amounts are synthetic.**

Generated on **2026-10-31**: **31 invoice PDFs + 2 alternative PO PDFs**.

## Load the sample pack

1. Start the app with `./run.sh` and use an empty workspace. Do not also load the built-in 13-example demo: its reference IDs overlap this pack.
2. Upload `vendors/approved-vendors.json` under **Vendor master**.
3. Upload `purchase_orders/purchase-orders.json` under **Purchase orders**.
4. Upload `history/previous-invoices.json` under **Invoice history**.
5. Upload `policy/ap-policy.json` under **Company policy**.
6. Upload `invoices/01-...pdf` through `25-...pdf` in ascending filename order (25 files maximum per upload), then cases 26-31.
7. Review fields, original PDFs, source evidence, checks, and recommendations.

For isolated tests, use the same reference files and upload a selected invoice. Cases 11/12 depend on earlier ready invoices, and case 24 depends on case 14. The manifest records results for the complete ordered batch.

**Protected-PDF test:** case 26 is intentionally encrypted with password `sample123`. The current app should reject the locked upload with an actionable message. The password is for manual inspection; do not unlock it before testing that behavior.

**Alternative PO PDFs:** `po-pdf-alternatives/` contains native PDF versions of PO-F014 and PO-F019. They duplicate two entries in the JSON PO master. To test them, omit those two rows from a copy of the JSON master, or use the relevant PDF in a separate empty workspace. Uploading both representations should produce a duplicate-reference error.

## Cases and verified local behavior

Results below were obtained using local text extraction/OCR with the optional LLM disabled. OCR output can vary across runtime versions. A mismatch is a documented extraction limitation, not a corrected ground truth.

| PDF | Format / test | Intended outcome | Observed local outcome |
| --- | --- | --- | --- |
| [01-ready.pdf](invoices/01-ready.pdf) | Valid invoice; exact vendor, PO, line, and arithmetic checks. | ready | ready |
| [02-within-tolerance.pdf](invoices/02-within-tolerance.pdf) | Valid invoice; exact vendor, PO, line, and arithmetic checks. | ready | ready |
| [03-duplicate.pdf](invoices/03-duplicate.pdf) | Duplicate, blocked vendor, or changed bank account. | hold | hold |
| [04-blocked-vendor.pdf](invoices/04-blocked-vendor.pdf) | Duplicate, blocked vendor, or changed bank account. | hold | hold |
| [05-bank-changed.pdf](invoices/05-bank-changed.pdf) | Duplicate, blocked vendor, or changed bank account. | hold | hold |
| [06-missing-po.pdf](invoices/06-missing-po.pdf) | Missing identifiers or inconsistent amounts. | clarification | clarification |
| [07-over-po-balance.pdf](invoices/07-over-po-balance.pdf) | PO capacity, quantity, or unit-price discrepancy. | procurement | procurement |
| [08-rate-mismatch.pdf](invoices/08-rate-mismatch.pdf) | PO capacity, quantity, or unit-price discrepancy. | procurement | procurement |
| [09-missing-number.pdf](invoices/09-missing-number.pdf) | Missing identifiers or inconsistent amounts. | clarification | clarification |
| [10-tax-discrepancy.pdf](invoices/10-tax-discrepancy.pdf) | Missing identifiers or inconsistent amounts. | clarification | clarification |
| [11-partial-invoice.pdf](invoices/11-partial-invoice.pdf) | Valid invoice; exact vendor, PO, line, and arithmetic checks. | ready | ready |
| [12-batch-capacity.pdf](invoices/12-batch-capacity.pdf) | PO capacity, quantity, or unit-price discrepancy. | procurement | procurement |
| [13-scanned-invoice.pdf](invoices/13-scanned-invoice.pdf) | Image-only PDF: OCR must be verified by a human. | clarification | clarification |
| [14-positioned-table.pdf](invoices/14-positioned-table.pdf) | Native PDF with a real positioned item table and separate columns. | ready | ready |
| [15-three-page-invoice.pdf](invoices/15-three-page-invoice.pdf) | Identity on page 1, item schedule on page 2, totals on page 3. | ready | ready |
| [16-mixed-text-and-scan.pdf](invoices/16-mixed-text-and-scan.pdf) | Native cover page with scanned item/totals page; per-page extraction. | clarification | clarification |
| [17-low-contrast-scan.pdf](invoices/17-low-contrast-scan.pdf) | Faded grayscale scan intentionally tests OCR uncertainty. | clarification | clarification |
| [18-sideways-scan.pdf](invoices/18-sideways-scan.pdf) | Image rotated 90 degrees; manual rotation/verification may be needed. | clarification | hold **(limitation)** |
| [19-tax-inclusive-gross-po.pdf](invoices/19-tax-inclusive-gross-po.pdf) | Gross PO and tax-inclusive line rate use the same comparison basis. | ready | ready |
| [20-cgst-sgst-components.pdf](invoices/20-cgst-sgst-components.pdf) | CGST 9% plus SGST 9% must sum to the explicit tax amount. | ready | ready |
| [21-currency-mismatch.pdf](invoices/21-currency-mismatch.pdf) | USD invoice against INR purchase order; no implicit conversion. | procurement | procurement |
| [22-ambiguous-numeric-date.pdf](invoices/22-ambiguous-numeric-date.pdf) | 01/02/2026 is ambiguous; date locale must be confirmed. | clarification | clarification |
| [23-different-item-description.pdf](invoices/23-different-item-description.pdf) | Same amounts but different item wording; equivalence requires review. | procurement | procurement |
| [24-identical-resubmission.pdf](invoices/24-identical-resubmission.pdf) | Exact byte-for-byte duplicate of case 14, submitted under another filename. | hold | hold |
| [25-blank-document.pdf](invoices/25-blank-document.pdf) | A valid empty PDF page; no fields may be invented. | clarification | clarification |
| [26-password-protected.pdf](invoices/26-password-protected.pdf) | Encrypted PDF. Expected upload error; password is sample123. | upload_rejected | upload_rejected |
| [27-missing-invoice-date.pdf](invoices/27-missing-invoice-date.pdf) | Invoice date deliberately omitted. | clarification | clarification |
| [28-credit-note.pdf](invoices/28-credit-note.pdf) | Negative credit-note amounts require a separate workflow. | clarification | clarification |
| [29-unregistered-vendor.pdf](invoices/29-unregistered-vendor.pdf) | Vendor absent from approved master and PO reference missing. | clarification | clarification |
| [30-cancelled-po.pdf](invoices/30-cancelled-po.pdf) | PO exists but is cancelled; valid amounts are insufficient. | procurement | procurement |
| [31-two-column-metadata.pdf](invoices/31-two-column-metadata.pdf) | Difficult two-column metadata layout; semantically valid invoice. Exposes local-parser limitations. | ready | clarification **(limitation)** |

## Ground truth and evidence

`expected-results.json` contains intended and observed outcomes, unresolved check codes, original field truth for authored invoices, file hashes, and upload errors. Case 24 is a byte-for-byte copy of case 14. Case 25 intentionally has no content.

The low-contrast and sideways scans are intentionally degraded test inputs. They must not be silently treated as verified. The two-column example is deliberately difficult for the local parser; compare its extraction against the PDF before interpreting vendor-conflict alerts.

## Regenerate

From the project directory:

```bash
uv pip install --python .venv/bin/python -r scripts/requirements-samples.txt
.venv/bin/python scripts/generate_sample_data.py
```

The generator refreshes dates, rewrites these named synthetic fixtures, recomputes observed outcomes in a temporary workspace, and rebuilds the ZIP. It does not read or change your live AP workspace.

Regenerate after a year or whenever you want fresh invoice/PO dates. Use `ledger-sample-test-cases.zip` to move the complete pack to another machine.
