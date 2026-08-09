"""
CYBERPUNK DATA NEXUS - AI-POWERED FILE MANAGEMENT SYSTEM
Flask Backend — Веб-версія

Вся конфігурація (категорії, теги, транслітерація, Flask-параметри)
читається з config.yaml через config_loader. Тут немає хардкоду.

Сховище файлів:
  - Backblaze B2 (S3-сумісний API) для бінарних файлів
  - Supabase PostgreSQL для метаданих (через auth/models.py → таблиця files + file_tags)
  - JSON-файл більше НЕ використовується для збереження файлів

Авторизація (auth/):
  - PostgreSQL + SQLAlchemy  (auth/models.py)
  - bcrypt паролі + JWT      (auth/service.py)
  - Flask-Login сесії        (auth/__init__.py)
  - Декоратори прав          (auth/decorators.py)
  - Маршрути /api/auth/*     (auth/routes.py)
  - Управління /api/admin/*  (auth/admin_routes.py)

Змінні середовища (.env):
  SECRET_KEY, DATABASE_URL         — обов'язкові
  STORAGE_PROVIDER=b2              — провайдер сховища
  STORAGE_ACCESS_KEY_ID            — B2 keyID
  STORAGE_SECRET_ACCESS_KEY        — B2 applicationKey
  STORAGE_BUCKET                   — назва бакету
  B2_ENDPOINT                      — регіональний endpoint (напр. https://s3.us-east-005.backblazeb2.com)
  STORAGE_PUBLIC_URL               — публічний домен bucket (опційно)
"""

import hashlib
import io
import json
import os
import re
import unicodedata
from datetime import datetime
from typing import List, Dict, Optional
import secrets

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config as BotoConfig

from flask import Flask, render_template, request, jsonify, send_file as flask_send_file, Response

from ai.inference import SemanticFileClassifier, resolve_subcategory, resolve_all_subcategories
from config_loader import (
    get_app_cfg,
    get_base_categories,
    get_base_category_ids,
    get_tag_to_category,
    get_tag_synonyms,
    get_transliteration_map,
    get_subcategory_rules,
    get_system_subcategory_names,
    get_extension_to_base_category,
)

# Авторизація
from auth import init_auth
from auth.decorators import (
    login_required,
    permission_required,
    admin_required,
    get_current_user,
)

from dotenv import load_dotenv

# Завантажуємо змінні з .env
load_dotenv()

# Завантажуємо конфіг один раз
_app_cfg = get_app_cfg()
_BASE_CATEGORY_IDS: set[str] = get_base_category_ids()
_TAG_TO_CATEGORY: dict[str, str] = get_tag_to_category()
_TAG_SYNONYMS: dict[str, str] = get_tag_synonyms()
_TRANSLIT_MAP: dict[str, str] = get_transliteration_map()
_SUBCATEGORY_RULES: dict = get_subcategory_rules()
_SYSTEM_SUBCATEGORY_NAMES: set[str] = get_system_subcategory_names()
# Маппінг розширення → базова категорія (найвищий пріоритет, перекриває AI)
_EXT_TO_BASE_CAT: dict[str, str] = get_extension_to_base_category()

# Flask app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = _app_cfg['max_upload_mb'] * 1024 * 1024

# Конфіг БД та безпеки (Supabase PostgreSQL)
import psycopg2

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise ValueError("SECRET_KEY не встановлено! Додайте його в .env файл")

database_url = os.environ.get('DATABASE_URL')
if not database_url:
    raise ValueError("DATABASE_URL не встановлено! Додайте його в .env файл")

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping":  True,
    "pool_recycle":   300,
    "pool_size":      5,
    "max_overflow":   10,
}

print("🚀 Connected to Supabase PostgreSQL")

# S3-сумісне хмарне сховище
# Підтримує: Cloudflare R2, Backblaze B2, AWS S3, MinIO, тощо.
# Провайдер обирається через змінну STORAGE_PROVIDER у .env.
#
# Cloudflare R2 (.env):
#   STORAGE_PROVIDER=r2
#   STORAGE_ACCESS_KEY_ID=<R2 Access Key ID>
#   STORAGE_SECRET_ACCESS_KEY=<R2 Secret Access Key>
#   STORAGE_BUCKET=<bucket name>
#   R2_ACCOUNT_ID=<Cloudflare Account ID>          ← тільки для R2
#   STORAGE_PUBLIC_URL=https://pub.yourdomain.com  ← опційно
#
# Backblaze B2 (.env):
#   STORAGE_PROVIDER=b2
#   STORAGE_ACCESS_KEY_ID=<B2 keyID>
#   STORAGE_SECRET_ACCESS_KEY=<B2 applicationKey>
#   STORAGE_BUCKET=<bucket name>
#   B2_ENDPOINT=https://s3.us-west-004.backblazeb2.com  ← регіональний endpoint
#   STORAGE_PUBLIC_URL=https://f005.backblazeb2.com/file/<bucket>  ← опційно
#
# AWS S3 (.env):
#   STORAGE_PROVIDER=s3
#   STORAGE_ACCESS_KEY_ID=<AWS Access Key>
#   STORAGE_SECRET_ACCESS_KEY=<AWS Secret>
#   STORAGE_BUCKET=<bucket name>
#   S3_REGION=eu-central-1

_STORAGE_PROVIDER     = os.environ.get('STORAGE_PROVIDER', 'r2').lower()
_STORAGE_ACCESS_KEY   = os.environ.get('STORAGE_ACCESS_KEY_ID', '')
_STORAGE_SECRET_KEY   = os.environ.get('STORAGE_SECRET_ACCESS_KEY', '')
_STORAGE_BUCKET       = os.environ.get('STORAGE_BUCKET', 'nexus-files')
_STORAGE_PUBLIC_URL   = os.environ.get('STORAGE_PUBLIC_URL', '').rstrip('/')

# Визначаємо endpoint залежно від провайдера
def _resolve_storage_endpoint() -> tuple[str, str]:
    """Повертає (endpoint_url, region_name) для обраного провайдера."""
    if _STORAGE_PROVIDER == 'r2':
        account_id = os.environ.get('R2_ACCOUNT_ID', '')
        if not account_id:
            raise ValueError("R2_ACCOUNT_ID не встановлено в .env")
        return f'https://{account_id}.r2.cloudflarestorage.com', 'auto'

    if _STORAGE_PROVIDER == 'b2':
        endpoint = os.environ.get('B2_ENDPOINT', '')
        if not endpoint:
            raise ValueError(
                "B2_ENDPOINT не встановлено в .env\n"
                "Приклад: B2_ENDPOINT=https://s3.us-east-005.backblazeb2.com"
            )
        # Витягуємо регіон з endpoint URL.
        # https://s3.us-east-005.backblazeb2.com  →  us-east-005
        import re as _re
        _b2_region_match = _re.search(r's3\.([^.]+)\.',  endpoint)
        b2_region = _b2_region_match.group(1) if _b2_region_match else 'us-east-005'
        return endpoint, b2_region

    if _STORAGE_PROVIDER == 's3':
        region = os.environ.get('S3_REGION', 'eu-central-1')
        return f'https://s3.{region}.amazonaws.com', region

    # Кастомний endpoint (MinIO, Wasabi, тощо)
    custom = os.environ.get('STORAGE_ENDPOINT', '')
    if not custom:
        raise ValueError(f"Невідомий STORAGE_PROVIDER='{_STORAGE_PROVIDER}'. "
                         "Встановіть STORAGE_ENDPOINT для кастомного провайдера.")
    return custom, os.environ.get('S3_REGION', 'auto')


if not all([_STORAGE_ACCESS_KEY, _STORAGE_SECRET_KEY]):
    raise ValueError(
        "Credentials хмарного сховища не встановлені!\n"
        "Додайте в .env: STORAGE_ACCESS_KEY_ID, STORAGE_SECRET_ACCESS_KEY, STORAGE_BUCKET"
    )

_STORAGE_ENDPOINT, _STORAGE_REGION = _resolve_storage_endpoint()

# Ініціалізуємо boto3 S3-клієнт (S3-сумісний для всіх провайдерів)
_s3_client = boto3.client(
    's3',
    endpoint_url          = _STORAGE_ENDPOINT,
    aws_access_key_id     = _STORAGE_ACCESS_KEY,
    aws_secret_access_key = _STORAGE_SECRET_KEY,
    region_name           = _STORAGE_REGION,
    config                = BotoConfig(
        signature_version = 's3v4',
        retries           = {'max_attempts': 3, 'mode': 'adaptive'},
        connect_timeout   = 10,
        read_timeout      = 30,
    ),
)

print(f"☁️  Storage: {_STORAGE_PROVIDER.upper()} → bucket: {_STORAGE_BUCKET} ({_STORAGE_ENDPOINT})")

# ── Тимчасова папка для буферування під час upload/preview ─────
_TEMP_DIR = os.environ.get('TEMP_DIR', '/tmp/nexus_tmp')
os.makedirs(_TEMP_DIR, exist_ok=True)

# Ініціалізація авторизації
init_auth(app)

# Створення таблиць якщо їх немає
with app.app_context():
    try:
        from auth.models import db as _auth_db
        from sqlalchemy import inspect as _sa_inspect
        from sqlalchemy.exc import OperationalError as _OpError

        _inspector = _sa_inspect(_auth_db.engine)
        _existing_tables = set(_inspector.get_table_names())

        for _table in _auth_db.metadata.sorted_tables:
            if _table.name not in _existing_tables:
                try:
                    _table.create(_auth_db.engine, checkfirst=True)
                except _OpError as _te:
                    print(f'[db] table create warning ({_table.name}): {_te}')

        print("✅ Database schema checked")

    except Exception as _e:
        print(f'[db] init warning: {_e}')

# Утиліти для імен файлів

def transliterate_cyrillic(text: str) -> str:
    """Транслітерує кириличний текст в латиницю (таблиця з конфігу)."""
    return ''.join(_TRANSLIT_MAP.get(ch, ch) for ch in text)


def prepare_filename_for_ai(filename: str) -> str:
    """
    Підготовлює ім'я файлу для AI класифікації:
    1. Транслітерує кирилицю (таблиця з config.yaml)
    2. Нормалізує unicode
    3. Залишає тільки alphanum та основні символи
    """
    transliterated = transliterate_cyrillic(filename)
    normalized = unicodedata.normalize('NFKD', transliterated)
    normalized = normalized.encode('ascii', 'ignore').decode('ascii')
    cleaned = re.sub(r'[^\w\s.-]', ' ', normalized)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def safe_filename(filename: str) -> str:
    """Створює безпечну назву файлу зі збереженням кирилиці."""
    name, ext = os.path.splitext(filename)
    safe_name = re.sub(r'[^\w\s\-\u0400-\u04FF]', '_', name)
    safe_name = re.sub(r'[\s_]+', '_', safe_name).strip('_')
    if not safe_name:
        safe_name = f"file_{int(datetime.now().timestamp())}"
    return safe_name + ext.lower()


# Утиліти для тегів і категорій

def normalize_tag(tag: str) -> str:
    """
    Нормалізує тег: нижній регістр, trim.
    Синоніми замінюються на канонічну форму (з config.yaml).
    Кирилиця зберігається якщо не є синонімом.
    """
    tag = tag.strip().lower()
    return _TAG_SYNONYMS.get(tag, tag)


def infer_categories_from_tags(tags: list[str]) -> set[str]:
    """
    Виводить множину категорій з тегів.
    Маппінг тег → категорія береться з config.yaml.
    """
    categories: set[str] = set()
    for tag in tags:
        t = tag.lower().strip()
        cat = _TAG_TO_CATEGORY.get(t)
        if cat:
            categories.add(cat)
    return categories


# R2Storage

class R2Storage:
    """
    Абстракція над Cloudflare R2 (S3-сумісний API).

    Методи:
      upload(file_obj, key, content_type)  → True/False
      download(key)                        → BytesIO | None
      delete(key)                         → True/False
      exists(key)                         → bool
      get_presigned_url(key, expires=3600) → str | None
      build_key(filename, file_id)         → str
    """

    def __init__(self, client, bucket: str, public_url: str = ''):
        self._s3    = client
        self._bucket = bucket
        self._pub   = public_url

    # ключ об'єкта

    @staticmethod
    def build_key(filename: str, file_id: str) -> str:
        """
        Будує ключ: uploads/YYYY/MM/<file_id>_<filename>
        Організація по роках/місяцях дозволяє ефективно listing і lifecycle.
        """
        now = datetime.utcnow()
        safe = re.sub(r'[^\w.\-]', '_', filename)
        return f"uploads/{now.year}/{now.month:02d}/{file_id}_{safe}"

    # upload

    def upload(
        self,
        file_obj,
        key: str,
        content_type: str = 'application/octet-stream',
        extra_meta: dict = None,
    ) -> bool:
        """
        Завантажує file_obj (file-like або bytes) в R2.
        extra_meta: додаткові S3 Metadata (dict[str,str]).
        """
        try:
            extra = {'ContentType': content_type}
            if extra_meta:
                extra['Metadata'] = {str(k): str(v) for k, v in extra_meta.items()}

            if isinstance(file_obj, (bytes, bytearray)):
                self._s3.put_object(
                    Bucket=self._bucket, Key=key, Body=file_obj, **extra
                )
            else:
                # file-like object (Flask FileStorage або BytesIO)
                if hasattr(file_obj, 'seek'):
                    file_obj.seek(0)
                self._s3.upload_fileobj(file_obj, self._bucket, key, ExtraArgs=extra)
            return True
        except ClientError as e:
            print(f'[Storage] upload failed ({key}): {e}')
            return False

    # download

    def download(self, key: str) -> Optional[io.BytesIO]:
        """Завантажує об'єкт з R2 → BytesIO. None якщо не знайдено."""
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=key)
            buf  = io.BytesIO(resp['Body'].read())
            buf.seek(0)
            return buf
        except ClientError as e:
            if e.response['Error']['Code'] in ('NoSuchKey', '404'):
                return None
            print(f'[Storage] download failed ({key}): {e}')
            return None

    # delete

    def delete(self, key: str) -> bool:
        """Видаляє об'єкт з R2."""
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as e:
            print(f'[Storage] delete failed ({key}): {e}')
            return False

    # exists

    def exists(self, key: str) -> bool:
        """Перевіряє чи існує об'єкт без завантаження."""
        try:
            self._s3.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    # presigned URL (для прямого завантаження)

    def get_presigned_url(self, key: str, expires: int = 3600) -> Optional[str]:
        """
        Генерує підписаний URL для прямого завантаження з R2.
        Використовується коли R2_PUBLIC_URL не задано.
        expires: термін дії в секундах (default 1 год).
        """
        try:
            url = self._s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': self._bucket, 'Key': key},
                ExpiresIn=expires,
            )
            return url
        except ClientError as e:
            print(f'[Storage] presign failed ({key}): {e}')
            return None

    def get_public_url(self, key: str) -> Optional[str]:
        """Повертає публічний URL якщо R2_PUBLIC_URL задано, інакше presigned."""
        if self._pub:
            return f"{self._pub}/{key}"
        return self.get_presigned_url(key)

    # copy (для дедуплікації)

    def copy(self, src_key: str, dst_key: str) -> bool:
        """Копіює об'єкт всередині bucket без повторного завантаження."""
        try:
            self._s3.copy_object(
                Bucket=self._bucket,
                CopySource={'Bucket': self._bucket, 'Key': src_key},
                Key=dst_key,
            )
            return True
        except ClientError as e:
            print(f'[Storage] copy failed ({src_key} → {dst_key}): {e}')
            return False


# Глобальний екземпляр
storage = R2Storage(_s3_client, _STORAGE_BUCKET, _STORAGE_PUBLIC_URL)


# FileRecord

class FileRecord:
    """
    Метадані файлу + AI-класифікація.

    R2-версія: файл зберігається в Cloudflare R2 за ключем self.storage_key.
    Метадані (включно з storage_key) — в Supabase PostgreSQL через auth/models.py → File.
    В пам'яті (self.files) зберігаємо лише індекс для швидкого доступу.
    """

    def __init__(
        self,
        file_bytes: bytes,
        original_filename: str,
        ai_model: SemanticFileClassifier,
        storage_key: str = '',
        file_id: str = '',
        upload_date: datetime = None,
        mimetype: str = 'application/octet-stream',
    ):
        self.original_filename = original_filename
        self.filename  = safe_filename(original_filename)
        self.size      = len(file_bytes)
        self.upload_date = upload_date or datetime.utcnow()
        self.mimetype  = mimetype

        # Унікальний ID — UUID-стиль через hashlib якщо не переданий
        if file_id:
            self.file_id = file_id
        else:
            self.file_id = hashlib.sha256(
                f"{self.filename}{self.upload_date.isoformat()}{self.size}".encode()
            ).hexdigest()[:16]

        # Ключ в R2
        self.storage_key = storage_key or R2Storage.build_key(self.filename, self.file_id)

        self.categories: set[str] = set()
        self.category: str = "other"
        self.subcategory: str = "general"
        self.subcategories: list[str] = ["general"]
        self._manual_category: bool = False

        # AI inference — передаємо транслітероване ім'я
        ai_filename = prepare_filename_for_ai(self.filename)
        result = ai_model.classify(ai_filename)

        self.tags: list[str] = list(result["tags"])
        self.confidence: float = result["confidence"]

        # ── Визначення категорії (3 рівні пріоритету) ──────────
        _, ext = os.path.splitext(self.filename)
        ext_lower = ext.lstrip('.').lower()

        ext_category  = _EXT_TO_BASE_CAT.get(ext_lower)
        tag_categories = infer_categories_from_tags(self.tags)
        ai_primary    = result["categories"][0] if result["categories"] else None
        ai_category   = ai_primary if ai_primary in _BASE_CATEGORY_IDS else None

        self.categories = set()
        if ext_category:   self.categories.add(ext_category)
        if tag_categories: self.categories.update(tag_categories)
        if ai_category:    self.categories.add(ai_category)
        if not self.categories: self.categories = {"other"}

        if ext_category:
            self.category = ext_category
        elif tag_categories:
            ordered = [c["id"] for c in get_base_categories()]
            self.category = next(
                (c for c in ordered if c in tag_categories),
                sorted(tag_categories)[0]
            )
        elif ai_category:
            self.category = ai_category
        else:
            self.category = "other"

        self.subcategory  = resolve_subcategory(self.category, self.tags)
        self.subcategories = resolve_all_subcategories(self.category, self.tags)

    # ── Теги ──

    def add_tag(self, tag: str, ai_model=None) -> None:
        tag = normalize_tag(tag)
        if tag and tag not in self.tags:
            self.tags.append(tag)
            self.recompute()
            if ai_model:
                self.reclassify(ai_model)

    def remove_tag(self, tag: str) -> None:
        if tag in self.tags:
            self.tags.remove(tag)
            self.recompute()

    # ── Перерахунок ──

    def recompute(self, ai_model=None) -> None:
        if getattr(self, '_manual_category', False):
            self.subcategory   = resolve_subcategory(self.category, self.tags) or "general"
            self.subcategories = resolve_all_subcategories(self.category, self.tags)
            return
        inferred = infer_categories_from_tags(self.tags)
        if not inferred:
            inferred = {"other"}
        self.categories = inferred
        if self.category not in self.categories:
            self.category = sorted(self.categories)[0]
        self.subcategory   = resolve_subcategory(self.category, self.tags) or "general"
        self.subcategories = resolve_all_subcategories(self.category, self.tags)

    def reclassify(self, ai_model) -> None:
        if getattr(self, '_manual_category', False):
            self.subcategory   = resolve_subcategory(self.category, self.tags) or "general"
            self.subcategories = resolve_all_subcategories(self.category, self.tags)
            return
        ordered_base = [c["id"] for c in get_base_categories() if c["id"] != "other"]
        if "document" in self.tags:
            self.category = "document"
        else:
            for base in ordered_base:
                if base in self.tags:
                    self.category = base
                    break
        self.subcategory   = resolve_subcategory(self.category, self.tags) or "general"
        self.subcategories = resolve_all_subcategories(self.category, self.tags)

    # ── Пошук ──

    def matches_search(self, query: str) -> bool:
        q = query.lower().strip()
        if not q:
            return True
        if q in self.filename.lower():         return True
        if any(q in tag.lower() for tag in self.tags): return True
        if q in self.category.lower():         return True
        if any(q in sub.lower() for sub in self.subcategories): return True
        _, ext = os.path.splitext(self.filename)
        if ext and q in ext.lower().lstrip('.'): return True
        return False

    def search_score(self, query: str) -> int:
        q = query.lower().strip()
        score = 0
        if q == self.filename.lower():                      score += 100
        elif self.filename.lower().startswith(q):           score += 60
        elif q in self.filename.lower():                    score += 40
        if q in [t.lower() for t in self.tags]:             score += 30
        elif any(q in t.lower() for t in self.tags):        score += 15
        if q in self.category.lower():                      score += 10
        if any(q in sub.lower() for sub in self.subcategories): score += 8
        return score

    # ── Серіалізація ──

    def to_dict(self) -> Dict:
        return {
            "file_id":           self.file_id,
            "filename":          self.filename,
            "original_filename": self.original_filename,
            "size":              self.size,
            "mimetype":          self.mimetype,
            "upload_date":       self.upload_date.isoformat(),
            "category":          self.category,
            "subcategory":       self.subcategory,
            "subcategories":     self.subcategories,
            "tags":              self.tags,
            "confidence":        self.confidence,
            "storage_key":       self.storage_key,
            "manual_category":   getattr(self, "_manual_category", False),
        }

    @staticmethod
    def from_dict(data: Dict) -> "FileRecord":
        """Відновлює FileRecord з БД-рядка без повторного AI-аналізу."""
        obj = FileRecord.__new__(FileRecord)
        obj.file_id           = data["file_id"]
        obj.filename          = data["filename"]
        obj.original_filename = data.get("original_filename", data["filename"])
        obj.size              = data["size"]
        obj.mimetype          = data.get("mimetype", "application/octet-stream")
        obj.upload_date       = datetime.fromisoformat(data["upload_date"])
        obj.category          = data["category"]
        obj.subcategory       = data.get("subcategory", "general")
        obj.subcategories     = data.get("subcategories", ["general"])
        obj.tags              = data.get("tags", [])
        obj.confidence        = data.get("confidence", 0.0)
        obj.storage_key       = data.get("storage_key", "")
        obj._manual_category  = data.get("manual_category", False)

        obj.categories = infer_categories_from_tags(obj.tags)
        if not obj.categories:
            obj.categories = {obj.category}
        if obj.subcategories == ["general"] and obj.tags:
            obj.subcategories = resolve_all_subcategories(obj.category, obj.tags)
        return obj


# ── DataManager ────────────────────────────────────────────────

class DataManager:
    """
    Менеджер файлів.

    Сховище:
      - Бінарні файли → Cloudflare R2 (через r2: R2Storage)
      - Метадані      → Supabase PostgreSQL (таблиця 'files' + 'file_tags')
      - Кастомні підкатегорії → окрема таблиця 'custom_subcategories' або
        fallback JSON (_CUSTOM_SUB_FILE) якщо таблиця ще не існує

    In-memory кеш self.files оновлюється при кожній мутації.
    Для масштабування — замінити на Redis або TTL-кеш.
    """

    # Fallback-файл для кастомних підкатегорій (якщо БД-таблиці немає)
    _CUSTOM_SUB_FILE = os.path.join(
        os.path.dirname(__file__), 'data', 'custom_subcategories.json'
    )

    def __init__(self):
        self.ai_model = SemanticFileClassifier()
        self.files: List[FileRecord] = []
        self.custom_subcategories: Dict[str, List[str]] = {}
        self._load()

    # ══════════════════════════════════════════════════════════
    # ПРИВАТНІ: завантаження / збереження
    # ══════════════════════════════════════════════════════════

    def _load(self) -> None:
        """Завантажує метадані з Supabase + кастомні підкатегорії."""
        self._load_files_from_db()
        self._load_custom_subcategories()

    def _load_files_from_db(self) -> None:
        """
        Читає всі активні файли з таблиці 'files' + теги з 'file_tags'.
        Якщо таблиця ще не існує — graceful fallback до порожнього списку.
        """
        try:
            from auth.models import db
            from sqlalchemy import text

            with db.engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT
                        f.id            AS file_id,
                        f.filename,
                        f.original_filename,
                        f.size,
                        f.mimetype,
                        f.category,
                        f.subcategory,
                        f.confidence,
                        f.manual_category,
                        f.storage_key,
                        f.upload_date,
                        COALESCE(
                            array_agg(ft.tag ORDER BY ft.created_at)
                            FILTER (WHERE ft.tag IS NOT NULL),
                            '{}'::text[]
                        ) AS tags
                    FROM files f
                    LEFT JOIN file_tags ft ON ft.file_id = f.id
                    WHERE f.status = 'active'
                    GROUP BY f.id
                    ORDER BY f.upload_date DESC
                """)).fetchall()

            self.files = []
            for row in rows:
                d = {
                    'file_id':           row.file_id,
                    'filename':          row.filename,
                    'original_filename': row.original_filename or row.filename,
                    'size':              row.size,
                    'mimetype':          row.mimetype or 'application/octet-stream',
                    'category':          row.category,
                    'subcategory':       row.subcategory or 'general',
                    'subcategories':     [row.subcategory or 'general'],
                    'tags':              list(row.tags) if row.tags else [],
                    'confidence':        float(row.confidence or 0.0),
                    'storage_key':       row.storage_key or '',
                    'upload_date':       row.upload_date.isoformat(),
                    'manual_category':   bool(row.manual_category),
                }
                self.files.append(FileRecord.from_dict(d))

            print(f"[DB] Loaded {len(self.files)} files from Supabase")

        except Exception as e:
            print(f"[DB] load_files warning: {e}")
            self.files = []

    def _load_custom_subcategories(self) -> None:
        """Завантажує кастомні підкатегорії (JSON-файл як сховище)."""
        os.makedirs(os.path.dirname(self._CUSTOM_SUB_FILE), exist_ok=True)
        try:
            if os.path.exists(self._CUSTOM_SUB_FILE):
                with open(self._CUSTOM_SUB_FILE, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                self.custom_subcategories = {
                    k: v for k, v in raw.items()
                    if k not in _SYSTEM_SUBCATEGORY_NAMES
                    and k not in _BASE_CATEGORY_IDS
                }
            else:
                self.custom_subcategories = {}
        except Exception as e:
            print(f"[DataManager] custom_subcategories load error: {e}")
            self.custom_subcategories = {}

    def save_data(self) -> None:
        """
        Зберігає кастомні підкатегорії у JSON.
        Метадані файлів зберігаються окремо через _save_record() при кожній мутації.
        """
        os.makedirs(os.path.dirname(self._CUSTOM_SUB_FILE), exist_ok=True)
        try:
            with open(self._CUSTOM_SUB_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.custom_subcategories, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[DataManager] save custom_subcategories error: {e}")

    def _save_record(self, record: FileRecord, user_id: int = None) -> bool:
        """
        Зберігає або оновлює один FileRecord в Supabase.
        Теги записуються в file_tags (upsert).
        Повертає True при успіху.
        """
        try:
            from auth.models import db
            from sqlalchemy import text

            now = datetime.utcnow()

            with db.engine.begin() as conn:
                # Upsert основного рядка
                conn.execute(text("""
                    INSERT INTO files (
                        id, user_id, filename, original_filename,
                        size, mimetype, category, subcategory,
                        confidence, manual_category, storage_key,
                        storage_provider, status, upload_date, updated_at
                    ) VALUES (
                        :id, :user_id, :filename, :original_filename,
                        :size, :mimetype, :category, :subcategory,
                        :confidence, :manual_category, :storage_key,
                        :storage_provider, 'active', :upload_date, :now
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        filename         = EXCLUDED.filename,
                        category         = EXCLUDED.category,
                        subcategory      = EXCLUDED.subcategory,
                        confidence       = EXCLUDED.confidence,
                        manual_category  = EXCLUDED.manual_category,
                        storage_key      = EXCLUDED.storage_key,
                        storage_provider = EXCLUDED.storage_provider,
                        updated_at       = EXCLUDED.updated_at
                """), {
                    'id':               record.file_id,
                    'user_id':          user_id,
                    'filename':         record.filename,
                    'original_filename': record.original_filename,
                    'size':             record.size,
                    'mimetype':         record.mimetype,
                    'category':         record.category,
                    'subcategory':      record.subcategory,
                    'confidence':       record.confidence,
                    'manual_category':  getattr(record, '_manual_category', False),
                    'storage_key':      record.storage_key,
                    'storage_provider': _STORAGE_PROVIDER,
                    'upload_date':      record.upload_date,
                    'now':              now,
                })

                # Оновлення тегів: видаляємо старі → вставляємо нові
                conn.execute(text(
                    "DELETE FROM file_tags WHERE file_id = :fid"
                ), {'fid': record.file_id})

                if record.tags:
                    for tag in record.tags:
                        conn.execute(text("""
                            INSERT INTO file_tags (file_id, tag, created_by, created_at)
                            VALUES (:fid, :tag, :uid, :now)
                            ON CONFLICT (file_id, tag) DO NOTHING
                        """), {'fid': record.file_id, 'tag': tag,
                               'uid': user_id, 'now': now})

            return True
        except Exception as e:
            print(f"[DB] _save_record error ({record.file_id}): {e}")
            return False

    def _delete_record_from_db(self, file_id: str) -> bool:
        """Soft-delete в Supabase (status = 'deleted')."""
        try:
            from auth.models import db
            from sqlalchemy import text
            with db.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE files SET status = 'deleted', deleted_at = :now
                    WHERE id = :fid
                """), {'fid': file_id, 'now': datetime.utcnow()})
            return True
        except Exception as e:
            print(f"[DB] delete_record error ({file_id}): {e}")
            return False

    # ══════════════════════════════════════════════════════════
    # ПУБЛІЧНІ: CRUD
    # ══════════════════════════════════════════════════════════

    def check_duplicate(self, filename: str) -> "FileRecord | None":
        for f in self.files:
            if f.filename == filename:
                return f
        return None

    def add_file(
        self,
        file,
        replace_existing: bool = False,
        user_id: int = None,
    ) -> "FileRecord | None":
        """
        Завантажує файл у R2, зберігає метадані в Supabase.
        file: Flask FileStorage об'єкт.
        Повертає FileRecord або None при помилці.
        """
        filename = safe_filename(file.filename)
        mimetype = file.content_type or 'application/octet-stream'
        existing = self.check_duplicate(filename)

        if existing and not replace_existing:
            return None

        # Зчитуємо байти в пам'ять (буфер — файл < MAX_CONTENT_LENGTH)
        file_bytes = file.read()

        # Якщо заміна — видаляємо старий об'єкт з R2
        if existing and replace_existing:
            if existing.storage_key:
                storage.delete(existing.storage_key)
            self._delete_record_from_db(existing.file_id)
            self.files.remove(existing)

        # Створюємо FileRecord (AI-класифікація)
        record = FileRecord(
            file_bytes        = file_bytes,
            original_filename = file.filename,
            ai_model          = self.ai_model,
            mimetype          = mimetype,
        )

        # Завантажуємо в R2/B2
        # S3 Metadata дозволяє лише ASCII — кодуємо original filename через urllib
        from urllib.parse import quote as _url_quote
        ok = storage.upload(
            file_obj     = io.BytesIO(file_bytes),
            key          = record.storage_key,
            content_type = mimetype,
            extra_meta   = {
                # URL-encode щоб уникнути non-ASCII символів (кирилиця, тощо)
                'original-filename': _url_quote(file.filename, safe='._- '),
                'file-id':           record.file_id,
            },
        )
        if not ok:
            return None

        # Зберігаємо метадані в Supabase
        self._save_record(record, user_id=user_id)
        self.files.append(record)
        return record

    def get_file_by_id(self, file_id: str) -> "FileRecord | None":
        for f in self.files:
            if f.file_id == file_id:
                return f
        return None

    def delete_file(self, file_id: str) -> bool:
        """Видаляє файл з R2 і робить soft-delete в Supabase."""
        record = self.get_file_by_id(file_id)
        if not record:
            return False
        # Видаляємо з R2
        if record.storage_key:
            storage.delete(record.storage_key)
        # Soft-delete в Supabase
        self._delete_record_from_db(file_id)
        # Прибираємо з кешу
        self.files.remove(record)
        return True

    def get_filtered_files(
        self,
        category: str = None,
        subcategory: str = None,
        search_query: str = None,
        search_global: bool = False,
    ) -> List[FileRecord]:
        is_global_search = bool(search_query and search_global)
        result = self.files

        if not is_global_search and category and category != 'all':
            result = [f for f in result if f.category == category]

        if not search_query and subcategory:
            if subcategory == 'general':
                result = [f for f in result if f.subcategories == ['general']]
            else:
                result = [f for f in result if subcategory in f.subcategories]

        if search_query:
            result = [f for f in result if f.matches_search(search_query)]
            result = sorted(result, key=lambda f: f.search_score(search_query), reverse=True)

        return result

    def get_stats(self) -> dict:
        categories: dict[str, int] = {}
        for f in self.files:
            categories[f.category] = categories.get(f.category, 0) + 1
        return {
            'total_files': len(self.files),
            'total_size':  sum(f.size for f in self.files),
            'categories':  categories,
        }

    def get_analytics(self) -> dict:
        """
        Повна аналітика (без змін логіки — але тепер дані з Supabase).
        """
        from collections import Counter
        from datetime import timedelta

        files = self.files
        total = len(files)

        if total == 0:
            return {
                'total_files': 0, 'total_size': 0,
                'categories_dist': [], 'top_tags': [],
                'confidence_dist': [], 'upload_heatmap': [],
                'size_by_category': [], 'top_extensions': [],
                'uploads_by_month': [], 'high_confidence_pct': 0,
                'avg_tags_per_file': 0, 'largest_category': None,
            }

        cat_counts = Counter(f.category for f in files)
        categories_dist = [
            {'category': cat, 'count': cnt, 'pct': round(cnt / total * 100, 1)}
            for cat, cnt in cat_counts.most_common()
        ]

        all_tags = [tag for f in files for tag in f.tags]
        top_tags = [{'tag': t, 'count': c} for t, c in Counter(all_tags).most_common(15)]

        buckets = [0] * 10
        for f in files:
            buckets[min(int(f.confidence * 10), 9)] += 1
        confidence_dist = [
            {'range': f'{i*10}-{i*10+10}%', 'count': buckets[i],
             'pct': round(buckets[i] / total * 100, 1)}
            for i in range(10)
        ]

        today     = datetime.utcnow().date()
        start_day = today - timedelta(days=83)
        day_counts: dict[str, int] = {}
        for f in files:
            d = f.upload_date.date()
            if d >= start_day:
                day_counts[d.isoformat()] = day_counts.get(d.isoformat(), 0) + 1
        upload_heatmap = [
            {'date': (start_day + timedelta(days=i)).isoformat(),
             'count': day_counts.get((start_day + timedelta(days=i)).isoformat(), 0)}
            for i in range(84)
        ]

        size_by_cat: dict[str, list] = {}
        for f in files:
            size_by_cat.setdefault(f.category, []).append(f.size)
        size_by_category = [
            {'category': cat,
             'avg_size': int(sum(sizes) / len(sizes)),
             'total_size': sum(sizes)}
            for cat, sizes in sorted(size_by_cat.items(),
                                     key=lambda x: sum(x[1]), reverse=True)
        ]

        exts = []
        for f in files:
            _, ext = os.path.splitext(f.filename)
            if ext:
                exts.append(ext.lower().lstrip('.'))
        top_extensions = [
            {'ext': e, 'count': c} for e, c in Counter(exts).most_common(10)
        ]

        month_counts: dict[str, int] = {}
        for f in files:
            key = f.upload_date.strftime('%Y-%m')
            month_counts[key] = month_counts.get(key, 0) + 1
        uploads_by_month = []
        for i in range(5, -1, -1):
            try:
                from dateutil.relativedelta import relativedelta
                m = datetime.utcnow() - relativedelta(months=i)
            except ImportError:
                month_num = datetime.utcnow().month - i
                year      = datetime.utcnow().year
                while month_num <= 0:
                    month_num += 12; year -= 1
                m = datetime(year, month_num, 1)
            key = m.strftime('%Y-%m')
            uploads_by_month.append({
                'month': m.strftime('%b %Y'), 'key': key,
                'count': month_counts.get(key, 0),
            })

        high_conf          = sum(1 for f in files if f.confidence >= 0.8)
        high_confidence_pct = round(high_conf / total * 100, 1)
        avg_tags_per_file   = round(sum(len(f.tags) for f in files) / total, 1)
        largest_category    = cat_counts.most_common(1)[0][0] if cat_counts else None

        return {
            'total_files': total,
            'total_size':  sum(f.size for f in files),
            'categories_dist':    categories_dist,
            'top_tags':           top_tags,
            'confidence_dist':    confidence_dist,
            'upload_heatmap':     upload_heatmap,
            'size_by_category':   size_by_category,
            'top_extensions':     top_extensions,
            'uploads_by_month':   uploads_by_month,
            'high_confidence_pct': high_confidence_pct,
            'avg_tags_per_file':   avg_tags_per_file,
            'largest_category':    largest_category,
        }


# ── Глобальний менеджер ────────────────────────────────────────
# Ініціалізуємо всередині app context, щоб SQLAlchemy мав доступ до БД
data_manager: "DataManager" = None  # type: ignore

with app.app_context():
    data_manager = DataManager()


# ═══════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════

# ── Сторінки UI ───────────────────────────────────────────────

@app.route('/home')
@app.route('/landing')
@app.route('/login')
@app.route('/register')
@app.route('/auth')
def home():
    """Лендінг + форма входу/реєстрації."""
    return render_template('landing.html')


@app.route('/')
@login_required
def index():
    """Дешборд — основна сторінка. Передає роль для JS UI restrictions."""
    user = get_current_user()
    role = user.role if user else 'viewer'
    return render_template('index.html', user_role=role)


@app.route('/profile')
@login_required
def profile():
    """Сторінка профілю. Передає дані через Jinja — JS не залежить від JWT/sessionStorage."""
    import json as _json
    user = get_current_user()
    raw  = data_manager.get_stats()
    tags = len({t for f2 in data_manager.files for t in f2.tags})
    user_dict = user.to_dict(include_sensitive=True) if user else {}
    user_dict['stats'] = {
        'total_files': raw['total_files'],
        'total_size':  raw['total_size'],
        'categories':  len(raw.get('categories', [])),
        'total_tags':  tags,
    }
    return render_template('profile.html', user_json=_json.dumps(user_dict, ensure_ascii=False))


# ── API статистики (відкрита для всіх авторизованих) ───────────

@app.route('/api/stats/summary', methods=['GET'])
@login_required
def stats_summary():
    """Загальна статистика для профілю та лендінгу."""
    stats = data_manager.get_stats()
    return jsonify({
        'total_files':  stats['total_files'],
        'total_size':   stats['total_size'],
        'categories':   len(stats['categories']),
        'total_tags':   len({t for f in data_manager.files for t in f.tags}),
    })


@app.route('/api/files', methods=['GET'])
@login_required
@permission_required('files:read')
def get_files():
    category = request.args.get('category', 'all')
    subcategory = request.args.get('subcategory')
    search = request.args.get('search', '')
    # search_global=true → пошук по всіх категоріях, ігнорує category/subcategory фільтри
    search_global = request.args.get('search_global', 'false').lower() == 'true'
    files = data_manager.get_filtered_files(category, subcategory, search, search_global)
    return jsonify([f.to_dict() for f in files])

@app.route('/api/search', methods=['GET'])
@login_required
@permission_required('files:read')
def search_files():
    """
    Глобальний пошук по всіх файлах незалежно від категорії.
    Повертає результати згруповані по категоріях для зручного відображення.
    GET /api/search?q=звіт
    """
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'query': query, 'total': 0, 'results': [], 'by_category': {}})

    matched = data_manager.get_filtered_files(
        search_query=query,
        search_global=True,
    )

    # Групуємо по категоріях для UI фільтрів
    by_category: dict[str, int] = {}
    for f in matched:
        by_category[f.category] = by_category.get(f.category, 0) + 1

    return jsonify({
        'query': query,
        'total': len(matched),
        'results': [f.to_dict() for f in matched],
        'by_category': by_category,
    })


@app.route('/api/files/<file_id>', methods=['GET'])
@login_required
@permission_required('files:read')
def get_file(file_id):
    record = data_manager.get_file_by_id(file_id)
    if record:
        return jsonify(record.to_dict())
    return jsonify({'error': 'File not found'}), 404


def write_audit(action: str, target_type: str = None, target_id: str = None, detail: dict = None):
    """Записує подію в audit_log. Безпечно ігнорує помилки."""
    try:
        from auth.models import db, AuditLog
        user = get_current_user()
        import json as _json
        entry = AuditLog(
            actor_id    = user.id if user else None,
            action      = action,
            target_type = target_type,
            target_id   = str(target_id) if target_id else None,
            detail      = _json.dumps(detail, ensure_ascii=False) if detail else None,
            ip_address  = request.remote_addr,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        print(f'[audit] write failed: {e}')


@app.route('/api/upload', methods=['POST'])
@login_required
@permission_required('files:upload')
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    try:
        replace_existing = request.form.get('replace', 'false').lower() == 'true'
        filename = safe_filename(file.filename)
        existing = data_manager.check_duplicate(filename)

        if existing and not replace_existing:
            return jsonify({
                'duplicate': True,
                'existing_file': existing.to_dict(),
                'message': f'Файл "{filename}" вже існує',
            }), 409

        user = get_current_user()
        record = data_manager.add_file(
            file,
            replace_existing = replace_existing,
            user_id          = user.id if user else None,
        )
        if record is None:
            return jsonify({'error': 'File upload failed (R2 or DB error)'}), 500

        write_audit('file.upload', 'file', record.file_id, {
            'filename':     record.filename,
            'size':         record.size,
            'category':     record.category,
            'storage_key':  record.storage_key,
            'replaced':     replace_existing,
        })

        return jsonify({
            'duplicate': False,
            'file':      record.to_dict(),
            'replaced':  replace_existing,
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/files/<file_id>', methods=['DELETE'])
@login_required
@permission_required('files:delete')
def delete_file(file_id):
    record = data_manager.get_file_by_id(file_id)
    if not record:
        return jsonify({'error': 'File not found'}), 404
    filename = record.filename
    if data_manager.delete_file(file_id):
        write_audit('file.delete', 'file', file_id, {'filename': filename})
        return jsonify({'success': True})
    return jsonify({'error': 'File not found'}), 404


@app.route('/api/files/<file_id>/tags', methods=['POST'])
@login_required
@permission_required('files:tag_add')
def add_tag(file_id):
    record = data_manager.get_file_by_id(file_id)
    if not record:
        return jsonify({'error': 'File not found'}), 404

    tag = request.json.get('tag')
    if not tag:
        return jsonify({'error': 'No tag provided'}), 400

    record.add_tag(tag, data_manager.ai_model)
    user = get_current_user()
    data_manager._save_record(record, user_id=user.id if user else None)
    write_audit('file.tag_add', 'file', file_id, {'filename': record.filename, 'tag': tag})
    return jsonify(record.to_dict())


@app.route('/api/files/<file_id>/tags/<tag>', methods=['DELETE'])
@login_required
@permission_required('files:tag_remove')
def remove_tag(file_id, tag):
    record = data_manager.get_file_by_id(file_id)
    if not record:
        return jsonify({'error': 'File not found'}), 404

    record.remove_tag(tag)
    user = get_current_user()
    data_manager._save_record(record, user_id=user.id if user else None)
    write_audit('file.tag_remove', 'file', file_id, {'filename': record.filename, 'tag': tag})
    return jsonify(record.to_dict())


@app.route('/api/files/<file_id>/category', methods=['PATCH'])
@login_required
@permission_required('files:move')
def update_category(file_id):
    """Змінити категорію файлу вручну."""
    record = data_manager.get_file_by_id(file_id)
    if not record:
        return jsonify({'error': 'File not found'}), 404

    data = request.json
    new_category = data.get('category', '').strip().lower()

    if not new_category:
        return jsonify({'error': 'Category is required'}), 400
    if not re.match(r'^[\w\-]+$', new_category):
        return jsonify({'error': 'Category name can only contain letters, digits, hyphens and underscores'}), 400

    # Видаляємо теги-назви базових категорій (беремо з конфігу)
    record.tags = [t for t in record.tags if t.lower() not in _BASE_CATEGORY_IDS]

    record.category = new_category
    record.categories = {new_category}
    record.subcategory = resolve_subcategory(new_category, record.tags) or 'general'
    record.subcategories = resolve_all_subcategories(new_category, record.tags)
    record._manual_category = True
    user = get_current_user()
    data_manager._save_record(record, user_id=user.id if user else None)
    write_audit('file.move', 'file', file_id, {
        'filename': record.filename, 'new_category': new_category
    })
    return jsonify(record.to_dict())


@app.route('/api/files/<file_id>/download', methods=['GET'])
@login_required
@permission_required('files:download')
def download_file(file_id):
    """
    Завантажує файл з R2 і повертає клієнту як attachment.
    Якщо задано R2_PUBLIC_URL — перенаправляє на presigned URL (швидше).
    """
    record = data_manager.get_file_by_id(file_id)
    if not record:
        return jsonify({'error': 'File not found'}), 404

    if not record.storage_key:
        return jsonify({'error': 'No storage key — file may not be migrated yet'}), 404

    write_audit('file.download', 'file', file_id, {
        'filename': record.filename, 'storage_key': record.storage_key
    })

    # Якщо є публічний домен — відправляємо presigned redirect (без проксі через Flask)
    if _STORAGE_PUBLIC_URL:
        from flask import redirect as flask_redirect
        url = storage.get_public_url(record.storage_key)
        if url:
            return flask_redirect(url)

    # Інакше проксіюємо через Flask (менш ефективно, але universально)
    buf = storage.download(record.storage_key)
    if buf is None:
        return jsonify({'error': 'File not found in storage'}), 404

    return flask_send_file(
        buf,
        as_attachment    = True,
        download_name    = record.original_filename or record.filename,
        mimetype         = record.mimetype or 'application/octet-stream',
    )


@app.route('/api/categories', methods=['GET'])
@login_required
@permission_required('categories:read')
def get_categories():
    """
    Повертає всі категорії: базові (з конфігу) + кастомні.
    Кастомні = ті що є у файлах АБО зареєстровані через POST /api/categories.
    """
    # Базові категорії формуються з конфігу (не захардкоджено)
    base = [
        {'id': c['id'], 'label': f"{c['emoji']} {c['label']}"}
        for c in get_base_categories()
    ]
    base_ids = {c['id'] for c in base}

    from_files = {f.category for f in data_manager.files if f.category not in base_ids}
    from_registry = set(data_manager.custom_subcategories.keys()) - base_ids
    custom_ids = sorted(from_files | from_registry)

    custom = [{'id': cid, 'label': f'🗂️ {cid.upper()}'} for cid in custom_ids]
    return jsonify(base + custom)


@app.route('/api/categories', methods=['POST'])
@login_required
@permission_required('categories:create')
def create_category():
    """Створити кастомну категорію."""
    data = request.json or {}
    name = (data.get('name') or '').strip().lower()

    if not name:
        return jsonify({'error': 'name required'}), 400
    if not re.match(r'^[\w\-]+$', name):
        return jsonify({'error': 'Only letters, digits, hyphens and underscores allowed'}), 400
    if name in _BASE_CATEGORY_IDS:
        return jsonify({'error': f'"{name}" is a built-in category'}), 400

    if name not in data_manager.custom_subcategories:
        data_manager.custom_subcategories[name] = []
    data_manager.save_data()
    return jsonify({'id': name, 'label': f'🗂️ {name.upper()}'}), 201


@app.route('/api/categories/<category_id>', methods=['DELETE'])
@login_required
@permission_required('categories:delete')
def delete_category(category_id):
    """Видалити кастомну категорію; файли переміщуються до 'other'."""
    if category_id in _BASE_CATEGORY_IDS:
        return jsonify({'error': 'Cannot delete base categories'}), 400

    moved = 0
    user = get_current_user()
    for rec in data_manager.files:
        if rec.category == category_id:
            rec.category = 'other'
            rec.categories = {'other'}
            rec.subcategory = 'general'
            rec.subcategories = ['general']
            data_manager._save_record(rec, user_id=user.id if user else None)
            moved += 1

    data_manager.custom_subcategories.pop(category_id, None)
    data_manager.save_data()
    return jsonify({'deleted': category_id, 'files_moved': moved})


@app.route('/api/stats', methods=['GET'])
@login_required
@permission_required('analytics:read')
def get_stats():
    return jsonify(data_manager.get_stats())


@app.route('/api/analytics', methods=['GET'])
@login_required
@permission_required('analytics:read')
def get_analytics():
    """Повна аналітика для дашборду."""
    return jsonify(data_manager.get_analytics())


@app.route('/api/subcategories/<category>', methods=['GET'])
@login_required
@permission_required('categories:read')
def get_subcategories(category):
    """
    Всі можливі підкатегорії категорії (системні з конфігу).
    """
    subcategories = list(_SUBCATEGORY_RULES.get(category, {}).keys())
    if subcategories:
        subcategories.insert(0, "general")
    return jsonify(subcategories)


@app.route('/api/categories/<category_id>/subcategories', methods=['GET'])
@login_required
@permission_required('categories:read')
def get_category_subcategories(category_id):
    """Системні + кастомні підкатегорії категорії."""
    system = list(_SUBCATEGORY_RULES.get(category_id, {}).keys())
    custom = data_manager.custom_subcategories.get(category_id, [])
    all_subs = ['general'] + system + [
        s for s in custom if s not in system and s != 'general'
    ]
    return jsonify(all_subs)


@app.route('/api/categories/<category_id>/subcategories', methods=['POST'])
@login_required
@permission_required('subcategories:create')
def create_subcategory(category_id):
    """Додати кастомну підкатегорію."""
    data = request.json or {}
    name = (data.get('name') or '').strip().lower()

    if not name:
        return jsonify({'error': 'name required'}), 400
    if not re.match(r'^[\w\-]+$', name):
        return jsonify({'error': 'Only letters, digits, hyphens and underscores allowed'}), 400
    if name == 'general':
        return jsonify({'error': '"general" is reserved'}), 400

    if category_id not in data_manager.custom_subcategories:
        data_manager.custom_subcategories[category_id] = []

    if name not in data_manager.custom_subcategories[category_id]:
        data_manager.custom_subcategories[category_id].append(name)
        data_manager.save_data()

    return jsonify({'category': category_id, 'subcategory': name}), 201


@app.route('/api/categories/<category_id>/subcategories/<sub_name>', methods=['DELETE'])
@login_required
@permission_required('subcategories:delete')
def delete_subcategory(category_id, sub_name):
    """Видалити кастомну підкатегорію; файли повертаються до 'general'."""
    system = set(_SUBCATEGORY_RULES.get(category_id, {}).keys()) | {'general'}
    if sub_name in system:
        return jsonify({'error': f'Cannot delete system subcategory "{sub_name}"'}), 400

    moved = 0
    for rec in data_manager.files:
        if rec.category == category_id and sub_name in rec.subcategories:
            rec.subcategories = [s for s in rec.subcategories if s != sub_name]
            if not rec.subcategories:
                rec.subcategories = ['general']
            if rec.subcategory == sub_name:
                rec.subcategory = rec.subcategories[0]
            moved += 1

    subs = data_manager.custom_subcategories.get(category_id, [])
    if sub_name in subs:
        subs.remove(sub_name)
        data_manager.custom_subcategories[category_id] = subs
    data_manager.save_data()  # зберігає custom_subcategories у JSON
    return jsonify({'deleted': sub_name, 'files_updated': moved})


@app.route('/api/bulk/remove-tag', methods=['POST'])
@login_required
@permission_required('files:tag_remove')
def bulk_remove_tag():
    """Видалити один тег з кількох файлів одночасно."""
    data = request.json or {}
    file_ids = data.get('file_ids', [])
    tag = (data.get('tag') or '').strip().lower()

    if not file_ids:
        return jsonify({'error': 'file_ids required'}), 400
    if not tag:
        return jsonify({'error': 'tag required'}), 400

    user = get_current_user()
    updated = 0
    for fid in file_ids:
        rec = data_manager.get_file_by_id(fid)
        if rec and tag in rec.tags:
            rec.remove_tag(tag)
            data_manager._save_record(rec, user_id=user.id if user else None)
            updated += 1

    return jsonify({'updated': updated, 'tag': tag})


# ═══════════════════════════════════════════════════════════════
# FILE PREVIEW  (/api/files/<id>/preview-meta  +  /preview)
# ═══════════════════════════════════════════════════════════════

_PV_IMAGE = {'jpg','jpeg','png','gif','webp','bmp','ico','svg','tiff','tif'}
_PV_VIDEO = {'mp4','webm','mov','avi','mkv','wmv','m4v'}
_PV_AUDIO = {'mp3','wav','ogg','flac','m4a','aac','opus','wma'}
_PV_PDF   = {'pdf'}
_PV_SHEET = {'xlsx','xls','ods','csv'}
_PV_WORD  = {'docx','odt'}
_PV_ARCH  = {'zip','tar','gz','bz2'}
_PV_TEXT  = {
    'txt','py','js','ts','jsx','tsx','json','yaml','yml','toml','ini',
    'cfg','conf','sh','bash','md','rst','log','sql','html','htm','css',
    'scss','less','xml','env','gitignore','dockerfile','makefile',
    'c','cpp','h','hpp','java','go','rs','rb','php','swift','kt',
}
_PV_LANG = {
    'py':'python','js':'javascript','ts':'typescript','jsx':'javascript',
    'tsx':'typescript','json':'json','yaml':'yaml','yml':'yaml',
    'html':'html','htm':'html','css':'css','scss':'css','less':'css',
    'xml':'xml','sql':'sql','sh':'bash','bash':'bash','md':'markdown',
    'rst':'markdown','c':'c','cpp':'cpp','java':'java','go':'go',
    'rs':'rust','rb':'ruby','php':'php','swift':'swift','kt':'kotlin',
    'toml':'toml','ini':'ini',
}
_PV_MIME_IMG = {
    'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','gif':'image/gif',
    'webp':'image/webp','bmp':'image/bmp','ico':'image/x-icon',
    'svg':'image/svg+xml','tiff':'image/tiff','tif':'image/tiff',
}
_PV_MIME_VID = {
    'mp4':'video/mp4','webm':'video/webm','mov':'video/quicktime',
    'avi':'video/x-msvideo','mkv':'video/x-matroska','wmv':'video/x-ms-wmv','m4v':'video/mp4',
}
_PV_MIME_AUD = {
    'mp3':'audio/mpeg','wav':'audio/wav','ogg':'audio/ogg','flac':'audio/flac',
    'm4a':'audio/mp4','aac':'audio/aac','opus':'audio/opus','wma':'audio/x-ms-wma',
}
_PV_TEXT_LIMIT = 12_000
_PV_TABLE_ROWS = 40
_PV_TABLE_COLS = 20
_PV_ARCH_LIMIT = 250


def _pv_ext(filename: str) -> str:
    return os.path.splitext(filename)[1].lower().lstrip('.')


def _read_docx(path: str):
    """
    Читає параграфи з .docx через zipfile + xml.etree.ElementTree.
    Не використовує python-docx — уникає проблем з версіями бібліотеки.
    Повертає (paragraphs: list[str], total: int, truncated: bool).
    """
    import zipfile as _zf
    import xml.etree.ElementTree as _ET

    NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    paras = []

    try:
        with _zf.ZipFile(path, 'r') as zf:
            if 'word/document.xml' not in zf.namelist():
                return [], 0, False   # порожній або не валідний docx
            xml_bytes = zf.read('word/document.xml')

        root = _ET.fromstring(xml_bytes)
        for p in root.iter(f'{{{NS}}}p'):
            parts = []
            for t in p.iter(f'{{{NS}}}t'):
                if t.text:
                    parts.append(t.text)
            line = ''.join(parts).strip()
            if line:
                paras.append(line)

    except Exception:
        return [], 0, False

    total = len(paras)
    return paras[:100], total, total > 100


@app.route('/api/files/<file_id>/preview-meta', methods=['GET'])
@login_required
@permission_required('files:preview')
def preview_meta(file_id):
    """
    Повертає тип прев'ю + базові метадані.
    Розмір і тип беруться з метаданих (без звернення до R2).
    """
    rec = data_manager.get_file_by_id(file_id)
    if not rec:
        return jsonify({'error': 'not found'}), 404

    e  = _pv_ext(rec.filename)
    sz = rec.size

    if not rec.storage_key:
        return jsonify({'kind': 'none', 'reason': 'no storage key'})

    if e in _PV_IMAGE: return jsonify({'kind':'image','mime':_PV_MIME_IMG.get(e,'image/jpeg'),'size':sz})
    if e in _PV_VIDEO: return jsonify({'kind':'video','mime':_PV_MIME_VID.get(e,'video/mp4'),'size':sz})
    if e in _PV_AUDIO: return jsonify({'kind':'audio','mime':_PV_MIME_AUD.get(e,'audio/mpeg'),'size':sz})
    if e in _PV_PDF:   return jsonify({'kind':'pdf','size':sz})
    if e in _PV_SHEET: return jsonify({'kind':'sheet','ext':e,'size':sz})
    if e in _PV_WORD:  return jsonify({'kind':'word','ext':e,'size':sz})
    if e in _PV_ARCH or rec.filename.endswith(('.tar.gz','.tar.bz2')):
                       return jsonify({'kind':'archive','ext':e,'size':sz})
    if e in _PV_TEXT:  return jsonify({'kind':'text','lang':_PV_LANG.get(e,'text'),'size':sz})

    # Невідоме розширення: якщо маленький — спробуємо як text при preview
    if sz < 100_000:
        return jsonify({'kind':'text','lang':'text','size':sz})

    return jsonify({'kind':'none','size':sz})


@app.route('/api/files/<file_id>/preview', methods=['GET'])
@login_required
@permission_required('files:preview')
def preview_file(file_id):
    """
    Завантажує файл з R2 в пам'ять і повертає прев'ю.
    image/video/audio/pdf  → raw bytes (send_file)
    sheet/word/archive/text → JSON
    """
    rec = data_manager.get_file_by_id(file_id)
    if not rec:
        return jsonify({'error': 'File not found'}), 404
    if not rec.storage_key:
        return jsonify({'error': 'No storage key'}), 404

    e = _pv_ext(rec.filename)

    # ── Images / Video / Audio / PDF → stream прямо з R2 ─────
    if e in _PV_IMAGE or e in _PV_VIDEO or e in _PV_AUDIO or e in _PV_PDF:
        # Для медіа-файлів: redirect на presigned URL (без проксі через Flask)
        url = storage.get_public_url(rec.storage_key)
        if url and _STORAGE_PUBLIC_URL:
            from flask import redirect as flask_redirect
            return flask_redirect(url)

        buf = storage.download(rec.storage_key)
        if buf is None:
            return jsonify({'error': 'Not found in R2'}), 404

        if e in _PV_IMAGE:
            if e == 'svg':
                return flask_send_file(buf, mimetype='image/svg+xml')
            try:
                from PIL import Image as _Img
                img = _Img.open(buf)
                img.thumbnail((960, 960), _Img.LANCZOS)
                out_fmt = 'PNG' if e == 'png' else 'JPEG'
                if img.mode in ('RGBA', 'P', 'LA') and out_fmt == 'JPEG':
                    img = img.convert('RGB')
                out_buf = io.BytesIO()
                img.save(out_buf, format=out_fmt, quality=88, optimize=True)
                out_buf.seek(0)
                return flask_send_file(out_buf, mimetype=_PV_MIME_IMG.get(e, 'image/jpeg'))
            except Exception:
                buf.seek(0)
                return flask_send_file(buf, mimetype=_PV_MIME_IMG.get(e, 'image/jpeg'))

        if e in _PV_VIDEO:
            return flask_send_file(buf, mimetype=_PV_MIME_VID.get(e, 'video/mp4'), conditional=True)
        if e in _PV_AUDIO:
            return flask_send_file(buf, mimetype=_PV_MIME_AUD.get(e, 'audio/mpeg'), conditional=True)
        if e in _PV_PDF:
            return flask_send_file(buf, mimetype='application/pdf')

    # ── Для структурованих файлів — завантажуємо в тимчасовий файл ──────────
    # Використовуємо _TEMP_DIR щоб не тримати великі файли в пам'яті RAM
    tmp_path = None
    try:
        import tempfile
        suffix = f'.{e}' if e else ''
        with tempfile.NamedTemporaryFile(
            dir=_TEMP_DIR, suffix=suffix, delete=False
        ) as tmp:
            tmp_path = tmp.name
            buf = storage.download(rec.storage_key)
            if buf is None:
                return jsonify({'error': 'Not found in R2'}), 404
            tmp.write(buf.read())

        path = tmp_path

        # ── Spreadsheets ──────────────────────────────────────
        if e in _PV_SHEET:
            try:
                import pandas as _pd, csv as _csv
                if e == 'csv':
                    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                        sample = fh.read(4096)
                    try:
                        dialect = _csv.Sniffer().sniff(sample, delimiters=',;\t|')
                        sep = dialect.delimiter
                    except Exception:
                        sep = ','
                    df = _pd.read_csv(path, sep=sep, nrows=_PV_TABLE_ROWS,
                                      encoding='utf-8', errors='replace', dtype=str)
                else:
                    df = _pd.read_excel(path, nrows=_PV_TABLE_ROWS,
                                        engine='openpyxl', dtype=str)

                total_cols = len(df.columns)
                if total_cols > _PV_TABLE_COLS:
                    df = df.iloc[:, :_PV_TABLE_COLS]
                df = df.fillna('')
                headers = [str(c) for c in df.columns.tolist()]
                rows    = [list(r) for r in df.values.tolist()]

                try:
                    if e == 'csv':
                        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                            total_rows = sum(1 for _ in fh) - 1
                    else:
                        import openpyxl as _xl
                        wb = _xl.load_workbook(path, read_only=True, data_only=True)
                        ws = wb.active
                        total_rows = (ws.max_row or 1) - 1
                        wb.close()
                except Exception:
                    total_rows = len(rows)

                return jsonify({
                    'headers': headers, 'rows': rows,
                    'total_rows': max(total_rows, len(rows)),
                    'total_cols': total_cols,
                    'truncated': total_rows > _PV_TABLE_ROWS,
                    'truncated_cols': total_cols > _PV_TABLE_COLS,
                })
            except Exception as ex:
                return jsonify({'error': f'Cannot parse: {ex}'}), 500

        # ── Word / DOCX ───────────────────────────────────────
        if e in _PV_WORD:
            paras, total, truncated = _read_docx(path)
            if total == 0:
                return jsonify({'paragraphs': [], 'total': 0,
                                'truncated': False, 'empty': True})
            return jsonify({'paragraphs': paras, 'total': total, 'truncated': truncated})

        # ── Archives ──────────────────────────────────────────
        if e in _PV_ARCH or rec.filename.endswith(('.tar.gz', '.tar.bz2')):
            entries, total = [], 0
            try:
                if e == 'zip':
                    import zipfile as _zf
                    with _zf.ZipFile(path, 'r') as zf:
                        infos = sorted(zf.infolist(), key=lambda i: i.filename)
                        total = len(infos)
                        entries = [
                            {'name': i.filename, 'size': i.file_size,
                             'is_dir': i.filename.endswith('/')}
                            for i in infos[:_PV_ARCH_LIMIT]
                        ]
                else:
                    import tarfile as _tf
                    with _tf.open(path, 'r:*') as tf:
                        members = sorted(tf.getmembers(), key=lambda m: m.name)
                        total   = len(members)
                        entries = [
                            {'name': m.name, 'size': m.size, 'is_dir': m.isdir()}
                            for m in members[:_PV_ARCH_LIMIT]
                        ]
                return jsonify({'entries': entries, 'total': total,
                                'truncated': total > _PV_ARCH_LIMIT})
            except Exception as ex:
                return jsonify({'error': f'Cannot read archive: {ex}'}), 500

        # ── Text / Code ───────────────────────────────────────
        if e in _PV_TEXT:
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                    content = fh.read(_PV_TEXT_LIMIT)
                return jsonify({
                    'content':   content,
                    'lang':      _PV_LANG.get(e, 'text'),
                    'lines':     content.count('\n') + 1,
                    'truncated': rec.size > _PV_TEXT_LIMIT,
                })
            except Exception as ex:
                return jsonify({'error': f'Cannot read: {ex}'}), 500

        # ── Fallback: спробуємо як UTF-8 ─────────────────────
        try:
            with open(path, 'rb') as fh:
                fh.read(512).decode('utf-8')
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                content = fh.read(_PV_TEXT_LIMIT)
            return jsonify({'content': content, 'lang': 'text',
                            'lines': content.count('\n') + 1,
                            'truncated': rec.size > _PV_TEXT_LIMIT})
        except Exception:
            pass

        return jsonify({'kind': 'none'}), 415

    finally:
        # Завжди видаляємо тимчасовий файл
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ═══════════════════════════════════════════════════════════════
# SMART ALERTS
# ═══════════════════════════════════════════════════════════════

def _alert_fmt_size(b: int) -> str:
    for u in ['B','KB','MB','GB']:
        if b < 1024: return f'{b:.1f} {u}'
        b /= 1024
    return f'{b:.1f} TB'


@app.route('/api/alerts', methods=['GET'])
@login_required
@permission_required('analytics:read')
def get_alerts():
    """
    Аналізує колекцію і повертає список Smart Alerts.
    Кожен alert: { id, severity, icon, title, description,
                   recommendation, count, file_ids }
    """
    from collections import Counter as _Ctr
    files = data_manager.files
    total = len(files)
    if total == 0:
        return jsonify([])

    now    = datetime.now()
    alerts = []

    # 1 ── Файли без тегів ─────────────────────────────────────────
    no_tags = [f for f in files if not f.tags]
    if no_tags:
        alerts.append({
            'id': 'no_tags', 'severity': 'warning', 'icon': '🏷️',
            'title': 'Файли без тегів',
            'description': (f'{len(no_tags)} файл(ів) не мають жодного тегу — '
                            'AI не зміг їх розпізнати або теги були видалені.'),
            'recommendation': 'Додайте 2–4 описових теги вручну для кращої організації та пошуку.',
            'count': len(no_tags),
            'file_ids': [f.file_id for f in no_tags[:50]],
        })

    # 2 ── Файли старші 180 днів ───────────────────────────────────
    old = [f for f in files if (now - f.upload_date).days >= 180]
    if old:
        oldest = max((now - f.upload_date).days for f in old)
        alerts.append({
            'id': 'old_files', 'severity': 'info', 'icon': '🕰️',
            'title': 'Старі файли (6+ місяців)',
            'description': (f'{len(old)} файл(ів) зберігаються понад 180 днів. '
                            f'Найстаріший — {oldest} днів.'),
            'recommendation': 'Перегляньте: видаліть застарілі або перемістіть в архів.',
            'count': len(old),
            'file_ids': [f.file_id for f in sorted(old, key=lambda f: f.upload_date)[:50]],
        })

    # 3 ── Забагато підкатегорії "general" ────────────────────────
    gen   = [f for f in files if f.subcategory == 'general']
    g_pct = len(gen) / total * 100
    if g_pct >= 35:
        alerts.append({
            'id': 'too_many_general', 'severity': 'warning', 'icon': '📂',
            'title': 'Забагато файлів у "General"',
            'description': (f'{len(gen)} файл(ів) ({g_pct:.0f}%) мають підкатегорію "general" — '
                            'класифікація недостатньо точна.'),
            'recommendation': 'Додайте специфічні теги або вручну перемістіть у відповідні підкатегорії.',
            'count': len(gen),
            'file_ids': [f.file_id for f in gen[:50]],
        })

    # 4 ── Низька впевненість AI (<50%) ────────────────────────────
    low_c = [f for f in files if f.confidence < 0.5]
    if low_c:
        avg_c = sum(f.confidence for f in low_c) / len(low_c)
        alerts.append({
            'id': 'low_confidence', 'severity': 'warning', 'icon': '🤖',
            'title': 'Низька впевненість AI',
            'description': (f'{len(low_c)} файл(ів) класифіковані з впевненістю < 50% '
                            f'(середня: {avg_c*100:.0f}%).'),
            'recommendation': 'Перевірте класифікацію та за потреби виправте категорію вручну.',
            'count': len(low_c),
            'file_ids': [f.file_id for f in sorted(low_c, key=lambda f: f.confidence)[:50]],
        })

    # 5 ── Дублікати імен ──────────────────────────────────────────
    name_cnt  = _Ctr(f.filename.lower() for f in files)
    dup_names = {n for n, c in name_cnt.items() if c > 1}
    dups      = [f for f in files if f.filename.lower() in dup_names]
    if dups:
        alerts.append({
            'id': 'duplicates', 'severity': 'error', 'icon': '⚠️',
            'title': 'Дублікати файлів',
            'description': (f'{len(dup_names)} імен зустрічаються більше одного разу '
                            f'({len(dups)} файлів загалом).'),
            'recommendation': 'Перегляньте дублікати й видаліть зайві копії, щоб звільнити місце.',
            'count': len(dups),
            'file_ids': [f.file_id for f in dups[:50]],
        })

    # 6 ── Великі файли (>50 MB) без тегів ────────────────────────
    big_nt = [f for f in files if f.size > 50 * 1024 * 1024 and not f.tags]
    if big_nt:
        sz_total = sum(f.size for f in big_nt)
        alerts.append({
            'id': 'big_no_tags', 'severity': 'warning', 'icon': '💾',
            'title': 'Великі файли без тегів',
            'description': (f'{len(big_nt)} файл(ів) > 50 MB не мають тегів '
                            f'і займають {_alert_fmt_size(sz_total)}.'),
            'recommendation': 'Великі файли особливо важливо правильно класифікувати.',
            'count': len(big_nt),
            'file_ids': [f.file_id for f in sorted(big_nt, key=lambda f: -f.size)[:50]],
        })

    # 7 ── Засмічена категорія "other" (>20%) ─────────────────────
    oth   = [f for f in files if f.category == 'other']
    o_pct = len(oth) / total * 100
    if o_pct >= 20:
        alerts.append({
            'id': 'too_many_other', 'severity': 'info', 'icon': '📌',
            'title': 'Багато файлів у категорії "Other"',
            'description': f'{len(oth)} файл(ів) ({o_pct:.0f}%) у категорії "Other".',
            'recommendation': 'Перегляньте ці файли та перемістіть у відповідні категорії через Edit → Move.',
            'count': len(oth),
            'file_ids': [f.file_id for f in oth[:50]],
        })

    # 8 ── Файли лише з одним тегом ───────────────────────────────
    one_tag = [f for f in files if len(f.tags) == 1]
    if len(one_tag) >= max(3, int(total * 0.15)):
        alerts.append({
            'id': 'single_tag', 'severity': 'info', 'icon': '🔖',
            'title': 'Файли лише з одним тегом',
            'description': f'{len(one_tag)} файл(ів) мають лише один тег — цього недостатньо для точного пошуку.',
            'recommendation': 'Додайте 2–4 описових теги до кожного файлу.',
            'count': len(one_tag),
            'file_ids': [f.file_id for f in one_tag[:50]],
        })

    # 9 ── Домінуюча категорія (>65%, мінімум 10 файлів) ──────────
    cat_cnt = _Ctr(f.category for f in files)
    top_cat, top_cnt = cat_cnt.most_common(1)[0]
    top_pct = top_cnt / total * 100
    if top_pct >= 65 and total >= 10:
        alerts.append({
            'id': 'dominant_category', 'severity': 'info', 'icon': '⚖️',
            'title': f'Домінуюча категорія "{top_cat}"',
            'description': f'Категорія "{top_cat}" містить {top_cnt} файл(ів) ({top_pct:.0f}% колекції).',
            'recommendation': 'Розгляньте створення підкатегорій через Manage → Categories & Subcategories.',
            'count': top_cnt,
            'file_ids': [f.file_id for f in files if f.category == top_cat][:50],
        })

    # 10 ── Файли без розширення ───────────────────────────────────
    no_ext = [f for f in files if '.' not in f.filename or f.filename.startswith('.')]
    if no_ext:
        alerts.append({
            'id': 'no_extension', 'severity': 'info', 'icon': '❓',
            'title': 'Файли без розширення',
            'description': f'{len(no_ext)} файл(ів) не мають розширення — AI може помилитися з класифікацією.',
            'recommendation': 'Перейменуйте з коректним розширенням або вкажіть категорію вручну.',
            'count': len(no_ext),
            'file_ids': [f.file_id for f in no_ext[:50]],
        })

    # Сортуємо: error → warning → info
    sev_order = {'error': 0, 'warning': 1, 'info': 2}
    alerts.sort(key=lambda a: sev_order.get(a['severity'], 9))
    return jsonify(alerts)


# ═══════════════════════════════════════════════════════════════
# ROLE REQUESTS
# ═══════════════════════════════════════════════════════════════

# In-memory store for role requests (in production — move to DB table)
_role_requests: list[dict] = []

@app.route('/api/role-request', methods=['POST'])
@login_required
def submit_role_request():
    """Viewer надсилає запит на отримання вищої ролі."""
    user = get_current_user()
    data = request.get_json() or {}
    requested_role = data.get('role', 'editor')
    message = data.get('message', '').strip()[:500]

    if requested_role not in ('editor', 'admin'):
        return jsonify({'error': 'Invalid role requested'}), 400

    # Перевіряємо чи вже є pending запит від цього юзера
    existing = next((r for r in _role_requests
                     if r['user_id'] == user.id and r['status'] == 'pending'), None)
    if existing:
        return jsonify({'error': 'You already have a pending request'}), 409

    import time
    _role_requests.append({
        'id': int(time.time() * 1000),
        'user_id': user.id,
        'username': user.username,
        'display_name': user.display_name,
        'email': user.email,
        'current_role': user.role,
        'requested_role': requested_role,
        'message': message,
        'status': 'pending',
        'created_at': datetime.utcnow().isoformat(),
    })
    return jsonify({'success': True})


@app.route('/api/role-request/my', methods=['GET'])
@login_required
def get_my_role_request():
    """Повертає останній запит юзера (будь-якого статусу)."""
    user = get_current_user()
    # Знаходимо pending спочатку, потім останній будь-який
    req = next((r for r in _role_requests
                if r['user_id'] == user.id and r['status'] == 'pending'), None)
    if not req:
        # Знаходимо останній оброблений запит
        user_reqs = [r for r in _role_requests if r['user_id'] == user.id]
        req = user_reqs[-1] if user_reqs else None
    return jsonify({'request': req})


@app.route('/api/admin/verify-password', methods=['POST'])
@login_required
@admin_required
def admin_verify_password():
    """
    Перевіряє пароль поточного адміна для підтвердження чутливих дій.
    Повертає {'valid': true/false}.
    Невдала спроба записується в audit_log як 'admin.verify_failed'.
    """
    data = request.get_json() or {}
    password = data.get('password', '')
    user = get_current_user()

    if not password:
        return jsonify({'valid': False, 'error': 'Password required'}), 400

    # Намагаємось знайти bcrypt в різних місцях проекту
    valid = False
    try:
        from auth import bcrypt as _bc
        valid = _bc.check_password_hash(user.password_hash, password)
    except Exception:
        try:
            from flask_bcrypt import Bcrypt as _Bcrypt
            _tmp = _Bcrypt()
            valid = _tmp.check_password_hash(user.password_hash, password)
        except Exception:
            return jsonify({'valid': False, 'error': 'Verification service unavailable'}), 500

    if not valid:
        write_audit('admin.verify_failed', 'user', str(user.id), {
            'ip': request.remote_addr,
            'note': 'Wrong password on sensitive action confirmation',
        })

    return jsonify({'valid': valid})


@app.route('/api/admin/users/<int:uid>/profile', methods=['GET'])
@login_required
@admin_required
def admin_get_user_profile(uid):
    """Повертає повний профіль користувача для адміна."""
    from auth.models import User
    user = User.query.get(uid)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(user.to_dict(include_sensitive=True))


@app.route('/api/admin/role-requests/bulk', methods=['PATCH'])
@login_required
@admin_required
def bulk_handle_role_requests():
    """Масове схвалення/відхилення запитів на роль."""
    from auth.models import db, User
    data = request.get_json() or {}
    action  = data.get('action')   # 'approve' | 'reject'
    req_ids = data.get('ids', [])  # список int id

    if action not in ('approve', 'reject'):
        return jsonify({'error': 'Invalid action'}), 400

    updated = 0
    for req_id in req_ids:
        req = next((r for r in _role_requests if r['id'] == int(req_id)), None)
        if not req or req['status'] != 'pending':
            continue
        req['status'] = 'approved' if action == 'approve' else 'rejected'
        if action == 'approve':
            user = User.query.get(req['user_id'])
            if user:
                user.role = req['requested_role']
        updated += 1

    if updated:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    return jsonify({'updated': updated})


@app.route('/api/admin/role-requests', methods=['GET'])
@login_required
@admin_required
def get_role_requests():
    """Адмін отримує список pending запитів."""
    pending = [r for r in _role_requests if r['status'] == 'pending']
    return jsonify({'requests': pending, 'total': len(pending)})


@app.route('/api/admin/role-requests/<int:req_id>', methods=['PATCH'])
@login_required
@admin_required
def handle_role_request(req_id):
    """Адмін схвалює або відхиляє запит."""
    from auth.models import db, User
    data = request.get_json() or {}
    action = data.get('action')  # 'approve' | 'reject'

    req = next((r for r in _role_requests if r['id'] == req_id), None)
    if not req:
        return jsonify({'error': 'Request not found'}), 404

    req['status'] = 'approved' if action == 'approve' else 'rejected'

    if action == 'approve':
        user = User.query.get(req['user_id'])
        if user:
            old_role = user.role
            user.role = req['requested_role']
            db.session.commit()
            write_audit('admin.role_change', 'user', str(req['user_id']), {
                'username': req['username'],
                'old_role': old_role,
                'new_role': req['requested_role'],
                'via': 'role_request',
            })

    return jsonify({'success': True})


# ═══════════════════════════════════════════════════════════════
# ANALYTICS REPORT DOWNLOAD (admin)
# ═══════════════════════════════════════════════════════════════

@app.route('/api/admin/analytics-report', methods=['GET'])
@login_required
@admin_required
def download_analytics_report():
    """Завантажує CSV-звіт аналітики файлів (аналог вкладки Analytics)."""
    import io
    import csv as _csv

    analytics = data_manager.get_analytics()
    output = io.StringIO()
    w = _csv.writer(output)

    w.writerow(['CYBER DATA NEXUS — Analytics Report'])
    w.writerow(['Generated', datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')])
    w.writerow([])

    w.writerow(['=== OVERVIEW ==='])
    w.writerow(['Total Files', analytics['total_files']])
    total_size = analytics['total_size']
    size_str = (f"{total_size/1e9:.2f} GB" if total_size > 1e9
                else f"{total_size/1e6:.1f} MB" if total_size > 1e6
                else f"{total_size/1024:.0f} KB")
    w.writerow(['Total Size', size_str])
    w.writerow(['High Confidence %', f"{analytics['high_confidence_pct']}%"])
    w.writerow(['Avg Tags per File', analytics['avg_tags_per_file']])
    w.writerow([])

    w.writerow(['=== CATEGORIES DISTRIBUTION ==='])
    w.writerow(['Category', 'Count', 'Percent'])
    for c in analytics['categories_dist']:
        w.writerow([c['category'], c['count'], f"{c['pct']}%"])
    w.writerow([])

    w.writerow(['=== TOP TAGS ==='])
    w.writerow(['Tag', 'Count'])
    for t in analytics['top_tags']:
        w.writerow([t['tag'], t['count']])
    w.writerow([])

    w.writerow(['=== TOP FILE EXTENSIONS ==='])
    w.writerow(['Extension', 'Count'])
    for e in analytics['top_extensions']:
        w.writerow([e['ext'], e['count']])
    w.writerow([])

    w.writerow(['=== UPLOADS BY MONTH ==='])
    w.writerow(['Month', 'Count'])
    for m in analytics['uploads_by_month']:
        w.writerow([m['month'], m['count']])
    w.writerow([])

    w.writerow(['=== SIZE BY CATEGORY ==='])
    w.writerow(['Category', 'Total Size (bytes)', 'Avg Size (bytes)'])
    for s in analytics['size_by_category']:
        w.writerow([s['category'], s['total_size'], s['avg_size']])
    w.writerow([])

    w.writerow(['=== AI CONFIDENCE DISTRIBUTION ==='])
    w.writerow(['Range', 'Count', 'Percent'])
    for b in analytics['confidence_dist']:
        w.writerow([b['range'], b['count'], f"{b['pct']}%"])

    output.seek(0)
    from flask import Response
    filename = f"nexus-analytics-{datetime.utcnow().strftime('%Y%m%d-%H%M')}.csv"
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )




# ═══════════════════════════════════════════════════════════════
# R2 HEALTH CHECK + MIGRATION UTILITY
# ═══════════════════════════════════════════════════════════════

@app.route('/api/admin/storage/health', methods=['GET'])
@login_required
@admin_required
def r2_health():
    """Перевіряє доступність bucket хмарного сховища."""
    try:
        _s3_client.head_bucket(Bucket=_STORAGE_BUCKET)
        return jsonify({
            'ok':       True,
            'provider': _STORAGE_PROVIDER,
            'bucket':   _STORAGE_BUCKET,
            'endpoint': _STORAGE_ENDPOINT,
        })
    except ClientError as e:
        return jsonify({'ok': False, 'error': str(e)}), 503


@app.route('/api/admin/storage/migrate', methods=['POST'])
@login_required
@admin_required
def migrate_local_to_r2():
    """
    Міграційний ендпоінт: переносить файли зі старої локальної папки uploads/ в R2.

    Читає дані зі старого data.json (якщо існує), завантажує кожен файл в R2
    і записує метадані в Supabase.

    Запускати ОДИН РАЗ після деплою. Безпечний для повторного запуску —
    пропускає файли що вже мають storage_key.

    POST /api/admin/r2/migrate
    Body (optional): { "dry_run": true }  — лише перевірка без запису
    """
    data_req  = request.get_json() or {}
    dry_run   = data_req.get('dry_run', False)
    user      = get_current_user()

    old_data_file  = _app_cfg.get('data_file', 'data.json')
    old_upload_dir = _app_cfg.get('upload_folder', 'uploads')

    if not os.path.exists(old_data_file):
        return jsonify({'error': f'Old data file not found: {old_data_file}'}), 404

    try:
        with open(old_data_file, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        old_files = raw if isinstance(raw, list) else raw.get('files', [])
    except Exception as e:
        return jsonify({'error': f'Cannot read data file: {e}'}), 500

    migrated, skipped, failed = 0, 0, []

    for item in old_files:
        filename    = item.get('filename', '')
        old_fid     = item.get('file_id', '')
        old_filepath= item.get('filepath', os.path.join(old_upload_dir, filename))

        # Пропускаємо якщо вже є в кеші з storage_key
        existing = data_manager.get_file_by_id(old_fid)
        if existing and existing.storage_key:
            skipped += 1
            continue

        if not os.path.exists(old_filepath):
            failed.append({'file': filename, 'reason': 'not found on disk'})
            continue

        if dry_run:
            migrated += 1
            continue

        try:
            # Будуємо FileRecord з наявних метаданих (без повторного AI)
            rec = FileRecord.from_dict({
                **item,
                'original_filename': item.get('original_filename', filename),
                'mimetype': item.get('mimetype', 'application/octet-stream'),
                'storage_key': '',  # буде заповнено нижче
            })
            rec.storage_key = R2Storage.build_key(rec.filename, rec.file_id)

            # Завантажуємо файл в B2/R2
            from urllib.parse import quote as _url_quote
            with open(old_filepath, 'rb') as fh:
                ok = storage.upload(                    file_obj     = fh,
                    key          = rec.storage_key,
                    content_type = rec.mimetype,
                    extra_meta   = {
                        'migrated-from':     'local',
                        'original-id':       old_fid,
                        'original-filename': _url_quote(rec.original_filename, safe='._- '),
                    },
                )
            if not ok:
                failed.append({'file': filename, 'reason': 'R2 upload failed'})
                continue

            # Зберігаємо метадані в Supabase
            data_manager._save_record(rec, user_id=user.id if user else None)

            # Оновлюємо кеш
            if not existing:
                data_manager.files.append(rec)
            else:
                existing.storage_key = rec.storage_key

            write_audit('storage.migrate', 'file', rec.file_id, {
                'filename': filename, 'storage_key': rec.storage_key
            })
            migrated += 1

        except Exception as e:
            failed.append({'file': filename, 'reason': str(e)})

    return jsonify({
        'dry_run':  dry_run,
        'provider': _STORAGE_PROVIDER,
        'bucket':   _STORAGE_BUCKET,
        'total':    len(old_files),
        'migrated': migrated,
        'skipped':  skipped,
        'failed':   len(failed),
        'errors':   failed[:20],
    })


# Entry point
if __name__ == '__main__':
    app.run(
        debug=_app_cfg['debug'],
        host=_app_cfg['host'],
        port=_app_cfg['port'],
    )