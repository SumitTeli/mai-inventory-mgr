import sqlite3
import uuid

import config
from app.database import db_interface as database
from app.database import db_util

AUTH = {"Authorization": "Bearer test-key"}


def call(site, method, path, body=None, headers=AUTH):
    response = site["client"].open(path, method=method, json=body, headers=headers)
    return response.status_code, response.get_json()


def create(site, erp_key="000247", quantity=3, request_id=None, **fields):
    body = {"erp_key": erp_key, "name": "DRESSING TEGADERM 2 3/8X2 3/4 HP",
            "category_id": site["categories"]["OR Equipment"], "location": "C-L-5",
            "quantity": quantity, "request_id": request_id or str(uuid.uuid4())}
    body.update(fields)
    return call(site, "POST", "/api/v1/items", body)


def add(site, item_id, delta, request_id=None):
    return call(site, "POST", "/api/v1/items/" + item_id + "/quantity",
                {"delta": delta, "request_id": request_id or str(uuid.uuid4())})


def rows(site, sql, params=()):
    with sqlite3.connect(site["db_path"]) as db:
        return db.execute(sql, params).fetchall()


# ------------------------------------------------------------------ access
def test_off_unless_a_key_is_set(site, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", None)
    status, body = call(site, "GET", "/api/v1/categories")
    assert status == 503 and "not enabled" in body["error"]


def test_needs_the_right_key(site):
    assert call(site, "GET", "/api/v1/categories", headers={})[0] == 401
    assert call(site, "GET", "/api/v1/categories", headers={"Authorization": "Bearer wrong"})[0] == 401
    assert call(site, "GET", "/api/v1/categories", headers={"Authorization": "test-key"})[0] == 401
    assert call(site, "GET", "/api/v1/categories")[0] == 200


def test_errors_are_json_not_the_error_page(site, monkeypatch):
    def broken():
        raise RuntimeError("database is gone")
    monkeypatch.setattr(database, "get_all_active_categories", broken)
    status, body = call(site, "GET", "/api/v1/categories")
    assert status == 500 and body == {"error": "Internal error."}
    assert call(site, "POST", "/api/v1/items", None)[0] == 400                       # no JSON body
    assert call(site, "POST", "/api/v1/items", [1, 2])[0] == 400                     # not a JSON object
    assert call(site, "GET", "/api/v1/nope") == (404, {"error": "Unknown API call."})
    assert call(site, "DELETE", "/api/v1/items/x")[0] == 404
    assert call(site, "GET", "/api/v1/nope", headers={})[0] == 401                    # the key is checked first


def test_a_logged_in_browser_is_not_enough(site):
    # The API only takes the key: no session cookie, no website login, no CSRF risk.
    with site["client"].session_transaction() as session:
        session["_user_id"] = "someone@example.com"
    assert call(site, "GET", "/api/v1/categories", headers={})[0] == 401


# ------------------------------------------------------------------ categories
def test_categories_with_their_subcategories(site):
    database.delete_category(site["categories"]["PPE"])
    status, body = call(site, "GET", "/api/v1/categories")
    assert status == 200
    assert [c["name"] for c in body["categories"]] == ["OR Equipment"]               # deleted ones are left out
    subcategories = {s["name"] for s in body["categories"][0]["subcategories"]}
    assert subcategories == {"General", "Surgical/Wound Dressing"}
    assert body["categories"][0]["category_id"] == site["categories"]["OR Equipment"]


# ------------------------------------------------------------------ create
def test_create_makes_a_normal_item_and_links_the_number(site):
    status, item = create(site, subcategory_id=site["subcategories"]["Surgical/Wound Dressing"])
    assert status == 201
    assert item["name"] == "DRESSING TEGADERM 2 3/8X2 3/4 HP" and item["quantity_active"] == 3
    assert item["location"] == "C-L-5" and item["erp_keys"] == ["000247"]
    assert item["subcategory_name"] == "Surgical/Wound Dressing"

    status, found = call(site, "GET", "/api/v1/items/by-erp/000247")
    assert status == 200 and found == item
    site_item = database.get_item(item["item_id"])                                    # a normal website item
    assert site_item["quantity_active"] == 3 and site_item["deleted"] is False


def test_create_goes_into_general_when_no_subcategory_is_given(site):
    status, item = create(site)
    assert status == 201 and item["subcategory_name"] == "General"


def test_create_retry_never_makes_a_second_item(site):
    request_id = str(uuid.uuid4())
    first = create(site, request_id=request_id)
    again = create(site, request_id=request_id)
    assert first == again and first[0] == 201
    assert rows(site, "SELECT COUNT(*) FROM item")[0][0] == 1


def test_one_number_one_item(site):
    status, item = create(site)
    status, body = create(site)                                                       # same number, new request
    assert status == 409 and body["item_id"] == item["item_id"] and body["item_deleted"] is False
    database.delete_item(item["item_id"])
    assert call(site, "GET", "/api/v1/items/by-erp/000247")[0] == 404
    status, body = create(site)                                                       # deleted: a person decides
    assert status == 409 and body["item_deleted"] is True
    assert rows(site, "SELECT COUNT(*) FROM item")[0][0] == 1


def test_create_rejects_bad_categories(site):
    other = database.get_all_active_subcategories_for_category(site["categories"]["PPE"])[0]["id"]
    assert create(site, category_id="nope")[0] == 422
    assert create(site, subcategory_id=other)[0] == 422                               # belongs to another category
    database.delete_category(site["categories"]["PPE"])
    assert create(site, erp_key="000006", category_id=site["categories"]["PPE"])[0] == 422
    assert rows(site, "SELECT COUNT(*) FROM item")[0][0] == 0


def test_create_rejects_bad_fields(site):
    assert create(site, name="  ")[0] == 400
    assert create(site, erp_key="")[0] == 400
    assert create(site, quantity=-1)[0] == 400
    assert create(site, quantity="3")[0] == 400
    assert create(site, quantity=True)[0] == 400
    assert create(site, name="x" * 201)[0] == 400
    assert create(site, name="<img src=x onerror=alert(1)>")[0] == 400                # never HTML on the site
    assert create(site, location="C-L-5<script>")[0] == 400
    assert create(site, erp_key="0002>47")[0] == 400
    assert create(site, name="DRESSING\nTEGADERM")[0] == 400                         # no control characters
    status, body = call(site, "POST", "/api/v1/items", {"erp_key": "1", "name": "x", "quantity": 1,
                                                        "category_id": site["categories"]["PPE"]})
    assert status == 400 and "request_id" in body["error"]
    assert rows(site, "SELECT COUNT(*) FROM item")[0][0] == 0


# ------------------------------------------------------------------ quantity
def test_add_quantity(site):
    item_id = create(site)[1]["item_id"]
    assert add(site, item_id, 2) == (200, {"item_id": item_id, "quantity_active": 5})
    assert add(site, item_id, -1)[1]["quantity_active"] == 4
    status, body = add(site, item_id, -5)                                             # never below 0, like check-out
    assert status == 422 and body["quantity_active"] == 4
    assert add(site, item_id, -4)[1]["quantity_active"] == 0
    assert database.get_item(item_id)["quantity_active"] == 0


def test_add_quantity_retry_is_never_counted_twice(site):
    item_id = create(site)[1]["item_id"]
    request_id = str(uuid.uuid4())
    assert add(site, item_id, 2, request_id)[1]["quantity_active"] == 5
    assert add(site, item_id, 2, request_id)[1]["quantity_active"] == 5
    assert database.get_item(item_id)["quantity_active"] == 5


def test_a_lost_create_answer_is_not_counted_twice(site):
    request_id = str(uuid.uuid4())
    item_id = create(site, request_id=request_id)[1]["item_id"]                     # the answer never arrived
    status, body = add(site, item_id, 3, request_id)                                  # the scanner retries the line
    assert status == 201 and body["item_id"] == item_id
    assert database.get_item(item_id)["quantity_active"] == 3


def test_add_quantity_to_a_missing_or_deleted_item(site):
    item_id = create(site)[1]["item_id"]
    assert add(site, "nope", 1)[0] == 404
    database.delete_item(item_id)
    request_id = str(uuid.uuid4())
    assert add(site, item_id, 1, request_id)[0] == 404
    database.restore_deleted_item(item_id)
    assert add(site, item_id, 1, request_id)[1]["quantity_active"] == 4             # the failed try was not kept
    assert add(site, item_id, 1.5)[0] == 400


# ------------------------------------------------------------------ erp links
def test_link_more_numbers_to_an_existing_item(site):
    item_id = create(site)[1]["item_id"]
    body = {"erp_key": "000248", "request_id": str(uuid.uuid4())}
    status, item = call(site, "POST", "/api/v1/items/" + item_id + "/erp-links", body)
    assert status == 200 and item["erp_keys"] == ["000247", "000248"]
    assert call(site, "GET", "/api/v1/items/by-erp/000248")[1]["item_id"] == item_id
    body["request_id"] = str(uuid.uuid4())                                             # linking again is harmless
    assert call(site, "POST", "/api/v1/items/" + item_id + "/erp-links", body)[0] == 200


def test_a_number_cannot_move_to_another_item(site):
    first = create(site)[1]["item_id"]
    second = create(site, erp_key="000006")[1]["item_id"]
    status, body = call(site, "POST", "/api/v1/items/" + second + "/erp-links",
                        {"erp_key": "000247", "request_id": str(uuid.uuid4())})
    assert status == 409 and body["item_id"] == first
    status, body = call(site, "POST", "/api/v1/items/nope/erp-links",
                        {"erp_key": "999999", "request_id": str(uuid.uuid4())})
    assert status == 404


# ------------------------------------------------------------------ audit, site, upgrade
def test_every_change_is_in_the_audit_log_under_the_api_name(site):
    item_id = create(site)[1]["item_id"]
    add(site, item_id, 2)
    audit = rows(site, "SELECT user, event FROM audit WHERE type='ITEM' AND id=? ORDER BY date, rowid", (item_id,))
    assert [event for _, event in audit] == ["Created item.", "Linked ERP item number.", "Updated active quantity."]
    assert {user for user, _ in audit} == {"test-client"}


def test_the_website_still_works_and_shows_api_items(site):
    create(site)
    client = site["client"]
    assert client.get("/browse").status_code == 200
    browse = client.get("/api/browse").get_json()
    assert [i["name"] for i in browse["items"]] == ["DRESSING TEGADERM 2 3/8X2 3/4 HP"]
    assert client.get("/ping").data == b"healthy"


def test_upgrade_from_12_adds_the_tables_and_keeps_everything(site):
    create(site)
    with sqlite3.connect(site["db_path"]) as db:                                      # make it a v12 database
        db.execute("DROP TABLE item_erp_link")
        db.execute("DROP TABLE api_request")
        db.execute("UPDATE version SET db_version=12 WHERE db_name=?", (db_util.DATA_DB_NAME,))
    database.init_db()
    assert rows(site, "SELECT db_version FROM version WHERE db_name=?", (db_util.DATA_DB_NAME,))[0][0] == 13
    tables = {name for (name,) in rows(site, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"item_erp_link", "api_request"} <= tables
    assert rows(site, "SELECT COUNT(*) FROM item")[0][0] == 1                         # existing items untouched
