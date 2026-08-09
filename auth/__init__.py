"""
auth/__init__.py
────────────────
Пакет авторизації CYBER DATA NEXUS.

Експортує:
  db           — SQLAlchemy instance
  bcrypt       — Flask-Bcrypt instance
  login_manager — Flask-Login instance
  auth_bp      — Blueprint /api/auth/*
  admin_bp     — Blueprint /api/admin/*

Функція init_auth(app) реєструє все в Flask-застосунку.
"""

from flask_login import LoginManager

from .models import db, User
from .service import bcrypt
from .routes import auth_bp
from .admin_routes import admin_bp

login_manager = LoginManager()


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    """Flask-Login: завантажує користувача з БД за id із сесії."""
    try:
        return User.query.get(int(user_id))
    except (ValueError, TypeError):
        return None


def init_auth(app) -> None:
    """
    Ініціалізує всі компоненти авторизації та реєструє Blueprints.

    Виклик у create_app():
        init_auth(app)
    """
    # Ініціалізація розширень
    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)

    # Flask-Login: куди редиректити неавторизованих
    login_manager.login_view = 'home'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'warning'

    # Реєстрація Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    # Створення таблиць (якщо ще не існують)
    with app.app_context():
        db.create_all()


__all__ = [
    'db',
    'bcrypt',
    'login_manager',
    'auth_bp',
    'admin_bp',
    'init_auth',
    'User',
]