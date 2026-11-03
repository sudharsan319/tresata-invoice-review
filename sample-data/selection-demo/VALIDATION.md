# Selection demo verification — 3 November 2026

## Result

The four purchase orders and six invoices in the local app match the supplied synthetic PDFs. All arithmetic and all six recommendations are correct for this dataset. The dashboard's INR 30,120 total is the sum of **all six gross invoice totals**, including the invoice sent to procurement and the scanned invoice needing clarification.

The audit compared the app's stored SHA-256 hashes with the source PDFs, checked the visible/source text and the scanned page, compared extracted values with the originals, and independently recalculated invoice totals and cumulative PO usage with decimal arithmetic.

## Purchase orders

| PO | Vendor | Authorized net amount | PO line | Invoice use |
| --- | --- | ---: | --- | --- |
| PO-SEL-001 | Aster Cloud Ltd | INR 10,000 | 10 software seats × INR 1,000 | 10 seats / INR 10,000; fully used |
| PO-SEL-002 | Aster Cloud Ltd | INR 4,000 | 8 support hours × INR 500 | 4 hours / INR 2,000; INR 2,000 left |
| PO-SEL-003 | Blueleaf Office Supplies | INR 1,800 | 6 office supply kits × INR 300 | 6 kits / INR 1,800 claimed; awaiting scan review |
| PO-SEL-004 | Cedar Logistics Pvt Ltd | INR 10,000 | 5 delivery trips × INR 2,000 | 6 trips / INR 12,000 claimed; second invoice flagged |

All four POs are marked approved, use INR and net amount basis, and are valid from 5 August 2026 through 3 November 2027. Every invoice is dated 1 November 2026, within that period. The app extracted and stored each PO's number, vendor, amount, basis, status, dates, and line correctly.

## Invoices and decisions

| Invoice | PO | Net + tax = gross | Claimed cumulative PO use | App decision | Audit |
| --- | --- | --- | --- | --- | --- |
| INV-SEL-001 | PO-SEL-001 | 4,000 + 720 = 4,720 | INR 4,000; 4/10 seats | Ready for approval | Correct |
| INV-SEL-002 | PO-SEL-001 | 6,000 + 1,080 = 7,080 | INR 10,000; 10/10 seats | Ready for approval | Correct; the prior INR 4,000 is reserved |
| INV-SEL-003 | PO-SEL-002 | 2,000 + 360 = 2,360 | INR 2,000; 4/8 hours | Ready for approval | Correct |
| INV-SEL-004 | PO-SEL-003 | 1,800 + 0 = 1,800 | INR 1,800; 6/6 kits | Needs clarification | Correct; scanned PDF requires visual review |
| INV-SEL-005 | PO-SEL-004 | 6,000 + 1,080 = 7,080 | INR 6,000; 3/5 trips | Ready for approval | Correct |
| INV-SEL-006 | PO-SEL-004 | 6,000 + 1,080 = 7,080 | INR 12,000; 6/5 trips | Procurement review | Correct; exceeds amount by INR 2,000 and quantity by one trip |

Each invoice's line quantity × unit price equals its net subtotal. Invoice numbers are distinct, vendor IDs and tax IDs match the supplied master, and bank accounts match. The PO-SEL-004 overrun exceeds the configured 2% amount tolerance (INR 200), and the quantity exceeds the ordered five trips.

## Visible limitations for the submission

- OCR read `Blueleaf Office Supplies` as `Blueleaf OfficeSupplies` and `Office supply kits` as `Office supplykits` in INV-SEL-004. Identifiers and amounts were read correctly. The app keeps its scanned-document warning, so the decision remains **Needs clarification** until a person verifies and corrects the extraction.
- The supplied historical invoice register is explicitly empty. Duplicate checks cover these six uploaded PDFs and the declared zero previous records; they do not prove that no invoices exist outside this demo workspace.
- Vendor identities and PO approval statuses come from synthetic, supplied records. This demo does not independently confirm them against an ERP or procurement system.
- These documents were processed with local text extraction/OCR. OpenRouter is configured for future uploads but was not used to extract this seeded set. The app checks `subtotal + tax = total`; it does not determine whether a tax rate is legally correct.
- “Ready for approval” is a review recommendation. It does not confirm delivery/receipt or authorize payment.

## Additional split-order safeguard

A separate, isolated test found that an earlier invoice awaiting scan review was not reserved against a PO. Before the fix, a later invoice against that same PO could be marked ready. The app now marks later invoices **Needs clarification** while an earlier invoice for the PO still needs **source extraction verification**, shows the provisional claimed amount, and asks for that source to be checked. Once the earlier invoice is verified, its amount becomes a confirmed reservation and a genuine overrun is sent to procurement. Unrelated held or disputed invoices remain excluded from reservations. This fix does not change any of the six decisions above.
