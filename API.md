# Machine API (v1)

A small JSON API for the ScanBase scanning app (UCLA Health Materials Management), which
takes in donated items. People keep using the website exactly as before.

## Turning it on and off

The API is **off unless `MAI_API_KEY` is set**. Until then every `/api/v1` call answers `503`.
The only other effect of merging: two new, empty tables are created at start-up (see
[Database](#database)); nothing else on the live site changes.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # make a key
fly secrets set MAI_API_KEY="<that key>"                       # on
fly secrets unset MAI_API_KEY                                  # off again
```
To change the key, set a new one; the old one stops working at once.

`MAI_API_CLIENT_NAME` (default `scanbase-api`) is the name shown as the user in the audit log
for every change made through the API.

## Rules

- **Auth:** every call needs `Authorization: Bearer <MAI_API_KEY>`. A missing or wrong key
  answers `401`. The key is only ever used server to server, never on a scanning PC.
- **Items are matched by UCLA ERP item number** (`erp_key`), never by name. Several numbers
  can point to one item (for example one "face shield" item for several brands); one number
  points to one item only. Numbers are letters, digits, `.`, `-` and `_` (starting with a
  letter or digit), so each one can be looked up in a URL.
- **Nothing existing is overwritten.** The API creates items and adds to `quantity_active`.
  It never changes a name, category or note your team set, and never deletes anything your
  team made. (The one delete: if a new item's number cannot be linked, the API takes back
  the item it just made, so no item is left without its number. That shows in the audit
  log too.)
- **Every write is applied at most once.** Every write carries a `request_id`:
  - A write that finished: sending the same `request_id` again returns the same answer and
    changes nothing. Writes run one at a time, so two copies arriving together are applied
    once.
  - A write that was refused (`400`, `404`, `413`, `422`, or `409` `erp_key_linked` or
    `changed_meanwhile`) changed nothing.
    It can be sent again once the cause is fixed.
  - A write that broke off half-way (a server error, or a restart mid-request): sending it
    again is refused (`409` `did_not_finish`) instead of applied a second time. A person
    checks in the audit log (`/view/audit`, under the API's name) what was done, then sends
    what is missing with a **new** `request_id`.
  - The same `request_id` with a different request is refused (`409` `request_id_reused`).
    The one exception is the same scanned line: if a create succeeded but its answer was
    lost, the retry (sent as a quantity update once the item is found) gets the create's
    answer back (`201`), so the line is never counted twice.
- **Quantity never goes below 0.** Like check-out on the website, a subtraction that would
  go below 0 is refused (`422`) and changes nothing.
- **Every change goes through the normal database functions**, so it shows in the audit
  log (`/view/audit`) with before/after, and Litestream backs it up like everything else.
- **Requests are JSON:** send `Content-Type: application/json`.
- **Errors are always JSON:** `{"error": "..."}`, also for an unknown `/api/v1` path or
  method. Every `409` also has a `code` saying what to do:

  | `code` | Meaning | What the client does |
  |---|---|---|
  | `erp_key_linked` | the number already belongs to an item (`item_id` in the answer) | use that item |
  | `did_not_finish` | an earlier try of this `request_id` broke off half-way | do not resend; a person checks |
  | `request_id_reused` | this `request_id` was used for a different request | a bug in the client |
  | `changed_meanwhile` | the item changed between the check and the update | send it again |
- **Small requests only:** a body over 64 KB is refused (`413`).
- **Text is text, and no HTML gets in.** Text fields must be JSON strings, and may not
  contain `<`, `>` or control characters (`400`), so nothing sent through the API can change
  how a page that shows it is built.
- **Only the key counts.** A website login or session cookie gives no access to `/api/v1`,
  so there is no CSRF risk. Only whitelisted fields are read from a request.

## Endpoints

### `GET /api/v1/categories`
All active categories with their active subcategories.
```json
{"categories": [{"category_id": "…", "name": "OR Equipment",
                 "subcategories": [{"subcategory_id": "…", "name": "General"}]}]}
```

### `GET /api/v1/items/by-erp/<erp_key>`
The item an ERP item number is linked to. `404` if none (or the item was deleted). An item
in a category that was deleted later is still found (the item itself was not deleted).
```json
{"item_id": "…", "name": "DRESSING TEGADERM 2 3/8X2 3/4 HP", "category_id": "…",
 "category_name": "OR Equipment", "subcategory_id": "…", "subcategory_name": "General",
 "location": "C-L-5", "quantity_active": 3, "erp_keys": ["000247"]}
```

### `POST /api/v1/items`
Create an item and link its ERP item number.
```json
{"erp_key": "000247", "name": "DRESSING TEGADERM 2 3/8X2 3/4 HP", "category_id": "…",
 "subcategory_id": "…", "location": "C-L-5", "quantity": 3, "request_id": "<uuid>"}
```
- `erp_key`, `name`, `category_id`, `quantity` (a whole number, 0 or more) and `request_id` are
  required.
- Lengths: `erp_key` up to 64 characters, `name` and `location` up to 200, ids up to 100.
- `subcategory_id` is optional. Without it the item goes into the category's "General"
  subcategory (or, if it has none, its first active one).
- `location` is optional.
- `201` with the item (same shape as above).
- `409` `erp_key_linked` if the number is already linked:
  `{"error": "…", "code": "erp_key_linked", "item_id": "…", "item_deleted": false}`.
  If that item was deleted on the site, no new item is made: a person decides whether to
  restore it.
- `422` for an unknown or deleted category, a subcategory of another category, or a
  category with no active subcategory.
- `400` for missing or invalid fields.

### `POST /api/v1/items/<item_id>/quantity`
Add to (or, with a negative number, subtract from) the active quantity, in one database
statement, so two updates at the same time never overwrite each other.
```json
{"delta": 2, "request_id": "<uuid>"}
```
- `delta` (a whole number between -2147483647 and 2147483647) and `request_id` are required.
  `0` changes nothing.
- `200` with `{"item_id": "…", "quantity_active": 5}`.
- `201` with the full item, for the lost create answer described under the rules.
- `request_id` up to 100 characters.
- `404` if the item does not exist or is deleted.
- `422` if it would go below 0: `{"error": "Not enough in stock.", "quantity_active": 4}`.
- `409` `changed_meanwhile` if the item changed between the check and the update (it would go
  below 0 after all, or it was deleted); nothing changed, send it again. (A safeguard: with one server
  worker, requests run one at a time.)

### `POST /api/v1/items/<item_id>/erp-links`
Link one more ERP item number to an item that already exists (used once per item during a
re-scan of existing stock).
```json
{"erp_key": "000248", "request_id": "<uuid>"}
```
- `erp_key` (letters, digits, `.`, `-`, `_`) and `request_id` are required; `400` if missing
  or invalid.
- `200` with the item. Linking a number that is already linked to this item changes nothing.
- `409` `erp_key_linked` if the number is linked to another item (it is never moved):
  `{"error": "…", "code": "erp_key_linked", "item_id": "…", "item_deleted": false}`.
- `404` if the item does not exist or is deleted.

## Database

Two new tables. No existing table or column changes.

| Table | Columns | Purpose |
|---|---|---|
| `item_erp_link` | `erp_key` (unique), `item_id`, `date` | which item an ERP item number belongs to |
| `api_request` | `request_id` (unique), `kind`, `fingerprint`, `status`, `body`, `date` | each write: what it was, and its answer (`status` 0 until it finishes) |

Both are created at start-up in `db_util.py` (`CREATE TABLE IF NOT EXISTS`, like the other
tables), so the database version stays at 12.

`api_request` gets one small row per write. Removing old rows is optional; a
request retried after its row was removed would be applied again, so keep at least 30 days,
and keep rows that never finished (`status` 0):
`DELETE FROM api_request WHERE status != 0 AND date < strftime('%s', 'now', '-30 days');`

**To remove the API completely:** unset `MAI_API_KEY`, then (optionally) revert the code and
`DROP TABLE item_erp_link; DROP TABLE api_request;`. Items created through the API stay
normal items.
