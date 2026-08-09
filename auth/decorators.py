"""
auth/decorators.py
──────────────────
Декоратори захисту ендпоінтів CYBER DATA NEXUS.

Підтримує 2 режими авторизації:
  1. Flask-Login сесія (браузерний flow, cookies)
  2. JWT Bearer token (API flow, Authorization header)

Пріоритет: якщо є валідний Bearer — використовуємо JWT;
            інакше — Flask-Login current_user.
"""

from functools import wraps

from flask import request, jsonify, redirect, url_for, g
from flask_login import current_user, login_required as _fl_login_required

from .models import User
from .service import decode_access_token, touch_last_seen


# ═══════════════════════════════════════════════════════════════
# ВНУТРІШНІ УТИЛІТИ
# ═══════════════════════════════════════════════════════════════

def _is_api_request() -> bool:
    """API-запит: очікує JSON або використовує Bearer token."""
    accept = request.headers.get('Accept', '')
    auth = request.headers.get('Authorization', '')
    return 'application/json' in accept or auth.startswith('Bearer ')


def _extract_jwt_user() -> User | None:
    """
    Витягує та верифікує Bearer token з заголовка.
    Повертає User або None.
    """
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[7:].strip()
    payload = decode_access_token(token)
    if not payload:
        return None
    user = User.query.get(int(payload['sub']))
    if not user or not user.is_active:
        return None
    return user


def get_current_user() -> User | None:
    """
    Повертає поточного авторизованого користувача.
    Перевіряє спочатку Bearer JWT, потім Flask-Login сесію.
    Результат кешується в g.current_auth_user на час запиту.
    """
    if hasattr(g, 'current_auth_user'):
        return g.current_auth_user

    user = _extract_jwt_user()
    if not user and current_user.is_authenticated:
        user = current_user

    g.current_auth_user = user
    if user:
        touch_last_seen(user)
    return user


# ═══════════════════════════════════════════════════════════════
# ДЕКОРАТОРИ
# ═══════════════════════════════════════════════════════════════

def login_required(f):
    """
    Вимагає авторизованого користувача (сесія або JWT).

    - API-запити: 401 JSON
    - Браузерні запити: редирект на /
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            if _is_api_request():
                return jsonify({
                    'error': 'Unauthorized',
                    'message': 'Authentication required.',
                }), 401
            return redirect(url_for('home'))
        return f(*args, **kwargs)

    return decorated


def permission_required(permission: str):
    """
    Вимагає конкретний дозвіл.

    Використання:
        @permission_required('files:upload')
        def upload(): ...
    """

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = get_current_user()
            if not user:
                if _is_api_request():
                    return jsonify({'error': 'Unauthorized'}), 401
                return redirect(url_for('home'))
            if not user.has_permission(permission):
                if _is_api_request():
                    return jsonify({
                        'error': 'Forbidden',
                        'message': f'Required permission: {permission}',
                        'your_role': user.role,
                    }), 403
                return jsonify({'error': 'Forbidden'}), 403
            return f(*args, **kwargs)

        return decorated

    return decorator


def role_required(*roles: str):
    """
    Вимагає одну з вказаних ролей.

    Використання:
        @role_required('admin')
        def admin_panel(): ...

        @role_required('admin', 'editor')
        def edit(): ...
    """

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = get_current_user()
            if not user:
                if _is_api_request():
                    return jsonify({'error': 'Unauthorized'}), 401
                return redirect(url_for('home'))
            if user.role not in roles:
                if _is_api_request():
                    return jsonify({
                        'error': 'Forbidden',
                        'message': f'Required role(s): {", ".join(roles)}',
                        'your_role': user.role,
                    }), 403
                return jsonify({'error': 'Forbidden'}), 403
            return f(*args, **kwargs)

        return decorated

    return decorator


def admin_required(f):
    """Скорочення для @role_required('admin')."""
    return role_required('admin')(f)