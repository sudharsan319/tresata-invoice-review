# output.pdf + synthetic PO test

Tested in the local app on 2026-11-03. The uploaded PO is `PO-AD4-005.pdf` (document `c9699e44-c01e-426d-9968-53e3caa29a46`); the uploaded invoice is `output.pdf` (document `6399107b-9917-4ad9-8386-2f5a8e2154bf`). The PO is a synthetic demonstration record and is marked as such in the PDF.

OpenRouter vision and field extraction both completed on the final invoice reprocessing run. OpenRouter vision supplied the three correctly named item rows. The saved extraction has invoice number `INV-005`, supplier `Ad4tech Material LLC`, date `2021-06-22`, due date `2021-06-27`, and subtotal and total `1564.00`. The due date came from the local OCR fallback because the model did not provide a usable source quote for it.

| Item | Quantity | Unit price | Amount |
| --- | ---: | ---: | ---: |
| Desktop furniture | 1 | 232.00 | 232.00 |
| Plumbing and electrical services | 2 | 514.00 | 1028.00 |
| Water tank repair works | 2 | 152.00 | 304.00 |

The lines sum to `1564.00`, matching both the invoice subtotal/total and the synthetic PO. The invoice separately shows `232.00` paid and `1332.00` balance due; those payment figures were not treated as the invoice total.

The saved recommendation is **Needs clarification**. The invoice has no PO number, so `PO-AD4-005` appears as a candidate and is not automatically matched. It uses `$` without an ISO currency code, does not explicitly state tax, is older than the app's 365-day policy, and needs visual verification because it is scanned. There is no approved vendor-master record for Ad4tech in the workspace, so vendor identity and the duplicate check remain unresolved. The invoice's unlabeled `576832` and `Pay Cheque to John Doe` were correctly left out of the vendor-ID and bank-account fields after field validation was tightened.

The PO's USD currency, validity dates, and approved status are synthetic test assumptions. The invoice itself does not prove them or prove that this PO belongs to it.
