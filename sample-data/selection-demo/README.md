# Selection demo data

All records here are synthetic. They demonstrate four purchase orders and six invoice PDFs across three vendors.

| Invoice | PO | Scenario | Expected recommendation |
| --- | --- | --- | --- |
| INV-SEL-001 | PO-SEL-001 | First partial invoice: 4 of 10 software seats | Ready for approval |
| INV-SEL-002 | PO-SEL-001 | Second partial invoice: remaining 6 seats; PO fully used | Ready for approval |
| INV-SEL-003 | PO-SEL-002 | Taxed service invoice from the same vendor on a different PO | Ready for approval |
| INV-SEL-004 | PO-SEL-003 | Scanned invoice from a different vendor; OCR review needed | Needs clarification |
| INV-SEL-005 | PO-SEL-004 | First partial invoice: 3 of 5 delivery trips | Ready for approval |
| INV-SEL-006 | PO-SEL-004 | Second partial invoice: combined 6 trips, one over the PO limit | Procurement review |

`approved-vendors.json` supplies the three vendor identities. `previous-invoices.json` is an explicit empty history register, so the app can check workspace duplicates without suggesting that historical invoices were provided. The four PO PDFs require review and activation before invoice matching uses them. `manifest.json` records the expected source values.

The Aster pair uses exactly ₹10,000 net on a ₹10,000 PO. The Cedar pair totals ₹12,000 net against a ₹10,000 PO; its second invoice exceeds both the authorized amount and the five-trip quantity.

Regenerate with `.venv/bin/python scripts/selection_demo.py` from the project root. The generator writes files only; it does not change the app workspace.
