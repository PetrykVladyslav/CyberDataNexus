"""
auth/service.py
───────────────
Виправлення v2:
  - JWT: перевірка що встановлений PyJWT (не python-jwt)
  - Реєстрація: generic повідомлення (без витоку email/username)
  - Транзакції: rollback при будь-якій DB помилці
  - Login: timing-safe перевірка (dummy hash якщо юзер не знайдений)
"""

import json
import re
from datetime import datetime, timedelta, timezone

# ── JWT: безпечний імпорт ──────────────────────────────────────
# Конфлікт: пакети 'jwt' (python-jwt) і 'PyJWT' мають однаковий
# модуль 'jwt', але різний API. PyJWT має .encode(), python-jwt — ні.
import jwt as _jwt_module
if not hasattr(_jwt_module, 'encode'):
    raise ImportError(
        "\n\n[CYBER DATA NEXUS] Конфлікт пакетів JWT!\n"
        "Встановлено 'python-jwt' замість 'PyJWT'.\n"
        "Виконайте у venv:\n"
        "  pip uninstall jwt python-jwt -y\n"
        "  pip install PyJWT\n"
    )
_jwt = _jwt_module

from flask import current_app, request
from flask_bcrypt import Bcrypt

from .models import db, User, AuditLog, Role, ROLE_PERMISSIONS

bcrypt = Bcrypt()

_JWT_ALGORITHM  = 'HS256'
_ACCESS_TTL_MIN = 60
_REFRESH_TTL_D  = 30
_MIN_PASS_LEN   = 8
_USERNAME_RE    = re.compile(r'^[A-Za-z0-9_@.-]{3,64}$')
_EMAIL_RE       = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


# ── Пароль ──────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.generate_password_hash(plain, rounds=12).decode('utf-8')


def check_password(plain: str, hashed: str) -> bool:
    return bcrypt.check_password_hash(hashed, plain)


def password_strength(plain: str) -> dict:
    checks = {
        'length':    len(plain) >= _MIN_PASS_LEN,
        'uppercase': bool(re.search(r'[A-Z]', plain)),
        'digit':     bool(re.search(r'\d', plain)),
        'special':   bool(re.search(r'[^A-Za-z0-9]', plain)),
    }
    score  = sum(checks.values())
    labels = ['Too short', 'Weak', 'Fair', 'Good', 'Strong']
    return {'score': score, 'label': labels[score], 'checks': checks}


# ── JWT ─────────────────────────────────────────────────────────

def _secret() -> str:
    return current_app.config['SECRET_KEY']


def generate_tokens(user: User) -> dict:
    now = datetime.now(timezone.utc)
    access_payload = {
        'sub':         str(user.id),
        'email':       user.email,
        'username':    user.username,
        'role':        user.role,
        'permissions': sorted(ROLE_PERMISSIONS.get(user.role, set())),
        'type':        'access',
        'iat':         int(now.timestamp()),
        'exp':         int((now + timedelta(minutes=_ACCESS_TTL_MIN)).timestamp()),
    }
    refresh_payload = {
        'sub':  str(user.id),
        'type': 'refresh',
        'iat':  int(now.timestamp()),
        'exp':  int((now + timedelta(days=_REFRESH_TTL_D)).timestamp()),
    }
    return {
        'access_token':  _jwt.encode(access_payload,  _secret(), algorithm=_JWT_ALGORITHM),
        'refresh_token': _jwt.encode(refresh_payload, _secret(), algorithm=_JWT_ALGORITHM),
        'token_type':    'Bearer',
        'expires_in':    _ACCESS_TTL_MIN * 60,
    }


def decode_access_token(token: str) -> 'dict | None':
    try:
        payload = _jwt.decode(token, _secret(), algorithms=[_JWT_ALGORITHM])
        return payload if payload.get('type') == 'access' else None
    except (_jwt.ExpiredSignatureError, _jwt.InvalidTokenError):
        return None


def decode_refresh_token(token: str) -> 'int | None':
    try:
        payload = _jwt.decode(token, _secret(), algorithms=[_JWT_ALGORITHM])
        if payload.get('type') != 'refresh':
            return None
        return int(payload['sub'])
    except _jwt.InvalidTokenError:
        return None


def refresh_access_token(refresh_token: str) -> 'dict | None':
    user_id = decode_refresh_token(refresh_token)
    if not user_id:
        return None
    user = User.query.get(user_id)
    if not user or not user.is_active:
        return None
    return generate_tokens(user)


# ── Валідація ────────────────────────────────────────────────────

def validate_registration(data: dict) -> list:
    """
    БЕЗПЕКА: не розкриваємо чи email/username вже існує.
    Повертає generic повідомлення при конфлікті (no user enumeration).
    """
    errors = []
    email    = (data.get('email') or '').strip().lower()
    username = (data.get('username') or '').strip().lstrip('@')
    password = data.get('password', '')
    first    = (data.get('first_name') or '').strip()

    if not email:
        errors.append('Email is required.')
    elif not _EMAIL_RE.match(email):
        errors.append('Invalid email format.')

    if not username:
        errors.append('Username is required.')
    elif not _USERNAME_RE.match(username):
        errors.append('Username: 3-64 chars, only letters, digits, _ @ . -')

    if len(password) < _MIN_PASS_LEN:
        errors.append(f'Password must be at least {_MIN_PASS_LEN} characters.')

    if not first:
        errors.append('First name is required.')

    # Перевіряємо БД лише якщо формат пройшов — і ТІЛЬКИ generic повідомлення
    if not errors:
        email_taken    = User.query.filter_by(email=email).first() is not None
        username_taken = User.query.filter_by(username=username).first() is not None
        if email_taken or username_taken:
            errors.append(
                'Registration failed. Please check your details or use different credentials.'
            )

    return errors


# ── Реєстрація / Вхід ────────────────────────────────────────────

def register_user(data: dict) -> tuple:
    errors = validate_registration(data)
    if errors:
        return None, errors

    is_first = User.query.count() == 0
    role     = Role.ADMIN if is_first else Role.VIEWER

    try:
        user = User(
            email          = data['email'].strip().lower(),
            username       = data['username'].strip().lstrip('@'),
            password_hash  = hash_password(data['password']),
            role           = role,
            first_name     = data.get('first_name', '').strip(),
            last_name      = data.get('last_name', '').strip(),
            is_verified    = is_first,
            notif_settings = json.dumps({
                'email_upload': True, 'email_storage': True,
                'email_security': True, 'email_digest': False,
                'email_updates': False, 'app_alerts': True, 'app_system': True,
            }),
        )
        db.session.add(user)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        print(f'[register_user] DB error: {exc}')
        return None, ['Registration failed due to a server error. Please try again.']

    _audit(user.id, 'user.register', 'user', str(user.id),
           {'role': role, 'email': user.email})
    return user, []


def login_user_service(email: str, password: str) -> tuple:
    """
    БЕЗПЕКА:
    - Однакове повідомлення при невірному email або паролі (no user enumeration)
    - Dummy bcrypt check якщо юзер не знайдений (захист від timing attack)
    """
    _GENERIC_ERROR = 'Invalid email or password.'
    email = email.strip().lower()
    user  = User.query.filter_by(email=email).first()

    # Виконуємо перевірку паролю навіть якщо юзера немає
    # щоб час відповіді не видавав відсутність акаунту
    _DUMMY_HASH = '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LeW.9mPa8xDI7c7dO'
    if user:
        password_ok = check_password(password, user.password_hash)
    else:
        check_password(password, _DUMMY_HASH)   # витрачаємо час
        password_ok = False

    if not user or not password_ok:
        return None, _GENERIC_ERROR

    if not user.is_active:
        return None, 'Account is not available. Please contact support.'

    try:
        user.last_login_at = datetime.utcnow()
        user.last_seen_at  = datetime.utcnow()
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        print(f'[login] timestamp update failed: {exc}')

    _audit(user.id, 'user.login', 'user', str(user.id), {'email': email})
    return user, ''


# ── Оновлення профілю ────────────────────────────────────────────

_PROFILE_FIELDS = {
    'first_name', 'last_name', 'phone', 'location', 'bio',
    'language', 'timezone', 'default_view', 'theme',
}


def update_user_profile(user: User, data: dict) -> dict:
    updated = {}
    for key, val in data.items():
        if key in _PROFILE_FIELDS:
            setattr(user, key, str(val).strip())
            updated[key] = getattr(user, key)
    if updated:
        try:
            db.session.commit()
            _audit(user.id, 'user.profile_update', 'user', str(user.id), updated)
        except Exception as exc:
            db.session.rollback()
            print(f'[update_profile] DB error: {exc}')
            return {}
    return updated


def update_user_password(user: User, old_pass: str, new_pass: str) -> list:
    errors = []
    if not check_password(old_pass, user.password_hash):
        errors.append('Current password is incorrect.')
    if len(new_pass) < _MIN_PASS_LEN:
        errors.append(f'New password must be at least {_MIN_PASS_LEN} characters.')
    if errors:
        return errors
    try:
        user.password_hash = hash_password(new_pass)
        db.session.commit()
        _audit(user.id, 'user.password_change', 'user', str(user.id), {})
    except Exception as exc:
        db.session.rollback()
        print(f'[update_password] DB error: {exc}')
        return ['Password update failed. Please try again.']
    return []


def update_notif_settings(user: User, settings: dict) -> dict:
    current = json.loads(user.notif_settings or '{}')
    allowed = {
        'email_upload', 'email_storage', 'email_security',
        'email_digest', 'email_updates', 'app_alerts', 'app_system',
    }
    updated = {k: v for k, v in settings.items() if k in allowed and isinstance(v, bool)}
    if updated:
        current.update(updated)
        try:
            user.notif_settings = json.dumps(current)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            print(f'[update_notif] DB error: {exc}')
    return updated


# ── Утиліти ─────────────────────────────────────────────────────

def _audit(actor_id, action, target_type, target_id, detail):
    try:
        ip = request.remote_addr
    except RuntimeError:
        ip = None
    try:
        entry = AuditLog(
            actor_id=actor_id, action=action,
            target_type=target_type, target_id=target_id,
            detail=json.dumps(detail, ensure_ascii=False),
            ip_address=ip,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        print(f'[audit] write failed: {exc}')


def touch_last_seen(user: User) -> None:
    try:
        user.last_seen_at = datetime.utcnow()
        db.session.commit()
    except Exception:
        db.session.rollback()