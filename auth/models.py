"""
auth/models.py
──────────────
SQLAlchemy-моделі для системи авторизації та файлового сховища CYBER DATA NEXUS.

Таблиці:
  users           — облікові записи користувачів
  files           — метадані файлів (замість JSON, готово для R2/S3)
  file_tags       — теги файлів (окрема таблиця замість JSON-масиву)
  storage_objects — об'єкти хмарного сховища (R2/S3), декоплінг від files
  share_links     — тимчасові посилання для шерингу файлів
  file_ownership  — (legacy) зв'язок file_id ↔ owner для міграції з JSON
  role_requests   — запити користувачів на підвищення ролі
  audit_log       — журнал всіх дій (хто, що, коли, з якої IP)
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


# ═══════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════

class Role(str, PyEnum):
    VIEWER = 'viewer'
    EDITOR = 'editor'
    ADMIN  = 'admin'


class FileStatus(str, PyEnum):
    ACTIVE    = 'active'
    DELETED   = 'deleted'
    ARCHIVED  = 'archived'
    UPLOADING = 'uploading'


class StorageProvider(str, PyEnum):
    LOCAL = 'local'
    R2    = 'r2'
    S3    = 's3'
    GCS   = 'gcs'


class RoleRequestStatus(str, PyEnum):
    PENDING  = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'


# ═══════════════════════════════════════════════════════════════
# ROLE PERMISSIONS MATRIX
# ═══════════════════════════════════════════════════════════════

ROLE_LEVEL: dict[str, int] = {
    Role.VIEWER: 1,
    Role.EDITOR: 2,
    Role.ADMIN:  3,
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    Role.VIEWER: {
        'files:read',
        # 'files:download',  — viewer не може скачувати
        'files:preview',
        'categories:read',
        'subcategories:read',
        # 'analytics:read',  — viewer не бачить аналітику
        'profile:read',
        'profile:edit',
    },
    Role.EDITOR: {
        'files:read',
        'files:download',
        'files:preview',
        'files:upload',
        'files:delete',
        'files:tag_add',
        'files:tag_remove',
        'files:move',
        'categories:read',
        'categories:create',
        'categories:delete',
        'subcategories:create',
        'subcategories:delete',
        'analytics:read',
        'profile:read',
        'profile:edit',
    },
    Role.ADMIN: {
        'files:read',
        'files:download',
        'files:preview',
        'files:upload',
        'files:delete',
        'files:tag_add',
        'files:tag_remove',
        'files:move',
        'categories:read',
        'categories:create',
        'categories:delete',
        'subcategories:create',
        'subcategories:delete',
        'analytics:read',
        'profile:read',
        'profile:edit',
        'users:read',
        'users:create',
        'users:edit_role',
        'users:delete',
        'users:invite',
        'audit:read',
        'storage:manage',
        'share:create',
    },
}


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


# ═══════════════════════════════════════════════════════════════
# USER MODEL
# ═══════════════════════════════════════════════════════════════

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username      = db.Column(db.String(64),  unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role          = db.Column(db.String(16),  nullable=False, default=Role.VIEWER)

    first_name    = db.Column(db.String(64),  nullable=False, default='')
    last_name     = db.Column(db.String(64),  nullable=False, default='')
    phone         = db.Column(db.String(32),  nullable=False, default='')
    location      = db.Column(db.String(128), nullable=False, default='')
    bio           = db.Column(db.Text,        nullable=False, default='')
    avatar_url    = db.Column(db.String(512), nullable=True)

    language      = db.Column(db.String(32),  nullable=False, default='Ukrainian / English')
    timezone      = db.Column(db.String(64),  nullable=False, default='UTC+3 (Kyiv)')

    notif_settings = db.Column(db.Text, nullable=False, default='{}')

    is_active     = db.Column(db.Boolean, nullable=False, default=True)
    is_verified   = db.Column(db.Boolean, nullable=False, default=False)

    created_at    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_seen_at  = db.Column(db.DateTime, nullable=True)

    files          = db.relationship('File',         back_populates='owner',
                                     cascade='all, delete-orphan', lazy='dynamic')
    owned_files    = db.relationship('FileOwnership', back_populates='owner',
                                     cascade='all, delete-orphan', lazy='dynamic')
    audit_entries  = db.relationship('AuditLog',     back_populates='actor',
                                     cascade='all, delete-orphan', lazy='dynamic')
    role_requests  = db.relationship('RoleRequest',  back_populates='requester',
                                     cascade='all, delete-orphan', lazy='dynamic',
                                     foreign_keys='RoleRequest.user_id')
    share_links    = db.relationship('ShareLink',    back_populates='created_by_user',
                                     cascade='all, delete-orphan', lazy='dynamic')

    def has_permission(self, permission: str) -> bool:
        return has_permission(self.role, permission)

    def can(self, permission: str) -> bool:
        return self.has_permission(permission)

    @property
    def display_name(self) -> str:
        full = f'{self.first_name} {self.last_name}'.strip()
        return full if full else self.username

    @property
    def role_level(self) -> int:
        return ROLE_LEVEL.get(self.role, 0)

    def to_dict(self, include_sensitive: bool = False) -> dict:
        import json
        data = {
            'id':            self.id,
            'email':         self.email,
            'username':      self.username,
            'role':          self.role,
            'first_name':    self.first_name,
            'last_name':     self.last_name,
            'display_name':  self.display_name,
            'phone':         self.phone,
            'location':      self.location,
            'bio':           self.bio,
            'avatar_url':    self.avatar_url,
            'language':      self.language,
            'timezone':      self.timezone,
            'is_active':     self.is_active,
            'is_verified':   self.is_verified,
            'created_at':    self.created_at.isoformat() if self.created_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
            'permissions':   list(ROLE_PERMISSIONS.get(self.role, set())),
            'notif_settings': json.loads(self.notif_settings or '{}'),
        }
        if include_sensitive:
            data['last_seen_at'] = self.last_seen_at.isoformat() if self.last_seen_at else None
        return data

    def __repr__(self) -> str:
        return f'<User {self.username!r} role={self.role!r}>'


# ═══════════════════════════════════════════════════════════════
# FILE MODEL
# ═══════════════════════════════════════════════════════════════

class File(db.Model):
    """
    Метадані файлу. UUID як PK — безпечний для зовнішніх посилань.
    storage_key — ключ об'єкта в R2/S3 (наприклад uploads/2024/01/uuid.pdf).
    """
    __tablename__ = 'files'

    id                = db.Column(db.String(36), primary_key=True,
                                  default=lambda: str(uuid.uuid4()))
    user_id           = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'),
                                  nullable=True, index=True)

    filename          = db.Column(db.String(512), nullable=False)
    original_filename = db.Column(db.String(512), nullable=False)

    size              = db.Column(db.BigInteger,  nullable=False, default=0)
    mimetype          = db.Column(db.String(255), nullable=True)

    category          = db.Column(db.String(64),  nullable=False, default='other')
    subcategory       = db.Column(db.String(64),  nullable=False, default='general')
    confidence        = db.Column(db.Float,       nullable=False, default=0.0)
    manual_category   = db.Column(db.Boolean,     nullable=False, default=False)

    storage_key       = db.Column(db.String(1024), nullable=True)
    storage_provider  = db.Column(db.String(16),   nullable=False,
                                  default=StorageProvider.LOCAL)
    storage_bucket    = db.Column(db.String(256),  nullable=True)

    status            = db.Column(db.String(16),  nullable=False,
                                  default=FileStatus.ACTIVE, index=True)
    deleted_at        = db.Column(db.DateTime,    nullable=True)

    checksum_md5      = db.Column(db.String(32),  nullable=True, index=True)
    checksum_sha256   = db.Column(db.String(64),  nullable=True)

    upload_date       = db.Column(db.DateTime, nullable=False,
                                  default=datetime.utcnow, index=True)
    updated_at        = db.Column(db.DateTime, nullable=False,
                                  default=datetime.utcnow, onupdate=datetime.utcnow)

    owner             = db.relationship('User',          back_populates='files')
    tags              = db.relationship('FileTag',        back_populates='file',
                                        cascade='all, delete-orphan', lazy='dynamic')
    storage_object    = db.relationship('StorageObject',  back_populates='file',
                                        uselist=False, cascade='all, delete-orphan')
    share_links       = db.relationship('ShareLink',      back_populates='file',
                                        cascade='all, delete-orphan', lazy='dynamic')

    __table_args__ = (
        db.Index('ix_files_category_status', 'category', 'status'),
        db.Index('ix_files_user_status',     'user_id',  'status'),
    )

    @property
    def tag_list(self) -> list[str]:
        return [t.tag for t in self.tags]

    @property
    def is_deleted(self) -> bool:
        return self.status == FileStatus.DELETED

    def soft_delete(self) -> None:
        self.status     = FileStatus.DELETED
        self.deleted_at = datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            'file_id':           self.id,
            'filename':          self.filename,
            'original_filename': self.original_filename,
            'size':              self.size,
            'mimetype':          self.mimetype,
            'category':          self.category,
            'subcategory':       self.subcategory,
            'confidence':        self.confidence,
            'manual_category':   self.manual_category,
            'storage_key':       self.storage_key,
            'storage_provider':  self.storage_provider,
            'status':            self.status,
            'tags':              self.tag_list,
            'upload_date':       self.upload_date.isoformat(),
            'updated_at':        self.updated_at.isoformat(),
            'owner_id':          self.user_id,
        }

    def __repr__(self) -> str:
        return f'<File {self.filename!r} status={self.status!r}>'


# ═══════════════════════════════════════════════════════════════
# FILE TAGS
# ═══════════════════════════════════════════════════════════════

class FileTag(db.Model):
    """
    Теги файлу в окремій таблиці.
    Переваги: індексований пошук по тегу, аналітика без парсингу JSON,
    зберігання автора тегу.
    """
    __tablename__ = 'file_tags'

    id         = db.Column(db.Integer, primary_key=True)
    file_id    = db.Column(db.String(36), db.ForeignKey('files.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    tag        = db.Column(db.String(128), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'),
                           nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    file    = db.relationship('File', back_populates='tags')
    creator = db.relationship('User', foreign_keys=[created_by])

    __table_args__ = (
        # ix_file_tags_tag вже створюється автоматично через index=True на колонці tag
        db.UniqueConstraint('file_id', 'tag', name='uq_file_tag'),
    )

    def __repr__(self) -> str:
        return f'<FileTag file={self.file_id!r} tag={self.tag!r}>'


# ═══════════════════════════════════════════════════════════════
# STORAGE OBJECTS
# ═══════════════════════════════════════════════════════════════

class StorageObject(db.Model):
    """
    Об'єкт у хмарному сховищі (R2, S3, GCS або локал).

    Декоплінг від File дозволяє:
      — замінити провайдера без зміни File-моделі
      — відстежувати статус multipart upload
      — зберігати ETag, версію від провайдера
      — мати копії в кількох провайдерах під час міграції
    """
    __tablename__ = 'storage_objects'

    id               = db.Column(db.Integer, primary_key=True)
    file_id          = db.Column(db.String(36), db.ForeignKey('files.id', ondelete='CASCADE'),
                                 nullable=False, unique=True, index=True)

    provider         = db.Column(db.String(16),   nullable=False, default=StorageProvider.LOCAL)
    bucket           = db.Column(db.String(256),  nullable=True)
    key              = db.Column(db.String(1024),  nullable=False)

    etag             = db.Column(db.String(128),  nullable=True)
    version_id       = db.Column(db.String(128),  nullable=True)
    content_type     = db.Column(db.String(255),  nullable=True)
    content_encoding = db.Column(db.String(64),   nullable=True)

    upload_id        = db.Column(db.String(256),  nullable=True)   # multipart upload ID
    is_uploaded      = db.Column(db.Boolean,      nullable=False, default=False)
    uploaded_at      = db.Column(db.DateTime,     nullable=True)

    is_public        = db.Column(db.Boolean, nullable=False, default=False)

    file = db.relationship('File', back_populates='storage_object')

    def __repr__(self) -> str:
        return f'<StorageObject provider={self.provider!r} key={self.key!r}>'


# ═══════════════════════════════════════════════════════════════
# SHARE LINKS
# ═══════════════════════════════════════════════════════════════

class ShareLink(db.Model):
    """
    Тимчасове посилання для шерингу файлу без надання доступу до системи.
    Маршрут: GET /share/<token>
    Підтримує: термін дії, ліміт переглядів, password-захист, дозвіл на скачування.
    """
    __tablename__ = 'share_links'

    id             = db.Column(db.Integer, primary_key=True)
    token          = db.Column(db.String(64), unique=True, nullable=False, index=True)
    file_id        = db.Column(db.String(36), db.ForeignKey('files.id', ondelete='CASCADE'),
                               nullable=False, index=True)
    created_by     = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'),
                               nullable=True)

    expires_at     = db.Column(db.DateTime, nullable=True)     # NULL = безтерміново
    max_views      = db.Column(db.Integer,  nullable=True)     # NULL = необмежено
    view_count     = db.Column(db.Integer,  nullable=False, default=0)
    password_hash  = db.Column(db.String(255), nullable=True)  # NULL = без пароля

    allow_download = db.Column(db.Boolean, nullable=False, default=False)

    is_active      = db.Column(db.Boolean, nullable=False, default=True)
    created_at     = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_accessed  = db.Column(db.DateTime, nullable=True)

    file             = db.relationship('File', back_populates='share_links')
    created_by_user  = db.relationship('User', back_populates='share_links',
                                       foreign_keys=[created_by])

    @property
    def is_expired(self) -> bool:
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return True
        if self.max_views and self.view_count >= self.max_views:
            return True
        return False

    def __repr__(self) -> str:
        return f'<ShareLink token={self.token!r} file={self.file_id!r}>'


# ═══════════════════════════════════════════════════════════════
# ROLE REQUESTS
# ═══════════════════════════════════════════════════════════════

class RoleRequest(db.Model):
    """
    Запит на підвищення ролі.
    Переносить in-memory _role_requests list → постійне сховище в БД.
    Зберігає повну історію (не лише pending), коментар адміна при відмові.
    """
    __tablename__ = 'role_requests'

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
                               nullable=False, index=True)
    current_role   = db.Column(db.String(16), nullable=False)
    requested_role = db.Column(db.String(16), nullable=False)
    message        = db.Column(db.Text, nullable=True)
    status         = db.Column(db.String(16), nullable=False,
                               default=RoleRequestStatus.PENDING, index=True)

    reviewed_by    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'),
                               nullable=True)
    reviewed_at    = db.Column(db.DateTime, nullable=True)
    review_note    = db.Column(db.Text,     nullable=True)  # коментар адміна при відмові

    created_at     = db.Column(db.DateTime, nullable=False,
                               default=datetime.utcnow, index=True)

    requester = db.relationship('User', back_populates='role_requests',
                                foreign_keys=[user_id])
    reviewer  = db.relationship('User', foreign_keys=[reviewed_by])

    def to_dict(self) -> dict:
        return {
            'id':             self.id,
            'user_id':        self.user_id,
            'username':       self.requester.username      if self.requester else None,
            'display_name':   self.requester.display_name  if self.requester else None,
            'email':          self.requester.email         if self.requester else None,
            'current_role':   self.current_role,
            'requested_role': self.requested_role,
            'message':        self.message,
            'status':         self.status,
            'review_note':    self.review_note,
            'reviewed_at':    self.reviewed_at.isoformat() if self.reviewed_at else None,
            'created_at':     self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return (f'<RoleRequest user={self.user_id} '
                f'{self.current_role}→{self.requested_role} [{self.status}]>')


# ═══════════════════════════════════════════════════════════════
# FILE OWNERSHIP  (legacy — для міграції з JSON)
# ═══════════════════════════════════════════════════════════════

class FileOwnership(db.Model):
    """
    (Legacy) Зв'язок між старим file_id (MD5-хеш з JSON) і власником.
    Використовується під час міграції JSON → files table.
    Після повної міграції таблицю можна видалити.
    """
    __tablename__ = 'file_ownership'

    id          = db.Column(db.Integer, primary_key=True)
    file_id     = db.Column(db.String(12),  nullable=False, unique=True, index=True)
    owner_id    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
                            nullable=False, index=True)
    migrated    = db.Column(db.Boolean,  nullable=False, default=False)  # чи перенесено в files
    migrated_at = db.Column(db.DateTime, nullable=True)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    owner = db.relationship('User', back_populates='owned_files')

    def __repr__(self) -> str:
        return (f'<FileOwnership file_id={self.file_id!r} '
                f'owner={self.owner_id} migrated={self.migrated}>')


# ═══════════════════════════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════════════════════════

class AuditLog(db.Model):
    """
    Журнал всіх значущих дій у системі.

    Дії (action):
      user.login, user.register, user.logout, user.password_change
      file.upload, file.download, file.delete, file.move
      file.tag_add, file.tag_remove
      admin.role_change, admin.user_delete, admin.user_deactivate
      storage.migrate, share.create, share.access
    """
    __tablename__ = 'audit_log'

    id          = db.Column(db.Integer, primary_key=True)
    actor_id    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'),
                            nullable=True, index=True)
    action      = db.Column(db.String(64),  nullable=False, index=True)
    target_type = db.Column(db.String(32),  nullable=True)
    target_id   = db.Column(db.String(64),  nullable=True)
    detail      = db.Column(db.Text,        nullable=True)   # JSON
    ip_address  = db.Column(db.String(45),  nullable=True)
    user_agent  = db.Column(db.String(512), nullable=True)   # для security-аудиту
    created_at  = db.Column(db.DateTime, nullable=False,
                            default=datetime.utcnow, index=True)

    actor = db.relationship('User', back_populates='audit_entries')

    __table_args__ = (
        db.Index('ix_audit_actor_action', 'actor_id', 'action'),
        db.Index('ix_audit_created_at',   'created_at'),
    )

    def to_dict(self) -> dict:
        import json as _json
        return {
            'id':          self.id,
            'actor_id':    self.actor_id,
            'actor_name':  self.actor.display_name if self.actor else 'system',
            'actor_role':  self.actor.role if self.actor else None,
            'action':      self.action,
            'target_type': self.target_type,
            'target_id':   self.target_id,
            'detail':      _json.loads(self.detail) if self.detail else None,
            'ip_address':  self.ip_address,
            'created_at':  self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f'<AuditLog action={self.action!r} actor_id={self.actor_id}>'