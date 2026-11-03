# Synthetic PO for output.pdf

`PO-AD4-005.pdf` is a **synthetic demonstration PO**, created from the visible supplier and three item rows in `../output.pdf`. It is not evidence that Green1 Materials LLC issued or approved a real order.

| Item | Quantity | Unit price | Amount |
| --- | ---: | ---: | ---: |
| Desktop furniture | 1 | 232.00 | 232.00 |
| Plumbing and electrical services | 2 | 514.00 | 1,028.00 |
| Water tank repair works | 2 | 152.00 | 304.00 |
| **Total** | | | **1,564.00** |

The PO uses USD as a synthetic assumption because the invoice shows only `$`, which does not establish an ISO currency code. It uses gross amount basis, since the invoice states a total of 1,564.00 but does not state tax. The invoice has no PO reference, so the app must not automatically match it to this PO. `ad4tech-vendor.json` is an equally synthetic vendor-master record used only to exercise identity checks.

The source invoice is dated 22 June 2021, so the app's current 365-day invoice-age policy should require clarification. The source also shows 232.00 paid and 1,332.00 balance due; those are payment-status details, not the invoice total.
