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

# Get what is stored for a request: a dict with kind, fingerprint, status (0 while
# it runs or if it never finished) and body, or None if the request_id is new
def get_api_request(request_id):
    result = None
    cursor = db.get_data_db().cursor()

    query_results = cursor.execute("""
        SELECT kind, fingerprint, status, body FROM api_request WHERE request_id=?""", (
            str(request_id).strip(),
    ))

    for row in query_results:
        result = {
            'kind': row[0],
            'fingerprint': row[1],
            'status': int(row[2]),
            'body': json.loads(row[3]),
        }

    cursor.close()
    return result

# Claim a request_id before its write starts (status 0). Returns False if the
# request_id was already there.
def start_api_request(request_id, kind, fingerprint):
    db_connection = db.get_data_db()
    cursor = db_connection.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO api_request (request_id, kind, fingerprint, status, body, date)
        VALUES(?, ?, ?, 0, 'null', ?)""", (
            str(request_id).strip(),
            str(kind),
            str(fingerprint),
            int(datetime.now().timestamp())
        ))
    started = cursor.rowcount == 1

    db_connection.commit()
    cursor.close()
    return started

# Store the answer to a finished write, so that a retry gets the same answer back
def finish_api_request(request_id, status, body):
    db_connection = db.get_data_db()
    cursor = db_connection.cursor()

    cursor.execute("""
        UPDATE api_request SET status=?, body=? WHERE request_id=?""", (
            int(status),
            json.dumps(body),
            str(request_id).strip()
        ))

    db_connection.commit()
    cursor.close()

# Forget a write that was refused (it changed nothing), so it can be sent again
def drop_api_request(request_id):
    db_connection = db.get_data_db()
    cursor = db_connection.cursor()

    cursor.execute("""
        DELETE FROM api_request WHERE request_id=? AND status=0""", (
            str(request_id).strip(),
    ))

    db_connection.commit()
    cursor.close()
