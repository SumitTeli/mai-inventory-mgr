# Machine API (v1)

A small JSON API so the ScanBase scanning app (UCLA Health Materials Management) can add
donated items to the inventory. People keep using the website exactly as before; this only
adds a second way for items to come in.

## Turning it on and off

The API is **off unless `MAI_API_KEY` is set**. Until then every `/api/v1` call answers `503`,
so merging this changes nothing on the live site.

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
  points to one item only.
- **Nothing existing is overwritten.** The API creates items and adds to `quantity_active`.
  It never changes a name, category or note your team set, and never deletes anything.
- **Quantity never goes below 0.** Like check-out on the website, a subtraction that would
  go below 0 is refused (`422`) and changes nothing.
- **Retries are safe.** Every write carries a `request_id`. If a write succeeded, sending
  the same `request_id` again returns the same answer and changes nothing. A write that
  failed changed nothing, so it is simply checked again. A `request_id` stands for one
  scanned line, on whichever endpoint it is sent: if a create succeeded but its answer was
  lost, the retry (sent as a quantity update once the item is found) gets the create's
  answer back, so the line is never counted twice.
- **Every change goes through the normal database functions**, so it shows in the audit
  log (`/view/audit`) with before/after, and Litestream backs it up like everything else.
- **Errors are always JSON:** `{"error": "..."}`, also for an unknown `/api/v1` path.
- **No HTML gets in.** Text fields may not contain `<`, `>` or control characters (`400`),
  so nothing sent through the API can change how a page that shows it is built.
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
The item an ERP item number is linked to. `404` if none (or the item was deleted).
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
- `subcategory_id` is optional. Without it the item goes into the category's "General".
- `201` with the item (same shape as above).
- `409` if the number is already linked: `{"error": "…", "item_id": "…", "item_deleted": false}`.
  If that item was deleted on the site, no new item is made: a person decides whether to
  restore it.
- `422` for an unknown or deleted category, or a subcategory of another category.
- `400` for missing or invalid fields.

### `POST /api/v1/items/<item_id>/quantity`
Add to (or, with a negative number, subtract from) the active quantity.
```json
{"delta": 2, "request_id": "<uuid>"}
```
`200` with `{"item_id": "…", "quantity_active": 5}`. `404` if the item does not exist or is
deleted. `422` if it would go below 0: `{"error": "Not enough in stock.", "quantity_active": 4}`.

### `POST /api/v1/items/<item_id>/erp-links`
Link one more ERP item number to an item that already exists (used once per item during a
re-scan of existing stock).
```json
{"erp_key": "000248", "request_id": "<uuid>"}
```
`200` with the item. `409` if the number is linked to another item. `404` if the item does
not exist or is deleted.

## Database

Two new tables. No existing table or column changes.

| Table | Columns | Purpose |
|---|---|---|
| `item_erp_link` | `erp_key` (unique), `item_id`, `date` | which item an ERP item number belongs to |
| `api_request` | `request_id` (unique), `status`, `body`, `date` | the answer to each successful write |

They are added by the `13.0` upgrade in `db_util.py`, like every earlier upgrade.

**To remove the API completely:** unset `MAI_API_KEY`, then (optionally)
`DROP TABLE item_erp_link; DROP TABLE api_request;`. Items created through the API stay
normal items.

## Tests

```bash
python -m pip install pytest
python -m pytest tests
```
The tests use a temporary database, never the real one.
