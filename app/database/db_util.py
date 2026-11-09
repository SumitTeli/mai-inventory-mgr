import sqlite3
from datetime import datetime
from flask import request, g, has_request_context
import logging
import os
from . import db_interface
import config

DATA_DB_PATH = config.DB_ROOT + 'mai.db'
DATA_DB_NAME = 'mai-db'
DATA_DB_VERSION = 12

LOG_DB_PATH = config.DB_ROOT + 'mai-log.db'
LOG_DB_NAME = 'mai-logs'
LOG_DB_VERSION = 0

##################
# CORE FUNCTIONS #
##################

# Initializes the database. To be called ONCE from application startup
def init_db():
    __init_data_db()
    __init_log_db()

#####################
# DATA DB FUNCTIONS #
#####################

def __init_data_db():
    db_connection = get_data_db()
    __check_data_table(db_connection)
    __upgrade_data_db(db_connection)

def __ensure_db_parent_dir(db_path):
    parent_dir = os.path.dirname(db_path)
    if parent_dir:
        if config.STAGE == "dev":
            os.makedirs(parent_dir, exist_ok=True)
        elif not os.path.isdir(parent_dir):
            raise RuntimeError(
                "Database directory does not exist: " + parent_dir +
                ". In non-dev environments this should be provisioned before startup."
            )

def __ensure_primary_data_db_present():
    if config.STAGE != "dev" and not os.path.isfile(DATA_DB_PATH):
        raise RuntimeError(
            "Primary data database is missing at " + DATA_DB_PATH +
            ". Expected Litestream restore before initialization."
        )

def get_data_db():
    __ensure_db_parent_dir(DATA_DB_PATH)
    __ensure_primary_data_db_present()
    db_connection = sqlite3.connect(DATA_DB_PATH)
    db_connection.execute('pragma journal_mode=wal')
    return db_connection

def __check_data_table(db_connection):
    cursor = db_connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS category (
            category_id text, name text, deleted int,
            UNIQUE(category_id)
        )
        """
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subcategory (
            subcategory_id text, category_id text, name text, deleted int,
            UNIQUE(subcategory_id)
        )
        """
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS item (
            item_id text, category_id text, name text, location text, quantity_active int, quantity_expired int, notes_public text, url text, deleted int, notes_private text, subcategory_id text,
            UNIQUE(item_id)
        )
        """
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user (
            user_id text, user_name text, user_email text, user_role int, user_picture text,
            UNIQUE(user_id)
        )
        """
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS image (
            image_id text, image_url text, deletion_hash text, item_id text,
            UNIQUE(image_id)
        )
        """
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit (
            date int, type text, id text, user text, event text, before text, after text
        )
        """
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS version (
            db_name text, db_version int,
            UNIQUE(db_name)
        )"""
    )

    # Used only by the machine API (/api/v1, see API.md): which item a UCLA ERP item
    # number belongs to. Several numbers can point at one item; a number points at
    # one item only. No existing table changes.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS item_erp_link (
            erp_key text, item_id text, date int,
            UNIQUE(erp_key)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS item_erp_link_item_id ON item_erp_link (item_id)")

    # Used only by the machine API (/api/v1): every write by request_id - what it
    # was (kind + fingerprint of the request) and its answer (status 0 while it
    # runs) - so that a retried request is answered again instead of being applied
    # twice. No existing table changes.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_request (
            request_id text, kind text, fingerprint text, status int, body text, date int,
            UNIQUE(request_id)
        )
        """
    )

    cursor.execute("""
        INSERT OR IGNORE INTO version (db_name, db_version)
        VALUES(?, ?)""", (
            DATA_DB_NAME,
            DATA_DB_VERSION
    ))
    cursor.close()
    db_connection.commit()

def __upgrade_data_db(db_connection):
    current_version = -1
    cursor = db_connection.cursor()

    # Get current db version
    query_results = cursor.execute("""
        SELECT db_version FROM version WHERE db_name=?""", (
            str(DATA_DB_NAME),
    ))

    for row in query_results:
        current_version = int(row[0])

    logging.info("Latest data database version: " + str(current_version))
    logging.info("Expected data database version: " + str(DATA_DB_VERSION))

    if current_version == -1:
        raise Exception("Error: was not able to pull the current db version")
    
    if current_version == DATA_DB_VERSION:
        logging.info("No data database update is needed.")
        return

    if current_version < 2:
        # Upgrade to v2.0
        logging.info("Upgrading data database to 2.0")

        cursor.execute("""
            ALTER TABLE user ADD COLUMN user_picture text DEFAULT '/static/mai_logo.png'
        
        """)
    
        cursor.execute("""
            INSERT OR REPLACE INTO version (db_name, db_version)
            VALUES(?, ?)""", (
                DATA_DB_NAME,
                2
        ))

    if current_version < 3:
        # Upgrade to v3.0
        logging.info("Upgrading data database to 3.0")

        cursor.execute("""
            ALTER TABLE item ADD COLUMN deleted int DEFAULT '0'
        """)

        cursor.execute("""
            INSERT OR REPLACE INTO version (db_name, db_version)
            VALUES(?, ?)""", (
                DATA_DB_NAME,
                3
        ))

    if current_version < 4:
        # Upgrade to v4.0
        logging.info("Upgrading data database to 4.0")

        query_results = cursor.execute("""
                SELECT * FROM item_audit
            """)
        
        result = []
        for row in query_results:
            # Temporarily store in result list, can't reuse cursor
            result.append(row)

        for row in result:
            cursor.execute("""
                INSERT OR IGNORE INTO audit (date, type, id, user, event, before, after)
                VALUES(?, ?, ?, ?, ?, ?, ?)""", (
                    int(row[0]), 
                    str("ITEM"),
                    str(row[1]), 
                    str(row[2]), 
                    str(row[3]),
                    str(row[4]),
                    str(row[5])
            ))
        
        # Delete the now-unused table
        cursor.execute("""
            DROP TABLE item_audit
        """)

        cursor.execute("""
            INSERT OR REPLACE INTO version (db_name, db_version)
            VALUES(?, ?)""", (
                DATA_DB_NAME,
                4
        ))

    if current_version < 5:
        # Upgrade to v5.0
        logging.info("Upgrading data database to 5.0")

        # Delete the now-unused table
        cursor.execute("""
            DROP TABLE history
        """)

        cursor.execute("""
            INSERT OR REPLACE INTO version (db_name, db_version)
            VALUES(?, ?)""", (
                DATA_DB_NAME,
                5
        ))

    # [mai120] Removing expired quantity, adding to active quantity
    if current_version < 6:
        # Upgrade to v6.0
        logging.info("Upgrading data database to 6.0")

        for item in db_interface.db_item.get_all_items():
            new_quantity = int(item['quantity_active']) + int(item['quantity_expired'])
            db_interface.db_item.update_item(item['id'], item['name'], item['category_id'], item['location'], int(new_quantity), int(0), item['notes'], item['url'])

        cursor.execute("""
            INSERT OR REPLACE INTO version (db_name, db_version)
            VALUES(?, ?)""", (
                DATA_DB_NAME,
                6
        ))

    # [mai127] Do not actually delete categories, simply mark them as "deleted"
    if current_version < 7:
        # Upgrade to v7.0
        logging.info("Upgrading data database to 7.0")

        cursor.execute("""
            ALTER TABLE category ADD COLUMN deleted int DEFAULT 0
        """)

        cursor.execute("""
            INSERT OR REPLACE INTO version (db_name, db_version)
            VALUES(?, ?)""", (
                DATA_DB_NAME,
                7
        ))

    # [mai139] Enable a extra hidden notes field that is visible only to members of MAI
    if current_version < 8:
        # Upgrade to v8.0
        logging.info("Upgrading data database to 8.0")

        cursor.execute("""
            ALTER TABLE item RENAME COLUMN notes TO notes_public
        """)

        cursor.execute("""
            ALTER TABLE item ADD COLUMN notes_private text DEFAULT ''
        """)

        cursor.execute("""
            INSERT OR REPLACE INTO version (db_name, db_version)
            VALUES(?, ?)""", (
                DATA_DB_NAME,
                8
        ))

    # [mai152] Removing all barcodes from webapp
    if current_version < 9:
        # Upgrade to v9.0
        logging.info("Upgrading data database to 9.0")

        # This code has been removed and will no longer work.
        # for barcode in db_interface.get_all_barcodes():
        #     db_interface.delete_barcode(barcode['barcode'])

        cursor.execute("""
            INSERT OR REPLACE INTO version (db_name, db_version)
            VALUES(?, ?)""", (
                DATA_DB_NAME,
                9
        ))   

    # [mai153] Drop barcode table
    if current_version < 10:
        # Upgrade to v10.0
        logging.info("Upgrading data database to 10.0")

        # Delete the now-unused table
        cursor.execute("""
            DROP TABLE barcode
        """)

        cursor.execute("""
            INSERT OR REPLACE INTO version (db_name, db_version)
            VALUES(?, ?)""", (
                DATA_DB_NAME,
                10
        ))   

    # [????] Enable subcategories within item db
    if current_version < 11:
        # Upgrade to v11.0
        logging.info("Upgrading data database to 11.0")

        cursor.execute("""
            ALTER TABLE item ADD COLUMN subcategory_id text DEFAULT ''
        """)

        cursor.execute("""
            INSERT OR REPLACE INTO version (db_name, db_version)
            VALUES(?, ?)""", (
                DATA_DB_NAME,
                11
        ))
    
    if current_version < 12:
        # Upgrade to v12.0
        logging.info("Upgrading data database to 12.0")

        # This is important - db will lock otherwise, the v12 upgrade is write intensive.
        db_connection.commit()

        for category in db_interface.get_all_categories():
            # Create a "general" subcategory for this category
            db_interface.insert_subcategory('General', category_id=category['id'])

        # Get all these new default subcategories
        cached_subcategories = {}
        for subcategory in db_interface.get_all_subcategories():
            cached_subcategories[subcategory['category_id']] = subcategory['id']
        
        # Insert correct default subcategory into each item
        for item in db_interface.get_all_items():
            subcategory = cached_subcategories[item['category_id']]
            db_interface.update_item(item['id'], item['name'], item['category_id'], item['location'], item['quantity_active'], item['quantity_expired'], item['notes_public'], item['url'], item['notes_private'], subcategory)

        cursor.execute("""
            INSERT OR REPLACE INTO version (db_name, db_version)
            VALUES(?, ?)""", (
                DATA_DB_NAME,
                12
        ))

    # Finally, commit the changes and close the cursor.
    db_connection.commit()
    cursor.close()

####################
# LOG DB FUNCTIONS #
####################

def __init_log_db():
    __ensure_db_parent_dir(LOG_DB_PATH)
    db_connection = sqlite3.connect(LOG_DB_PATH)
    __check_log_table(db_connection)
    __upgrade_log_db(db_connection)

def __get_log_db():
    __ensure_db_parent_dir(LOG_DB_PATH)
    db_connection = sqlite3.connect(LOG_DB_PATH)
    db_connection.execute('pragma journal_mode=wal')
    return db_connection

def __check_log_table(db_connection):
    cursor = db_connection.cursor()
    logging.info("Checking log table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS error_log (
            date int, source text, log_level int, log_level_name text, message text, args text, 
            module text, function_name text, line_num int, exception text, process int, thread text, thread_name text
        )"""
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS access_log (
            date int, source text, log_level int, log_level_name text, message text, args text, 
            module text, function_name text, line_num int, exception text, process int, thread text, thread_name text
        )"""
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS latency_log (
            date int, path text, time int
        )"""
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS version (
            db_name text, db_version int,
            UNIQUE(db_name)
        )"""
    )
    cursor.execute("""
        INSERT OR IGNORE INTO version (db_name, db_version)
        VALUES(?, ?)""", (
            LOG_DB_NAME,
            LOG_DB_VERSION
    ))

    db_connection.commit()
    cursor.close()

def __upgrade_log_db(db_connection):
    current_version = -1
    cursor = db_connection.cursor()

    # Get current db version
    query_results = cursor.execute("""
        SELECT db_version FROM version WHERE db_name=?""", (
            str(LOG_DB_NAME),
    ))

    for row in query_results:
        current_version = int(row[0])

    logging.info("Latest log database version: " + str(current_version))
    logging.info("Expected log database version: " + str(LOG_DB_VERSION))

    if current_version == -1:
        raise Exception("Error: was not able to pull the current log db version")
    
    if current_version == LOG_DB_VERSION:
        logging.info("No log database update is needed.")
        return

    # Finally, commit the changes and close the cursor.
    db_connection.commit()
    cursor.close()

####################
# HELPER FUNCTIONS #
####################

# Format a timestamp into a string
def format_timestamp(time):
    dt_object = datetime.fromtimestamp(time)
    return dt_object.strftime('%d-%b-%Y %H:%M:%S')    

# Get user if authenticated, otherwise fall back to ip address
def get_username(user):
    username = ""

    # A request through the machine API (/api/v1) is shown under the API client's name
    if has_request_context() and getattr(g, 'api_client', None):
        return str(g.api_client)

    if not user:
        return "unknown"

    try:
        if user.is_authenticated:
            username = user.email
        else:
            ip_address = ""
            if request.environ.get('HTTP_X_FORWARDED_FOR') is None:
                ip_address = str(request.environ['REMOTE_ADDR'])
            else:
                ip_address = str(request.environ['HTTP_X_FORWARDED_FOR']) # if behind a proxy
            username = ip_address
        return username
    except:
        return "unknown"