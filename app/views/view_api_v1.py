from app import app
from flask import request, jsonify
from functools import wraps

from app.database import db_interface as database

import config
import hmac

# Machine API (v1) for the ScanBase scanning app at UCLA Health Materials Management.
# Endpoints and examples: API.md
#
#   - Off unless MAI_API_KEY is set (503 otherwise). Every call needs
#     "Authorization: Bearer <MAI_API_KEY>".
#   - Errors are always JSON, never the site's HTML error page.

MAX_BODY_BYTES = 64 * 1024

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
