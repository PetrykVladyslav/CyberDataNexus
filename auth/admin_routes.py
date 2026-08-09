"""
auth/admin_routes.py
────────────────────
Blueprint /api/admin — управління користувачами (тільки admin).

Маршрути:
  GET    /api/admin/users              список усіх користувачів
  GET    /api/admin/users/<id>         деталі користувача
  PATCH  /api/admin/users/<id>/role    змінити роль
  PATCH  /api/admin/users/<id>/status  активувати / деактивувати
  DELETE /api/admin/users/<id>         видалити користувача
  GET    /api/admin/audit              журнал аудиту
  GET    /api/admin/stats              зведена статистика по ролях
"""

import json
from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_login import current_user

from .models import db, User, AuditLog, Role, ROLE_LEVEL
from .decorators import admin_required, get_current_user
from .service import hash_password, _audit, validate_registration

admin_bp = Blueprint('admin_bp', __name__, url_prefix='/api/admin')


# ─── Список користувачів ───────────────────────────────────────

@admin_bp.route('/users', methods=['GET'])
@admin_required
def list_users():
    """
    GET /api/admin/users?page=1&per_page=20&role=&search=
    Повертає пагінований список користувачів.
    """
    page = int(request.args.get('page', 1))
    per_page = min(int(request.args.get('per_page', 20)), 100)
    role_f = request.args.get('role', '').strip()
    search = request.args.get('search', '').strip().lower()

    q = User.query
    if role_f and role_f in [r.value for r in Role]:
        q = q.filter_by(role=role_f)
    if search:
        q = q.filter(
            db.or_(
                User.email.ilike(f'%{search}%'),
                User.username.ilike(f'%{search}%'),
                User.first_name.ilike(f'%{search}%'),
                User.last_name.ilike(f'%{search}%'),
            )
        )
    q = q.order_by(User.created_at.desc())

    paginated = q.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'users': [u.to_dict(include_sensitive=True) for u in paginated.items],
        'total': paginated.total,
        'page': page,
        'pages': paginated.pages,
        'per_page': per_page,
    })


# ─── Деталі користувача ────────────────────────────────────────

@admin_bp.route('/users/<int:user_id>', methods=['GET'])
@admin_required
def get_user(user_id: int):
    """GET /api/admin/users/<id>"""
    user = User.query.get_or_404(user_id)
    return jsonify({
        'user': user.to_dict(include_sensitive=True),
        'audit_recent': [
            e.to_dict() for e in
            AuditLog.query.filter_by(actor_id=user_id)
            .order_by(AuditLog.created_at.desc())
            .limit(10).all()
        ],
    })


# ─── Зміна ролі ────────────────────────────────────────────────

@admin_bp.route('/users/<int:user_id>/role', methods=['PATCH'])
@admin_required
def change_role(user_id: int):
    """
    PATCH /api/admin/users/<id>/role
    Body: { role: 'viewer' | 'editor' | 'admin' }

    Admin не може змінити свою власну роль (захист від само-понижання).
    """
    actor = get_current_user()
    if actor.id == user_id:
        return jsonify({'error': 'Cannot change your own role.'}), 400

    target = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}
    new_role = data.get('role', '').strip()

    if new_role not in [r.value for r in Role]:
        return jsonify({'error': f'Invalid role. Allowed: {[r.value for r in Role]}'}), 422

    old_role = target.role
    target.role = new_role
    db.session.commit()

    _audit(actor.id, 'admin.role_change', 'user', str(user_id),
           {'old_role': old_role, 'new_role': new_role,
            'target_email': target.email})

    return jsonify({
        'success': True,
        'user_id': user_id,
        'old_role': old_role,
        'new_role': new_role,
        'user': target.to_dict(),
    })


# ─── Активація / деактивація ────────────────────────────────────

@admin_bp.route('/users/<int:user_id>/status', methods=['PATCH'])
@admin_required
def change_status(user_id: int):
    """
    PATCH /api/admin/users/<id>/status
    Body: { is_active: bool }
    """
    actor = get_current_user()
    if actor.id == user_id:
        return jsonify({'error': 'Cannot deactivate yourself.'}), 400

    target = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}
    is_active = data.get('is_active')

    if not isinstance(is_active, bool):
        return jsonify({'error': 'is_active must be a boolean.'}), 422

    old_status = target.is_active
    target.is_active = is_active
    db.session.commit()

    action = 'admin.user_activate' if is_active else 'admin.user_deactivate'
    _audit(actor.id, action, 'user', str(user_id),
           {'email': target.email, 'old_status': old_status})

    return jsonify({
        'success': True,
        'user_id': user_id,
        'is_active': is_active,
        'user': target.to_dict(),
    })


# ─── Видалення ─────────────────────────────────────────────────

@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id: int):
    """
    DELETE /api/admin/users/<id>
    Admin не може видалити себе.
    """
    actor = get_current_user()
    if actor.id == user_id:
        return jsonify({'error': 'Cannot delete yourself.'}), 400

    target = User.query.get_or_404(user_id)
    email = target.email
    db.session.delete(target)
    db.session.commit()

    _audit(actor.id, 'admin.user_delete', 'user', str(user_id),
           {'email': email})

    return jsonify({'success': True, 'deleted_user_id': user_id})


# ─── Журнал аудиту ─────────────────────────────────────────────

@admin_bp.route('/audit', methods=['GET'])
@admin_required
def get_audit_log():
    """
    GET /api/admin/audit?page=1&per_page=50&action=&actor_id=
    """
    page = int(request.args.get('page', 1))
    per_page = min(int(request.args.get('per_page', 50)), 200)
    action_f = request.args.get('action', '').strip()
    actor_id = request.args.get('actor_id', '').strip()

    q = AuditLog.query
    if action_f:
        q = q.filter(AuditLog.action.ilike(f'%{action_f}%'))
    if actor_id.isdigit():
        q = q.filter_by(actor_id=int(actor_id))
    q = q.order_by(AuditLog.created_at.desc())

    paginated = q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'entries': [e.to_dict() for e in paginated.items],
        'total': paginated.total,
        'page': page,
        'pages': paginated.pages,
    })


# ─── Статистика ────────────────────────────────────────────────

@admin_bp.route('/stats', methods=['GET'])
@admin_required
def admin_stats():
    """
    GET /api/admin/stats
    Зведена статистика по ролях, активності, реєстраціях.
    """
    total = User.query.count()
    by_role = {r.value: User.query.filter_by(role=r.value).count() for r in Role}
    active = User.query.filter_by(is_active=True).count()
    verified = User.query.filter_by(is_verified=True).count()
    last_7d = User.query.filter(
        User.created_at >= datetime.utcnow().replace(
            hour=0, minute=0, second=0
        )
    ).count()
    audit_total = AuditLog.query.count()

    return jsonify({
        'total_users': total,
        'active_users': active,
        'verified_users': verified,
        'new_last_7d': last_7d,
        'by_role': by_role,
        'audit_total': audit_total,
    })