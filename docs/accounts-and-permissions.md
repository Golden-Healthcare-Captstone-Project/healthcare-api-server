# Accounts and permissions

Four account types, a fixed permission map, and ownership rules. Sign-in is **not** built: the caller is identified by the placeholder `X-User-Id` header in `app/auth.py` (`get_current_user`). That function is the only thing to replace when real authentication arrives. Until then the checks stop mistakes and casual misuse, but a determined caller can set the header to any id.

## Who can do what

| Permission | older_adult | caregiver | provider | admin |
|---|---|---|---|---|
| create_request (self; caregiver for linked clients) | yes | yes | | |
| view_own_requests (own + linked clients) | yes | yes | | |
| view_all_requests | | | yes | yes |
| update_request_status | | | yes | yes |
| make_payment (own request; caregiver for linked clients) | yes | yes | | |
| view_payment (owner or linked caregiver) | yes | yes | | |
| view_all_payments | | | | yes |
| manage_services | | | | yes |
| manage_users | | | | yes |
| manage_links | | | | yes |

The map lives in `app/permissions.py` (`ROLE_PERMISSIONS`). Unknown or legacy role values get no permissions. The community/social feed is deliberately not part of this: its posts come from the linked social media account.

Ownership: a request or payment is reachable by its owner, by a caregiver linked to the owner, and (for viewing) by staff with the matching `view_all_*` permission. Someone else's payment returns **404**, not 403, so ids cannot be probed.

## Caregiver links
A caregiver acts for an older adult only through a link created by an admin (`POST /caregiver-links`). Caregivers cannot link themselves. The caregiver account must have role `caregiver` and the linked account `older_adult`. The `caregiver_links` table is created automatically; no SQL migration is needed.

## Creating the first admin
There is no other way to make a user today:

```bash
python -m app.seed --admin you@example.com --first-name You --last-name Admin
```
It creates the account, or promotes an existing one. Accounts created by admins get an unusable password hash, since sign-in does not exist yet.

## Endpoints
`GET /me`, `GET /me/linked-clients`, `GET|POST /users`, `PATCH /users/{id}/role` (cannot remove the last admin), `GET|POST /caregiver-links`, `DELETE /caregiver-links/{id}`, `PATCH /requests/{id}/status`. `POST /requests/`, `GET /requests/`, `POST /services` and all `/payments` routes (except webhooks, which are signature-verified) now require an identity and the matching permission.

## Frontend
- `IdentityStore` holds the acting user id; `identityInterceptor` sends it as `X-User-Id` to our API only.
- `AccountService` loads `/me`; the UI hides what the account cannot use (the API still enforces everything). `/admin` is protected by `permissionGuard('view_all_requests')`.
- The "Acting as user ID" bar stands in for sign-in and is shown only where `environment.allowActingAs` is true (development by default, **off in production**). With it off and no login, nobody can request services or pay on a production deployment.
