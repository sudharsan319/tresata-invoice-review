# Validation

Verified through 3 November 2026 in the supplied Linux workspace, using Python 3.12 and Node.js 26.

| Check | Result |
| --- | --- |
| Backend automated tests | **94 passed** |
| TypeScript type checking + production frontend build | **Passed** |
| `./run.sh` dependency setup, build, and server startup | **Passed** |
| `./run.sh --dev` frontend and backend proxy | **Passed** |
| Frontend and API served over real localhost HTTP | **HTTP 200** |
| Real `/api/demo` flow through extraction and rules | **13 invoices processed; all expected routes matched** |
| Demo recommendations | **3 ready, 4 clarification, 3 procurement, 3 hold** |
| Original invoice PDF retrieval | **Passed** |
| Evidence JSON and summary CSV download | **Passed** |
| Local scanned-PDF OCR | **Extracted invoice identifier, total, and line item; requires human confirmation** |
| Invoice image upload | **PNG without an extension, JPEG, and WEBP processed through live upload; original bytes and image content types preserved; reprocessing uses the image for vision input** |
| PO image upload | **Extensionless PNG processed through live upload; original image preserved and a draft created without activating the PO** |
| OpenRouter integration | **Task routing, private settings, model catalogue, error handling, source validation, semantic confirmation, policy draft activation, and background reprocessing verified; automated provider tests mocked; all five task routes additionally checked live on synthetic data** |
| Browser interaction / visual QA | **Unavailable: the computer-use tool reported no browser available** |

The test suite includes 12 synthetic PDF decision scenarios and a scanned invoice, plus targeted controls around bank changes, duplicate scope, missing history, cumulative quantities, currencies, dates, arithmetic, conflicting reference identities, reference deletion, human correction audit, unsupported policies, multiple import formats, protected PDFs, and cross-origin writes. Tests use temporary data directories and do not alter the operator's workspace.

There is one dependency deprecation warning from FastAPI/Starlette's current test-client HTTP transport. The tests pass; this does not affect the running application's HTTP client/server path.

No real company or personal financial documents were used. The application was not hosted or deployed.

## OpenRouter upgrade

The new settings routes were checked over real localhost HTTP. The live public OpenRouter model catalogue confirms that every configured default supports structured output, and the vision default supports images. The running app was reloaded while preserving all 18 existing source documents and 14 invoice recommendations. After a key was added to the local .env, authentication and live inference for all five task routes were verified on synthetic inputs. The server needed a reload to pick up the environment file. Browser visual/interaction QA remains unavailable.

Budget defaults: Mistral Nemo for extraction/briefs, Mistral Small 24B for semantic matching/policy reading, and Gemma 3 12B for scanned-page vision. Item matches and policy proposals require explicit human confirmation. Exact financial checks continue to determine the recommendation.

## Live OpenRouter check

Live synthetic tests verified invoice identifier NS-1042, total 9440, quantity 8 and unit price 1000; source-backed item equivalence; scanned identifier FMT-013 and amount 1000; a sourced 2% policy tolerance proposal; and a brief citing real check IDs. The policy reader preserves the existing title when the model invents one, normalizes numeric percentage strings, and rejects unsupported numeric rules. Missing AI numeric cells can use one identical, source-backed local table row; broader unsupported item proposals remain rejected. No uploaded company invoices were reprocessed or modified by the live check.

Observed extraction latency varied considerably, including one approximately 63-second response with the budget extraction model. Live smoke tests are not a benchmark of general accuracy or latency. Policies, scans, and semantic matches retain their human-review requirements.

## Live upload visualization

Six additional tests verify that progress remains readable while extraction is deliberately blocked, a concurrent upload is rejected, failed files do not produce invented checks or prevent valid files from completing, live check messages match saved review messages, the upload trace persists, reference imports finish correctly, cross-origin writes remain blocked, and AI progress excludes prompts, API keys, and raw model outputs. Provider behavior in these tests is mocked; this feature required no additional paid calls.

An isolated server on localhost:8001 additionally accepted a real multipart upload (HTTP 202), completed the background job, emitted individual verification checks, and saved its trace. Temporary test data was separate from the operator's workspace. TypeScript and the production build pass. Browser visual QA remains unavailable: the computer-use tool reported no browser available.

The operator's localhost:8000 app was rebuilt and restarted successfully. Its frontend and new JavaScript bundle return HTTP 200, both live-upload API routes are registered, all 22 existing document IDs and 18 recommendation decisions were preserved, and the configured AI remains ready. No operator documents were uploaded, re-extracted, or otherwise changed during verification.

## Policy menu

The frontend now includes a top-right Policies button opening a right-side panel. The panel reads the existing workspace data to display all six active policy settings, source links, saved policy documents, pending AI drafts, and standard verification controls. TypeScript checking and the production build pass; the served HTML, JavaScript, CSS, and saved policy source link return HTTP 200. No backend behavior or policy values were changed. Browser interaction and visual QA remain unavailable in this session.
