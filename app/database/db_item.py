import uuid

from . import db_util as db
from . import db_category, db_image, db_audit, db_subcategory

##################
# ITEM FUNCTIONS #
##################

# Insert an item
def insert_item(category_id, name, location="", quantity_active=0, quantity_expired=0, notes_public="", url="", notes_private="", subcategory_id=""):
    item_id = str(uuid.uuid4())

    db_connection = db.get_data_db()
    cursor = db_connection.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO item (item_id, category_id, name, location, quantity_active, quantity_expired, notes_public, url, deleted, notes_private, subcategory_id)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            str(item_id).strip(),
            str(category_id).strip(),
            str(name).strip(),
            str(location).strip(),
            int(quantity_active),
            int(quantity_expired),
            str(notes_public),
            str(url).strip(),
            0,
            str(notes_private),
            str(subcategory_id).strip(),
        ))

    db_connection.commit()
    cursor.close()

    # Log the creation of the new item.
    db_audit.insert_item_audit_event(item_id, "Created item.", "", get_item(item_id))

    return item_id

# Return true if item_id already exists
def exists_item_id(item_id):
    cursor = db.get_data_db().cursor()

    query_result = cursor.execute("""
        SELECT EXISTS(SELECT 1 FROM item WHERE item_id=? LIMIT 1)""", (
            str(item_id).strip(),
    ))
    
    for row in query_result:
        exists = (row[0] == 1)
        cursor.close()
        return exists

# Get an item for a given item_id
def get_item(item_id):
    result = None
    cursor = db.get_data_db().cursor()

    query_results = cursor.execute("""
        SELECT * FROM item WHERE item_id=?""", (
            str(item_id).strip(),
    ))

    for row in query_results:
        result = {
            'id': str(row[0]),
            'category_id': str(row[1]),
            'category_name': db_category.get_category(str(row[1]))['name'],
            'category_status': db_category.get_category(str(row[1]))['deleted'],
            'name': str(row[2]),
            'location': str(row[3]),
            'quantity_active': int(row[4]),
            'quantity_expired': int(row[5]),
            'notes_public': str(row[6]),
            'url': str(row[7]),
            'deleted': bool(row[8]),
            'notes_private': str(row[9]),
            'subcategory': db_subcategory.get_subcategory(str(row[10])),
        }

    cursor.close()
    return result

# Get all items
def get_all_items():
    result = []
    cursor = db.get_data_db().cursor()
    
    ## Cache list of categories
    cached_categories = {}
    for category in db_category.get_all_categories():
        cached_categories[category['id']] = category['name']

    ## Cache list of subcategories
    cached_subcategories = {}
    for subcategory in db_subcategory.get_all_subcategories():
        cached_subcategories[subcategory['id']] = subcategory['name']

    query_results = cursor.execute("""
        SELECT * FROM item WHERE deleted=0 ORDER BY name COLLATE NOCASE ASC""", (
    ))

    for row in query_results:
        result.append({
            'id': str(row[0]),
            'category_id': str(row[1]),
            'category_name': cached_categories[str(row[1])],
            'name': str(row[2]),
            'location': str(row[3]),
            'quantity_active': int(row[4]),
            'quantity_expired': int(row[5]),
            'notes_public': str(row[6]),
            'url': str(row[7]),
            'deleted': bool(row[8]),
            'notes_private': str(row[9]),
            'subcategory': db_subcategory.get_subcategory(str(row[10])),
        })

    cursor.close()
    result.sort(key=lambda k: str(k['category_name']).lower())
    return result

# Get all deleted items
def get_all_deleted_items():
    result = []
    cursor = db.get_data_db().cursor()
    
    # # Cache list of categories
    cached_categories = {}
    for category in db_category.get_all_categories():
        cached_categories[category['id']] = category['name']

    query_results = cursor.execute("""
        SELECT * FROM item WHERE deleted=1 ORDER BY name COLLATE NOCASE ASC""", (
    ))

    for row in query_results:
        result.append({
            'id': str(row[0]),
            'category_id': str(row[1]),
            'category_name': cached_categories[str(row[1])],
            'name': str(row[2]),
            'location': str(row[3]),
            'quantity_active': int(row[4]),
            'quantity_expired': int(row[5]),
            'notes_public': str(row[6]),
            'url': str(row[7]),
            'deleted': bool(row[8]),
            'notes_private': str(row[9]),
            'subcategory': db_subcategory.get_subcategory(str(row[10])),
        })

    cursor.close()
    result.sort(key=lambda k: str(k['category_name']).lower())
    return result

# Get all items under a given category
def get_all_items_for_category(category_id):
    result = []
    cursor = db.get_data_db().cursor()

    # Cache category name
    cached_category_name = db_category.get_category(str(category_id).strip())['name']

    query_results = cursor.execute("""
        SELECT * FROM item WHERE category_id=? and deleted=0 ORDER BY name COLLATE NOCASE ASC""", (
            str(category_id).strip(),
    ))

    for row in query_results:
        result.append({
            'id': str(row[0]),
            'category_id': str(row[1]),
            'category_name': cached_category_name,
            'name': str(row[2]),
            'location': str(row[3]),
            'quantity_active': int(row[4]),
            'quantity_expired': int(row[5]),
            'notes_public': str(row[6]),
            'url': str(row[7]),
            'deleted': bool(row[8]),
            'notes_private': str(row[9]),
            'subcategory': db_subcategory.get_subcategory(str(row[10])),
        })

    cursor.close()
    return result

# Get all items under a given subcategory
def get_all_items_for_subcategory(subcategory_id):
    result = []
    cursor = db.get_data_db().cursor()

    # Cache subcategory info
    cached_subcategory = db_subcategory.get_subcategory(subcategory_id)

    # Cache category info
    cached_category = db_category.get_category(cached_subcategory['category_id'])

    query_results = cursor.execute("""
        SELECT * FROM item WHERE subcategory_id=? and deleted=0 ORDER BY name COLLATE NOCASE ASC""", (
            str(subcategory_id).strip(),
    ))

    for row in query_results:
        result.append({
            'id': str(row[0]),
            'category_id': str(row[1]),
            'category_name': cached_category['name'],
            'name': str(row[2]),
            'location': str(row[3]),
            'quantity_active': int(row[4]),
            'quantity_expired': int(row[5]),
            'notes_public': str(row[6]),
            'url': str(row[7]),
            'deleted': bool(row[8]),
            'notes_private': str(row[9]),
            'subcategory': cached_subcategory,
        })

    cursor.close()
    return result

# Update an item with new values
def update_item(item_id, name, category_id, location, quantity_active, quantity_expired, notes_public, url, notes_private, subcategory_id):
    db_connection = db.get_data_db()
    cursor = db_connection.cursor()
    item_before = get_item(item_id)

    cursor.execute("""
        UPDATE item SET name=?, category_id=?, location=?, quantity_active=?, quantity_expired=?, notes_public=?, url=?, notes_private=?, subcategory_id=? WHERE item_id=?""", (
            str(name).strip(),
            str(category_id).strip(),
            str(location).strip(),
            int(quantity_active),
            int(quantity_expired),
            str(notes_public),
            str(url).strip(),
            str(notes_private),
            str(subcategory_id).strip(),
            str(item_id).strip()
        ))
    
    # Save (commit) the changes
    db_connection.commit()
    cursor.close()

    db_audit.insert_item_audit_event(item_id, "Edited item.", item_before, get_item(item_id))

# Update an item's quantity
def update_item_quantity(item_id, new_quantity):
        return update_item_quantity_active(item_id, new_quantity)

# Update an item's active quantity
def update_item_quantity_active(item_id, new_quantity):
    db_connection = db.get_data_db()
    cursor = db_connection.cursor()
    item_before = get_item(item_id)

    cursor.execute("""
        UPDATE item SET quantity_active=? WHERE item_id=?""", (
            int(new_quantity),
            str(item_id).strip()
        ))
    
    # Save (commit) the changes
    db_connection.commit()
    cursor.close()

    db_audit.insert_item_audit_event(item_id, "Updated active quantity.", item_before, get_item(item_id))

# Add to (or subtract from) an item's active quantity in one statement, so two
# updates at the same time can never overwrite each other. Like check-out, it is
# refused if the quantity would go below 0. Returns the new active quantity, or
# None if nothing changed (item missing or deleted, or not enough in stock).
def add_item_quantity_active(item_id, diff):
    db_connection = db.get_data_db()
    cursor = db_connection.cursor()
    item_before = get_item(item_id)

    cursor.execute("""
        UPDATE item SET quantity_active=quantity_active + ? WHERE item_id=? AND deleted=0 AND quantity_active + ? >= 0""", (
            int(diff),
            str(item_id).strip(),
            int(diff)
        ))
    updated = cursor.rowcount

    # Save (commit) the changes
    db_connection.commit()
    cursor.close()

    if updated == 0:
        return None

    item_after = get_item(item_id)
    db_audit.insert_item_audit_event(item_id, "Updated active quantity.", item_before, item_after)
    return item_after['quantity_active']

# Update an item's expired quantity
def update_item_quantity_expired(item_id, new_quantity):
    db_connection = db.get_data_db()
    cursor = db_connection.cursor()
    item_before = get_item(item_id)

    cursor.execute("""
        UPDATE item SET quantity_expired=? WHERE item_id=?""", (
            int(new_quantity),
            str(item_id).strip()
        ))
    
    # Save (commit) the changes
    db_connection.commit()
    cursor.close()

    db_audit.insert_item_audit_event(item_id, "Updated expired quantity.", item_before, get_item(item_id))

# Delete an item for a given item_id
def delete_item(item_id):
    db_connection = db.get_data_db()
    cursor = db_connection.cursor()
    item_before = get_item(item_id)

    query_results = cursor.execute("""
        UPDATE item SET deleted=? WHERE item_id=?""", (
            1,
            str(item_id).strip(),
    ))

    db_connection.commit()
    cursor.close()

    db_audit.insert_item_audit_event(item_id, "Deleted item.", item_before, get_item(item_id))

# Undo deletion of an item for a given item_id
def restore_deleted_item(item_id):
    db_connection = db.get_data_db()
    cursor = db_connection.cursor()
    item_before = get_item(item_id)

    query_results = cursor.execute("""
        UPDATE item SET deleted=? WHERE item_id=?""", (
            0,
            str(item_id).strip(),
    ))

    db_connection.commit()
    cursor.close()

    db_audit.insert_item_audit_event(item_id, "Restored item.", item_before, get_item(item_id))

# Browse items with filtering, sorting, and pagination
def browse_items(search='', category_id='', subcategory_id='', sort_by='name', sort_order='asc', hide_out_of_stock=False, offset=0, limit=24):
    # Build WHERE clause
    conditions = ['i.deleted = 0']
    params = []

    if search:
        conditions.append('(i.name LIKE ? OR i.notes_public LIKE ? OR i.location LIKE ?)')
        search_param = '%' + search + '%'
        params.extend([search_param, search_param, search_param])

    if category_id:
        conditions.append('i.category_id = ?')
        params.append(category_id)

    if subcategory_id:
        conditions.append('i.subcategory_id = ?')
        params.append(subcategory_id)

    if hide_out_of_stock:
        conditions.append('i.quantity_active > 0')

    where_clause = ' AND '.join(conditions)

    # Whitelisted sort columns to prevent SQL injection
    sort_columns = {
        'name': 'i.name COLLATE NOCASE',
        'category': 'c.name COLLATE NOCASE',
        'quantity': 'i.quantity_active',
    }
    order_col = sort_columns.get(sort_by, 'i.name COLLATE NOCASE')
    order_dir = 'ASC' if sort_order == 'asc' else 'DESC'

    cursor = db.get_data_db().cursor()

    # Get total count
    count_query = 'SELECT COUNT(*) FROM item i WHERE ' + where_clause
    count_result = cursor.execute(count_query, params)
    total_count = 0
    for row in count_result:
        total_count = row[0]

    # Get paginated results with category/subcategory names resolved via JOIN
    data_query = (
        'SELECT i.item_id, i.category_id, c.name, i.name, i.location, i.quantity_active, '
        'i.quantity_expired, i.notes_public, i.url, i.notes_private, s.name '
        'FROM item i '
        'LEFT JOIN category c ON i.category_id = c.category_id AND c.deleted = 0 '
        'LEFT JOIN subcategory s ON i.subcategory_id = s.subcategory_id AND s.deleted = 0 '
        'WHERE ' + where_clause + ' '
        'ORDER BY ' + order_col + ' ' + order_dir + ' '
        'LIMIT ? OFFSET ?'
    )
    data_params = params + [limit, offset]

    query_results = cursor.execute(data_query, data_params)

    result = []
    item_ids = []

    for row in query_results:
        item_id = str(row[0])
        item_ids.append(item_id)
        result.append({
            'id': item_id,
            'category_id': str(row[1]),
            'category_name': str(row[2]) if row[2] is not None else '',
            'name': str(row[3]),
            'location': str(row[4]),
            'quantity_active': int(row[5]),
            'quantity_expired': int(row[6]),
            'notes_public': str(row[7]),
            'url': str(row[8]),
            'subcategory_name': str(row[10]) if row[10] is not None else '',
            'image_url': None,
        })

    cursor.close()

    # Batch-fetch first image for each item (ORDER BY ROWID for deterministic "first" image)
    if item_ids:
        image_cursor = db.get_data_db().cursor()
        placeholders = ','.join(['?' for _ in item_ids])
        image_query = (
            'SELECT item_id, image_url FROM image '
            'WHERE item_id IN (' + placeholders + ') '
            'ORDER BY ROWID'
        )
        image_results = image_cursor.execute(image_query, item_ids)

        image_map = {}
        for img_row in image_results:
            iid = str(img_row[0])
            if iid not in image_map:
                image_map[iid] = str(img_row[1])

        image_cursor.close()

        for item in result:
            item['image_url'] = image_map.get(item['id'])

    return result, total_count