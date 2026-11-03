from app import app
from flask import request, jsonify, g
from functools import wraps

from app.database import db_interface as database

import config
import hmac

# Machine API (v1) for the ScanBase scanning app at UCLA Health Materials Management.
# Endpoints and examples: API.md
#
#   - Off unless MAI_API_KEY is set (503 otherwise). Every call needs
#     "Authorization: Bearer <MAI_API_KEY>".
#   - Changes go through the normal database functions, so they appear in the
#     audit log, under the name in MAI_API_CLIENT_NAME.
#   - Every write carries a request_id. The answer to a write that succeeded is
#     stored and returned again for a retry, so a retry is never applied twice.
#     (A write that failed changed nothing, so it is simply checked again.)
#   - Items are found by UCLA ERP item number (erp_key), never by name.

MAX_ERP_KEY_LENGTH = 64
MAX_NAME_LENGTH = 200
MAX_LOCATION_LENGTH = 200
MAX_ID_LENGTH = 100
MAX_QUANTITY = 2147483647

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
    supplied = header[7:].strip() if header.startswith('Bearer ') else ''
    if not supplied or not hmac.compare_digest(supplied.encode('utf-8'), config.API_KEY.encode('utf-8')):
        raise ApiError(401, "Unauthorized.")
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

# Run a write once per request_id: a retry of a write that succeeded gets the
# same answer back and changes nothing.
def run_once(body, write):
    request_id = __text(body, 'request_id', MAX_ID_LENGTH, required=True)
    stored = database.get_api_request(request_id)
    if stored:
        return stored[1], stored[0]
    result, status = write()
    database.insert_api_request(request_id, status, result)
    return result, status

def __json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "A JSON object is required.")
    return body

# Text from the API never contains HTML (< or >) or control characters, so it can
# never change how a page that shows it is built.
def __text(body, field, max_length, required=False):
    value = body.get(field)
    value = '' if value is None else str(value).strip()
    if required and not value:
        raise ApiError(400, field + " is required.")
    if len(value) > max_length:
        raise ApiError(400, field + " is longer than " + str(max_length) + " characters.")
    if '<' in value or '>' in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ApiError(400, field + " must not contain < or > or control characters.")
    return value

def __integer(body, field, minimum, maximum):
    value = body.get(field)
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
# category), else the category's "General" subcategory.
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
@app.route('/api/v1/categories', methods=['GET'])
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
@app.route('/api/v1/items/by-erp/<string:erp_key>', methods=['GET'])
@api_endpoint
def api_v1_item_by_erp(erp_key):
    item_id = database.get_item_id_for_erp_key(erp_key)
    item = __item_json(item_id) if item_id else None
    if item is None:
        raise ApiError(404, "No item is linked to this erp_key.")
    return item, 200

# Create an item and link its ERP item number
@app.route('/api/v1/items', methods=['POST'])
@api_endpoint
def api_v1_create_item():
    body = __json_body()

    def write():
        erp_key = __text(body, 'erp_key', MAX_ERP_KEY_LENGTH, required=True)
        name = __text(body, 'name', MAX_NAME_LENGTH, required=True)
        location = __text(body, 'location', MAX_LOCATION_LENGTH)
        quantity = __integer(body, 'quantity', 0, MAX_QUANTITY)
        category_id = __text(body, 'category_id', MAX_ID_LENGTH, required=True)

        # Never a second item for the same number - also not when the linked item
        # was deleted on the site: that is for a person to decide (restore it or not).
        linked = database.get_item_id_for_erp_key(erp_key)
        if linked:
            raise ApiError(409, "This erp_key is already linked to an item.",
                           item_id=linked, item_deleted=__item_json(linked) is None)

        category = database.get_category(category_id)
        if category is None or category['deleted']:
            raise ApiError(422, "Unknown category_id.")
        subcategory_id = __subcategory_for(category_id, __text(body, 'subcategory_id', MAX_ID_LENGTH))

        item_id = database.insert_item(category_id, name, location, quantity, 0, "", "", "", subcategory_id)
        database.insert_erp_link(erp_key, item_id)
        return __item_json(item_id), 201

    return run_once(body, write)

# Add to (or subtract from) an item's active quantity
@app.route('/api/v1/items/<string:item_id>/quantity', methods=['POST'])
@api_endpoint
def api_v1_item_quantity(item_id):
    body = __json_body()

    def write():
        diff = __integer(body, 'delta', -MAX_QUANTITY, MAX_QUANTITY)
        item = __item_json(item_id)
        if item is None:
            raise ApiError(404, "Item not found.")
        # Same rule as check-out on the website: never below 0.
        if item['quantity_active'] + diff < 0:
            raise ApiError(422, "Not enough in stock.", quantity_active=item['quantity_active'])
        new_quantity = database.add_item_quantity_active(item_id, diff)
        if new_quantity is None:
            raise ApiError(409, "The item changed at the same time. Please try again.")
        return {'item_id': item_id, 'quantity_active': new_quantity}, 200

    return run_once(body, write)

# Link one more ERP item number to an existing item (e.g. during a re-scan)
@app.route('/api/v1/items/<string:item_id>/erp-links', methods=['POST'])
@api_endpoint
def api_v1_item_erp_link(item_id):
    body = __json_body()

    def write():
        erp_key = __text(body, 'erp_key', MAX_ERP_KEY_LENGTH, required=True)
        if __item_json(item_id) is None:
            raise ApiError(404, "Item not found.")
        linked = database.insert_erp_link(erp_key, item_id)
        if linked != item_id:
            raise ApiError(409, "This erp_key is already linked to another item.", item_id=linked)
        return __item_json(item_id), 200

    return run_once(body, write)

# Anything else under /api/v1 (unknown path or method): a JSON 404, after the key
# check, instead of the site's HTML error page.
@app.route('/api/v1/<path:anything>', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
@api_endpoint
def api_v1_unknown(anything):
    raise ApiError(404, "Unknown API call.")
