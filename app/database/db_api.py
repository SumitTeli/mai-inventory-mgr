from datetime import datetime
import json

from . import db_util as db
from . import db_audit

######################
# ERP LINK FUNCTIONS #
######################

# Link a UCLA ERP item number to an item. Returns the item_id the number is
# linked to afterwards: item_id itself, or another item if it was already taken.
def insert_erp_link(erp_key, item_id):
    db_connection = db.get_data_db()
    cursor = db_connection.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO item_erp_link (erp_key, item_id, date)
        VALUES(?, ?, ?)""", (
            str(erp_key).strip(),
            str(item_id).strip(),
            int(datetime.now().timestamp())
        ))
    inserted = cursor.rowcount

    db_connection.commit()
    cursor.close()

    if inserted:
        db_audit.insert_item_audit_event(item_id, "Linked ERP item number.", "", {'erp_key': str(erp_key).strip()})

    return get_item_id_for_erp_key(erp_key)

# Get the item_id an ERP item number is linked to (None if it is not linked)
def get_item_id_for_erp_key(erp_key):
    result = None
    cursor = db.get_data_db().cursor()

    query_results = cursor.execute("""
        SELECT item_id FROM item_erp_link WHERE erp_key=?""", (
            str(erp_key).strip(),
    ))

    for row in query_results:
        result = str(row[0])

    cursor.close()
    return result

# Get all ERP item numbers linked to an item
def get_erp_keys_for_item(item_id):
    result = []
    cursor = db.get_data_db().cursor()

    query_results = cursor.execute("""
        SELECT erp_key FROM item_erp_link WHERE item_id=? ORDER BY erp_key""", (
            str(item_id).strip(),
    ))

    for row in query_results:
        result.append(str(row[0]))

    cursor.close()
    return result

#########################
# API REQUEST FUNCTIONS #
#########################

# Get the stored answer to a request: (status, body), or None if it is new
def get_api_request(request_id):
    result = None
    cursor = db.get_data_db().cursor()

    query_results = cursor.execute("""
        SELECT status, body FROM api_request WHERE request_id=?""", (
            str(request_id).strip(),
    ))

    for row in query_results:
        result = (int(row[0]), json.loads(row[1]))

    cursor.close()
    return result

# Store the answer to a request, so that a retry gets the same answer back
def insert_api_request(request_id, status, body):
    db_connection = db.get_data_db()
    cursor = db_connection.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO api_request (request_id, status, body, date)
        VALUES(?, ?, ?, ?)""", (
            str(request_id).strip(),
            int(status),
            json.dumps(body),
            int(datetime.now().timestamp())
        ))

    db_connection.commit()
    cursor.close()
