"""
config_loader.py — утиліта для завантаження конфігурації.

Всі модулі імпортують звідси замість прямого читання YAML.
Використання:
    from config_loader import cfg, get_extension_map, get_subcategory_rules
"""

from pathlib import Path
import yaml

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load() -> dict:
    """Завантажує та повертає конфіг як словник."""
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Singleton ──────────────────────────────────────────────────
# Конфіг завантажується один раз при першому імпорті модуля
cfg: dict = _load()


# ── Зручні геттери ─────────────────────────────────────────────

def get_extension_map() -> dict[str, str]:
    """
    Повертає словник {розширення → категорія}.
    Перетворює зворотну структуру конфігу (категорія → [розширення]).
    """
    result = {}
    for category, extensions in cfg["extension_map"].items():
        for ext in extensions:
            result[ext.lower()] = category
    return result


def get_all_extensions() -> list[str]:
    """Список всіх відомих розширень файлів."""
    return list(get_extension_map().keys())


def get_all_categories() -> list[str]:
    """Список всіх категорій."""
    return list(cfg["extension_map"].keys())


def get_subcategory_rules() -> dict[str, dict[str, set[str]]]:
    """
    Повертає правила підкатегорій у форматі:
    { category: { subcategory: {keyword, ...} } }
    Ключові слова конвертуються в set для O(1) пошуку.
    """
    rules = {}
    for category, subcats in cfg["subcategory_rules"].items():
        rules[category] = {
            subcat: set(keywords)
            for subcat, keywords in subcats.items()
        }
    return rules


def get_tag_rules() -> dict[str, list[str]]:
    """Маппінг токен → теги для генерації датасету."""
    return cfg["tag_rules"]


def get_token_pools() -> dict[str, list[str]]:
    """Домени токенів для генерації імен файлів."""
    return cfg["token_pools"]


def get_generic_tokens() -> list[str]:
    return cfg["generic_tokens"]


def get_confusion_names() -> list[str]:
    return cfg["confusion_names"]


def get_generic_tags() -> list[str]:
    return cfg["generic_tags"]


def get_dataset_cfg() -> dict:
    return cfg["dataset"]


def get_model_cfg() -> dict:
    return cfg["model"]


def get_app_cfg() -> dict:
    """Flask-конфігурація (upload_folder, data_file, port тощо)."""
    return cfg["app"]


def get_extension_to_base_category() -> dict[str, str]:
    """
    Маппінг розширення → базова категорія.
    Використовується в FileRecord як найвищий пріоритет класифікації —
    перекриває AI-результат для форматів без власної базової категорії
    (xlsx→document, pptx→video тощо).
    """
    return {ext.lower(): cat for ext, cat in cfg["extension_to_base_category"].items()}


def get_base_categories() -> list[dict]:
    """
    Повертає список базових (системних) категорій.
    Кожен елемент: {'id': str, 'label': str, 'emoji': str, 'builtin': bool}
    """
    return cfg["base_categories"]


def get_base_category_ids() -> set[str]:
    """Множина id базових категорій для швидкої перевірки."""
    return {c["id"] for c in cfg["base_categories"]}


def get_tag_to_category() -> dict[str, str]:
    """Маппінг тег → категорія для infer_categories_from_tags()."""
    return cfg["tag_to_category"]


def get_tag_synonyms() -> dict[str, str]:
    """Маппінг синонім_тегу → канонічна_форма для normalize_tag()."""
    return cfg["tag_synonyms"]


def get_transliteration_map() -> dict[str, str]:
    """Таблиця транслітерації кирилиця → латиниця."""
    return {k: (v or "") for k, v in cfg["transliteration"].items()}


def get_system_subcategory_names() -> set[str]:
    """
    Повертає всі назви системних підкатегорій з усіх категорій.
    Використовується у DataManager.load_data() для фільтрації артефактів.
    """
    names: set[str] = {"general"}
    for subcats in cfg["subcategory_rules"].values():
        names.update(subcats.keys())
    return names


def reload() -> None:
    """
    Перезавантажує конфіг з диска (корисно в тестах або
    якщо config.yaml змінився під час роботи процесу).
    """
    global cfg
    cfg = _load()
