"""
inference.py — інференс-модуль класифікатора файлів.

SUBCATEGORY_RULES та всі параметри читаються з config.yaml.
Тут немає жодного хардкоду.
"""

import joblib
import numpy as np
from pathlib import Path
import sys

from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent       # .../ai/
PROJECT_ROOT = BASE_DIR.parent                    # .../project_root/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config_loader import get_subcategory_rules, get_model_cfg

MODEL_DIR = BASE_DIR / "model"


# ── Підкатегорії ───────────────────────────────────────────────
# Завантажуються з конфігу один раз при старті модуля.
# Формат: { category: { subcategory: {keyword, ...} } }
SUBCATEGORY_RULES: dict[str, dict[str, set[str]]] = get_subcategory_rules()

# ── Параметри inference ────────────────────────────────────────
_mcfg = get_model_cfg()
DEFAULT_TAG_THRESHOLD: float = _mcfg["tag_threshold"]


# ── Функції для підкатегорій ───────────────────────────────────

def resolve_subcategory(category: str, tags: list[str]) -> str:
    """
    Визначає підкатегорію на основі тегів.
    Підтримує синоніми та кириличні теги.

    ВАЖЛИВО: Повертає ПЕРШУ знайдену підкатегорію.
    Для файлів з кількома підкатегоріями використовуйте
    resolve_all_subcategories().
    """
    rules = SUBCATEGORY_RULES.get(category, {})
    tag_set = {tag.lower().strip() for tag in tags}

    for subcat, keywords in rules.items():
        if tag_set & keywords:
            return subcat

    return "general"


def resolve_all_subcategories(category: str, tags: list[str]) -> list[str]:
    """
    Визначає ВСІ підкатегорії на основі тегів.
    Для файлів які можуть належати до кількох підкатегорій.
    Наприклад: audit + spreadsheet → ["audit", "tables"]
    """
    rules = SUBCATEGORY_RULES.get(category, {})
    tag_set = {tag.lower().strip() for tag in tags}

    matched = [
        subcat
        for subcat, keywords in rules.items()
        if tag_set & keywords
    ]

    return matched if matched else ["general"]


# ── Класифікатор ───────────────────────────────────────────────

class SemanticFileClassifier:
    """Inference-only AI класифікатор файлів."""

    def __init__(self) -> None:
        self.encoder = SentenceTransformer(str(MODEL_DIR / "encoder"))
        self.category_model = joblib.load(MODEL_DIR / "category_model.pkl")
        self.tag_model = joblib.load(MODEL_DIR / "tag_model.pkl")
        self.mlb = joblib.load(MODEL_DIR / "tag_binarizer.pkl")

    def classify(
        self,
        filename: str,
        tag_threshold: float = DEFAULT_TAG_THRESHOLD,
    ) -> dict:
        """
        Класифікує файл за назвою.

        Args:
            filename: ім'я файлу (тільки ім'я, без повного шляху)
            tag_threshold: мінімальна впевненість для включення тегу

        Returns:
            {
                "categories": [str],   # передбачена категорія
                "tags": [str],         # список тегів
                "confidence": float    # впевненість для категорії
            }
        """
        emb = self.encoder.encode([filename])

        # ── Категорія ──
        category: str = self.category_model.predict(emb)[0]
        confidence: float = float(np.max(self.category_model.predict_proba(emb)))

        # ── Теги ──
        tag_probs = self.tag_model.predict_proba(emb)[0]
        tags: list[str] = [
            self.mlb.classes_[i]
            for i, p in enumerate(tag_probs)
            if p >= tag_threshold
        ]

        # fallback: якщо жоден тег не перевищив поріг
        if not tags:
            tags = [category]

        return {
            "categories": [category],
            "tags": tags,
            "confidence": confidence,
        }
