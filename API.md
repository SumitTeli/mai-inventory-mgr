# Machine API (v1)

A small JSON API for the ScanBase scanning app (UCLA Health Materials Management), which
takes in donated items. People keep using the website exactly as before.

## Turning it on and off

The API is **off unless `MAI_API_KEY` is set**. Until then every `/api/v1` call answers `503`,
so merging this changes nothing on the live site.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # make a key
fly secrets set MAI_API_KEY="<that key>"                       # on
fly secrets unset MAI_API_KEY                                  # off again
```
To change the key, set a new one; the old one stops working at once.

## Rules

- **Auth:** every call needs `Authorization: Bearer <MAI_API_KEY>`. A missing or wrong key
  answers `401`. The key is only ever used server to server, never on a scanning PC.
- **Errors are always JSON:** `{"error": "..."}`, also for an unknown `/api/v1` path.
- **Small requests only:** a body over 64 KB is refused (`413`).
- **Only the key counts.** A website login or session cookie gives no access to `/api/v1`,
  so there is no CSRF risk.

## Endpoints

### `GET /api/v1/categories`
All active categories with their active subcategories.
```json
{"categories": [{"category_id": "…", "name": "OR Equipment",
                 "subcategories": [{"subcategory_id": "…", "name": "General"}]}]}
```
