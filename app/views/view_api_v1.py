from app import app
from flask import request, jsonify, g
from functools import wraps

from app.database import db_interface as database

import config
import hashlib
import hmac
import json
import re
import threading

# Machine API (v1) for the ScanBase scanning app at UCLA Health Materials Management.
# Endpoints and examples: API.md
#
#   - Off unless MAI_API_KEY is set (503 otherwise). Every call needs
#     "Authorization: Bearer <MAI_API_KEY>".
#   - Errors are always JSON, never the site's HTML error page.
#   - Changes go through the normal database functions, so they appear in the
#     audit log, under the name in MAI_API_CLIENT_NAME.
#   - Every write carries a request_id and is applied at most once (see run_once).
#   - Items are found by UCLA ERP item number (erp_key), never by name.

MAX_BODY_BYTES = 64 * 1024
MAX_ERP_KEY_LENGTH = 64
MAX_NAME_LENGTH = 200
MAX_LOCATION_LENGTH = 200
MAX_ID_LENGTH = 100
MAX_QUANTITY = 2147483647

# ERP item numbers are used in URLs (/items/by-erp/<erp_key>), so they are
# letters, digits, ".", "-" and "_" only, starting with a letter or digit.
ERP_KEY_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')

# API writes run one at a time, so a retry that arrives while the first try is
# still running waits for it and then gets its answer. On the server (one gunicorn
# sync worker, see etc/services.d) requests already run one at a time; the lock
# keeps it that way on a threaded server too (app.run in run-website.py).
__write_lock = threading.Lock()

##################
# AUTH + HELPERS #
##################

class ApiError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status = status
        self.body = dict({'error': message}, **extra)

def __check_api_key():
    if not config.API_KEY:
        raise ApiError(503, "The API is not enabled on this server.")
    header = request.headers.get('Authorization', '')
    supplied = header[7:].strip() if header[:7].lower() == 'bearer ' else ''
    if not supplied or not hmac.compare_digest(supplied.encode('utf-8'), config.API_KEY.encode('utf-8')):
        raise ApiError(401, "Unauthorized.")
    if (request.content_length or 0) > MAX_BODY_BYTES:
        raise ApiError(413, "The request is too large.")
    g.api_client = config.API_CLIENT_NAME

# Check the key, run the endpoint, and always answer in JSON
# (the site-wide error handler would otherwise redirect to the HTML error page).
def api_endpoint(handler):
    @wraps(handler)
    def wrapper(*args, **kwargs):
        try:
            __check_api_key()
            body, status = handler(*args, **kwargs)
        except ApiError as e:
            body, status = e.body, e.status
        except Exception:
            app.logger.error("API error at %s", request.path, exc_info=True)
            body, status = {'error': "Internal error."}, 500
        return jsonify(body), status
    return wrapper

# Run a write at most once per request_id.
#   - The request_id is claimed before the write starts.
#   - The write finished: its answer is stored, and a retry gets that same answer.
#   - The write was refused (an ApiError: nothing was added): the claim is dropped,
#     so the request can be sent again.
#   - The write broke off half-way (a server error, or a restart mid-request): the
#     claim stays, and a retry is refused (409, did_not_finish) instead of being
#     applied a second time. A person checks the audit log on the site.
#   - The request_id was used for a different request: refused (409, request_id_reused).
def run_once(body, kind, write, item_id=None):
    request_id = __text(body, 'request_id', MAX_ID_LENGTH, required=True)
    fingerprint = __fingerprint(body, item_id)
    with __write_lock:
        stored = database.get_api_request(request_id)
        if stored is None and not database.start_api_request(request_id, kind, fingerprint):
            stored = database.get_api_request(request_id)
        if stored is not None:
            return __stored_answer(stored, kind, fingerprint)
        try:
            result, status = write()
        except ApiError:
            database.drop_api_request(request_id)
            raise
        database.finish_api_request(request_id, status, result)
        return result, status

# What a request asks for (everything except its request_id), so a reused
# request_id can be told apart from a retry.
def __fingerprint(body, item_id):
    asked = {key: value for key, value in body.items() if key != 'request_id'}
    text = json.dumps([item_id, asked], sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def __stored_answer(stored, kind, fingerprint):
    if stored['status'] == 0:
        raise ApiError(409, "An earlier try of this request did not finish, so it is not run again. "
                            "Please check the audit log on the website.", code='did_not_finish')
    if stored['kind'] == kind and stored['fingerprint'] == fingerprint:
        return stored['body'], stored['status']
    raise ApiError(409, "This request_id was already used for a different request.", code='request_id_reused')

# The JSON body, read with a hard size limit (also when it comes without a
# Content-Length, e.g. chunked, which the check in __check_api_key cannot see).
def __json_body():
    data = request.stream.read(MAX_BODY_BYTES + 1)
    if len(data) > MAX_BODY_BYTES:
        raise ApiError(413, "The request is too large.")
    try:
        body = json.loads(data) if request.is_json else None
    except (ValueError, RecursionError):                    # not JSON, or nested too deep
        body = None
    if not isinstance(body, dict):
        raise ApiError(400, "A JSON object is required (Content-Type: application/json).")
    return body

# Text from the API is always a JSON string, and never contains HTML (< or >) or
# control characters, so it can never change how a page that shows it is built.
def __text(body, field, max_length, required=False):
    value = body.get(field)
    if value is not None and not isinstance(value, str):
        raise ApiError(400, field + " must be text.")
    value = '' if value is None else value.strip()
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:                              # e.g. half of a surrogate pair
        raise ApiError(400, field + " is not valid text.")
    if required and not value:
        raise ApiError(400, field + " is required.")
    if len(value) > max_length:
        raise ApiError(400, field + " is longer than " + str(max_length) + " characters.")
    if '<' in value or '>' in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ApiError(400, field + " must not contain < or > or control characters.")
    return value

def __erp_key(body):
    erp_key = __text(body, 'erp_key', MAX_ERP_KEY_LENGTH, required=True)
    if not ERP_KEY_PATTERN.fullmatch(erp_key):
        raise ApiError(400, "erp_key may only contain letters, digits, '.', '-' and '_'.")
    return erp_key

def __integer(body, field, minimum, maximum):
    value = body.get(field)
    if value is None:
        raise ApiError(400, field + " is required.")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(400, field + " must be a whole number.")
    if value < minimum or value > maximum:
        raise ApiError(400, field + " must be between " + str(minimum) + " and " + str(maximum) + ".")
    return value

def __item_json(item_id):
    item = database.get_item(item_id)
    if item is None or item['deleted']:
        return None
    subcategory = item['subcategory'] or {}
    return {
        'item_id': item['id'],
        'name': item['name'],
        'category_id': item['category_id'],
        'category_name': item['category_name'],
        'subcategory_id': subcategory.get('id', ''),
        'subcategory_name': subcategory.get('name', ''),
        'location': item['location'],
        'quantity_active': item['quantity_active'],
        'erp_keys': database.get_erp_keys_for_item(item['id']),
    }

# The subcategory a new item goes into: the one asked for (it must belong to the
# category), else the category's "General" subcategory, else its first one.
def __subcategory_for(category_id, subcategory_id):
    active = database.get_all_active_subcategories_for_category(category_id)
    if subcategory_id:
        for subcategory in active:
            if subcategory['id'] == subcategory_id:
                return subcategory_id
        raise ApiError(422, "Unknown subcategory_id for this category.")
    for subcategory in active:
        if subcategory['name'].strip().lower() == 'general':
            return subcategory['id']
    if active:
        return active[0]['id']
    raise ApiError(422, "This category has no active subcategory.")

#############
# ENDPOINTS #
#############

# All active categories with their active subcategories
@app.route('/api/v1/categories', methods=['GET'], provide_automatic_options=False)
@api_endpoint
def api_v1_categories():
    categories = []
    for category in database.get_all_active_categories():
        categories.append({
            'category_id': category['id'],
            'name': category['name'],
            'subcategories': [
                {'subcategory_id': subcategory['id'], 'name': subcategory['name']}
                for subcategory in database.get_all_active_subcategories_for_category(category['id'])
            ],
        })
    return {'categories': categories}, 200

# The item an ERP item number is linked to
@app.route('/api/v1/items/by-erp/<string:erp_key>', methods=['GET'], provide_automatic_options=False)
@api_endpoint
def api_v1_item_by_erp(erp_key):
    item_id = database.get_item_id_for_erp_key(erp_key)
    item = __item_json(item_id) if item_id else None
    if item is None:
        raise ApiError(404, "No item is linked to this erp_key.")
    return item, 200

# Create an item and link its ERP item number
@app.route('/api/v1/items', methods=['POST'], provide_automatic_options=False)
@api_endpoint
def api_v1_create_item():
    body = __json_body()

    def write():
        erp_key = __erp_key(body)
        name = __text(body, 'name', MAX_NAME_LENGTH, required=True)
        location = __text(body, 'location', MAX_LOCATION_LENGTH)
        quantity = __integer(body, 'quantity', 0, MAX_QUANTITY)
        category_id = __text(body, 'category_id', MAX_ID_LENGTH, required=True)

        # Never a second item for the same number - also not when the linked item
        # was deleted on the site: that is for a person to decide (restore it or not).
        linked = database.get_item_id_for_erp_key(erp_key)
        if linked:
            raise ApiError(409, "This erp_key is already linked to an item.", code='erp_key_linked',
                           item_id=linked, item_deleted=__item_json(linked) is None)

        category = database.get_category(category_id)
        if category is None or category['deleted']:
            raise ApiError(422, "Unknown category_id.")
        subcategory_id = __subcategory_for(category_id, __text(body, 'subcategory_id', MAX_ID_LENGTH))

        item_id = database.insert_item(category_id, name, location, quantity, 0, "", "", "", subcategory_id)
        try:
            linked = database.insert_erp_link(erp_key, item_id)
        except BaseException:
            # Linking broke off (an error, or the server shutting down, which raises
            # SystemExit here). Unless the number did get linked to the new item, take
            # that item back, so a new item without its number is never left behind.
            if database.get_item_id_for_erp_key(erp_key) != item_id:
                database.delete_item(item_id)
            raise
        if linked != item_id:
            # The number was linked to another item in the meantime (only possible from
            # outside this process): keep that one, take back the item just made.
            database.delete_item(item_id)
            raise ApiError(409, "This erp_key is already linked to an item.", code='erp_key_linked',
                           item_id=linked, item_deleted=__item_json(linked) is None)
        return __item_json(item_id), 201

    return run_once(body, 'create', write)

@api_endpoint
def __unknown_call():
    raise ApiError(404, "Unknown API call.")

# Anything else under /api/v1 (an unknown path, or a method the call does not
# take): a JSON 404, after the key check, instead of the site's HTML error page.
@app.before_request
def api_v1_unknown():
    if request.routing_exception is None:
        return None
    if request.path != '/api/v1' and not request.path.startswith('/api/v1/'):
        return None
    return __unknown_call()
