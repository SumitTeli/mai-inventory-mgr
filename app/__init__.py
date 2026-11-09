from flask import Flask
from logging.config import dictConfig
from app.logging.logging_cfg import LOGGING_CONFIGURATION
from flask_login import LoginManager
from flask_compress import Compress
from app.user import User

import os

class ReverseProxied(object):
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        scheme = environ.get('HTTP_X_FORWARDED_PROTO')
        if scheme:
            environ['wsgi.url_scheme'] = scheme
        return self.app(environ, start_response)

# Initialize the app
app = Flask(__name__, instance_relative_config=True)
Compress(app)
app.secret_key = os.environ.get("MAI_SECRET_KEY") or os.urandom(24)
app.wsgi_app = ReverseProxied(app.wsgi_app)

# Auth
login_manager = LoginManager()
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

# Load the views
from app.views import (
    view_api,
    view_api_v1,
    view_auth,
    view_delete,
    view_edit,
    view_general,
    view_register,
    view_search,
    view_view,
    view_error
)

# Load the config file
app.config.from_object('config')

# Set up logging configuration
dictConfig(LOGGING_CONFIGURATION)