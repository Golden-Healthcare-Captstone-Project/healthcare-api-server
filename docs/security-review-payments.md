# Payment feature: security review and end-to-end test

Scope: the processor-agnostic payment work (`app/payment_providers/`, `app/routers/payments.py`, the Angular gateway/checkout/result code) plus the dependencies and repo hygiene around it. Fixes to the payment path are in the working tree with tests; everything else is reported only.

## Findings

| # | Severity | Finding | Status |
|---|----------|---------|--------|
| 1 | High | **A declined card could leave a charged order marked `failed`.** Stripe emits `payment_intent.payment_failed` for every declined attempt, but the intent stays usable. The first version treated that as final, so a later successful retry was ignored. | Fixed |
| 2 | High | **No authentication or ownership checks** on payment, request and service routes. `get_current_user` is a placeholder (`X-User-Id` header); `/requests/` took `user_id` in the body; the frontend hardcoded `user_id: 1`. Anyone who could guess a sequential payment or request id could create intents for it or read its status. `POST /services` was public. | **Partly fixed** by the accounts and permissions work (see `accounts-and-permissions.md`): roles, ownership checks on requests and payments, admin-only service creation. Still open: identity is the spoofable `X-User-Id` header until real sign-in exists. |
| 3 | Medium | **Double charge race.** Two concurrent `POST /payments/intent` for one request could both create an intent. | Fixed (row lock; effective on PostgreSQL, a no-op on SQLite) |
| 4 | Medium | **Mock provider could settle payments for anyone who knows its secret** (`mock-secret`, default and hardcoded in the dev gateway) if enabled in a real deployment. | Fixed (refuses to run when `VERCEL_ENV=production`; logs a warning when enabled; only active when `PAYMENT_PROVIDER=mock`) |
| 5 | Medium | **Unauthenticated status endpoint leaked internal ids** (`transaction_id`, `service_request_id`) by sequential id. | Fixed (returns only payment id, provider, status, amount, currency) |
| 6 | Medium | **Webhook accepted unbounded bodies** and trusted a `paid` event without checking the amount. | Fixed (413 above 1 MB; a `paid` event whose amount differs from the stored amount is acknowledged but ignored) |
| 7 | Medium | **Processor-supplied redirect URL was followed unvalidated** (`javascript:`/`data:` navigation risk). | Fixed (https only, plus http to localhost in dev) |
| 8 | High | **Outdated Python dependencies with known advisories** (`pip-audit`): starlette 0.52.1 (10), urllib3 2.6.3 (7), anyio, idna, python-dotenv, requests (2 each). Starlette is the web framework itself. | Reported. Upgrade `requirements.txt`, run the test suite, redeploy. Fix versions per advisory: starlette 1.3.1, urllib3 2.8.0, requests 2.33.0, anyio 4.14.2, idna 3.15, python-dotenv 1.2.2. Note the starlette fix is a major version; check FastAPI/slowapi compatibility first. |
| 9 | High | **`@angular/core` 19.x advisories** (`npm audit`: 7 vulnerabilities, 4 high; XSS and sanitization bypass classes). The suggested fix is a breaking major upgrade. | Reported. Check for a patched 19.x release first, otherwise schedule the upgrade. |
| 10 | Medium | **Rate limiting keys on `get_remote_address`.** Behind Vercel's proxy this may be the proxy address (everyone shares limits) or a spoofable forwarded header. | Reported |
| 11 | Low | No CSP or other security headers on the frontend. When Stripe is chosen, add a CSP allowing its script and frame domains. | Reported |
| 12 | Low | Money stored as `Float`; prefer integer cents or `Numeric`. | Reported |
| 13 | Low | CORS always allows `http://localhost:4200`, even in production. | Reported |
| 14 | Low | `.github/workflows/meta-refresh.yml` sends `META_ADMIN_SECRET` in a URL query string, which tends to end up in access logs. Use a header. | Reported |
| 15 | Low | `test.db` is tracked in the backend repo, and the frontend repo tracks `.vs/**/*.db` editor index files. The backend copy holds only seed data (5 services, 2 requests, no users or payments). | Reported. `git rm --cached` them and add `.vs/` to the frontend `.gitignore`. |
| 16 | Low | The 422 handler echoes submitted input back in the response. | Reported |

## Functional gaps found while testing (not security)
- `app/seed.py` creates services **without prices**, so checkout on a database seeded that way fails with "Service has no price". Production services need prices set.
- The frontend hardcodes service ids 1-13 in `service.model.ts`; they must match database ids exactly.
- The pre-existing "checkout form did not mount" race in `AppComponent` (a `setTimeout` racing change detection) was found and fixed by rendering before mounting.

## Checked and found sound
- The charged amount comes from `Service.price` on the server; the client cannot choose it.
- Card data never reaches this app (processor SDK only); nothing sensitive is logged, and client secrets are not logged.
- Webhook signatures: Stripe's `construct_event`; mock uses constant-time comparison; raw body is verified before parsing.
- Replayed webhooks are idempotent, and a paid payment cannot be changed by later events.
- A payment keeps the provider that created it, so changing `PAYMENT_PROVIDER` never asks the wrong processor about an old payment.
- Bandit on `app/`: no issues. No secrets in either repo's working tree or git history (Stripe, webhook, private-key, database-URL and Meta-token patterns). `.env` is ignored in both repos.

## End-to-end test
`healthcare-web-client/e2e/run.sh [outDir]` starts the real API (mock provider, throwaway SQLite database) and the Angular dev server, drives headless Chromium, and checks the database as well as the UI. Screenshots are written to `outDir`. Result: **9 of 9 scenarios passed**:

1. Happy path: request, checkout, approve, success page, payment row `paid`
2. Decline keeps the modal open and the payment pending; approving then succeeds on the same payment
3. Failure page, then "Try again" opens checkout with a new payment
4. Pending result polls, gives up with "still processing", then settles on "Check again"
5. Missing, malformed or unknown payment id shows the error view (and no API call for bad ids)
6. Paying an already-paid request is refused with a clear message
7. Result page renders in French
8. Webhook and status API checks: bad signature, unknown provider, wrong amount, oversized body, replay, failure after paid, no internal ids in the response
9. With another provider configured, the mock webhook and intent endpoint are refused (503)

Not covered: the real Stripe SDK and real Stripe webhooks (no test keys were used), concurrent intent creation on PostgreSQL, and any other browser than Chromium.

## Recommended order of follow-up
0. Real sign-in. Until it exists, the role checks stop mistakes and casual misuse but not a determined caller who sets the header.
1. Upgrade starlette/urllib3/requests and the Angular 19 advisories (items 8, 9).
2. Add real authentication and ownership checks (item 2), then drop the public status endpoint's reliance on obscurity.
3. Before launch with Stripe: set `STRIPE_WEBHOOK_SECRET`, point Stripe at `/payments/webhook/stripe`, run the Stripe test-card cases, and add the CSP.
4. Run the SQL migration for the new `payments.provider` and `payments.currency` columns.
