"""
auth/routes.py
──────────────
Blueprint /auth  і  /api/auth/* — всі ендпоінти авторизації.

Маршрути:
  POST /api/auth/register          реєстрація
  POST /api/auth/login             вхід (видає JWT + встановлює сесію)
  POST /api/auth/logout            вихід
  POST /api/auth/refresh           оновити access token
  GET  /api/auth/me                поточний користувач
  PUT  /api/auth/me                оновити профіль
  PUT  /api/auth/me/password       змінити пароль
  PUT  /api/auth/me/notifications  налаштування сповіщень
  GET  /api/auth/password-strength перевірка надійності пароля
"""

from flask import Blueprint, request, jsonify, session
from flask_login import login_user, logout_user

from .models   import db, User
from .service  import (
    register_user, login_user_service, generate_tokens,
    refresh_access_token, update_user_profile, update_user_password,
    update_notif_settings, password_strength,
)
from .decorators import login_required, get_current_user

auth_bp = Blueprint('auth_bp', __name__, url_prefix='/api/auth')


# ─── Реєстрація ────────────────────────────────────────────────

@auth_bp.route('/register', methods=['POST'])
def register():
    """
    POST /api/auth/register
    Body: { email, username, password, first_name, last_name? }

    Перший зареєстрований користувач отримує роль admin.
    """
    data = request.get_json(silent=True) or {}
    user, errors = register_user(data)
    if errors:
        return jsonify({'success': False, 'errors': errors}), 422

    tokens = generate_tokens(user)
    login_user(user, remember=False)

    return jsonify({
        'success': True,
        'user':    user.to_dict(),
        **tokens,
    }), 201


# ─── Вхід ──────────────────────────────────────────────────────

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    POST /api/auth/login
    Body: { email, password, remember_me? }

    Повертає JWT-токени + встановлює Flask-Login сесію.
    """
    data     = request.get_json(silent=True) or {}
    email    = data.get('email', '')
    password = data.get('password', '')
    remember = bool(data.get('remember_me', False))

    user, error = login_user_service(email, password)
    if not user:
        return jsonify({'success': False, 'error': error}), 401

    tokens = generate_tokens(user)
    login_user(user, remember=remember)

    return jsonify({
        'success': True,
        'user':    user.to_dict(),
        **tokens,
    })


# ─── Вихід ─────────────────────────────────────────────────────

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    POST /api/auth/logout
    Видаляє Flask-Login сесію. JWT інвалідуються на клієнті.
    """
    logout_user()
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out.'})


# ─── Оновлення токена ───────────────────────────────────────────

@auth_bp.route('/refresh', methods=['POST'])
def token_refresh():
    """
    POST /api/auth/refresh
    Body: { refresh_token }

    Повертає новий access token.
    """
    data    = request.get_json(silent=True) or {}
    rt      = data.get('refresh_token', '')
    tokens  = refresh_access_token(rt)
    if not tokens:
        return jsonify({'success': False, 'error': 'Invalid or expired refresh token.'}), 401
    return jsonify({'success': True, **tokens})


# ─── Поточний користувач ───────────────────────────────────────

@auth_bp.route('/me', methods=['GET'])
@login_required
def me():
    """
    GET /api/auth/me
    Повертає дані поточного авторизованого користувача + stats файлів.
    Stats беруться з data_manager (імпорт з головного app через current_app).
    """
    from flask import current_app
    user      = get_current_user()
    user_dict = user.to_dict(include_sensitive=True)

    # Додаємо статистику файлів якщо data_manager доступний
    try:
        dm    = current_app.config.get('DATA_MANAGER')
        if dm:
            raw   = dm.get_stats()
            tags  = len({t for f in dm.files for t in f.tags})
            user_dict['stats'] = {
                'total_files': raw['total_files'],
                'total_size':  raw['total_size'],
                'categories':  len(raw['categories']),
                'total_tags':  tags,
            }
    except Exception:
        user_dict['stats'] = {'total_files': 0, 'total_size': 0, 'categories': 0, 'total_tags': 0}

    return jsonify({'success': True, 'user': user_dict})


@auth_bp.route('/me', methods=['PUT', 'PATCH'])
@login_required
def update_me():
    """
    PUT/PATCH /api/auth/me
    Body: { first_name?, last_name?, phone?, location?, bio?, language?, timezone?, ... }
    """
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    updated = update_user_profile(user, data)
    if not updated:
        return jsonify({'success': False, 'error': 'No valid fields provided.'}), 400
    return jsonify({'success': True, 'updated': updated, 'user': user.to_dict()})


@auth_bp.route('/me/password', methods=['PUT'])
@login_required
def change_password():
    """
    PUT /api/auth/me/password
    Body: { old_password, new_password }
    """
    user = get_current_user()
    data     = request.get_json(silent=True) or {}
    old_pass = data.get('old_password', '')
    new_pass = data.get('new_password', '')

    errors = update_user_password(user, old_pass, new_pass)
    if errors:
        return jsonify({'success': False, 'errors': errors}), 422

    # Видаємо нові токени щоб не відлогінювати
    tokens = generate_tokens(user)
    return jsonify({'success': True, 'message': 'Password updated.', **tokens})


@auth_bp.route('/me/notifications', methods=['PUT', 'PATCH'])
@login_required
def update_my_notifications():
    """
    PUT /api/auth/me/notifications
    Body: { email_upload?: bool, email_storage?: bool, ... }
    """
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    updated = update_notif_settings(user, data)
    return jsonify({'success': True, 'updated': updated})


# ─── Утиліта ───────────────────────────────────────────────────

@auth_bp.route('/password-strength', methods=['POST'])
def check_password_strength():
    """
    POST /api/auth/password-strength
    Body: { password }
    Клієнт може перевіряти надійність під час введення.
    """
    data = request.get_json(silent=True) or {}
    pwd  = data.get('password', '')
    return jsonify(password_strength(pwd))