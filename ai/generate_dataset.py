"""
generate_dataset.py — генерація навчального датасету.

Вся конфігурація (категорії, розширення, токени, теги тощо)
читається з config.yaml через config_loader.
Тут немає жодного хардкоду.
"""

import json
import random
from pathlib import Path

from config_loader import (
    get_extension_map,
    get_tag_rules,
    get_token_pools,
    get_generic_tokens,
    get_confusion_names,
    get_generic_tags,
    get_dataset_cfg,
)

BASE_DIR = Path(__file__).parent

# ── Завантаження конфігурації ──────────────────────────────────
dcfg = get_dataset_cfg()

TOTAL_SAMPLES: int = dcfg["total_samples"]
TRAIN_RATIO: float = dcfg["train_ratio"]

EXTENSION_TO_CATEGORY: dict[str, str] = get_extension_map()
EXTENSIONS: list[str] = list(EXTENSION_TO_CATEGORY.keys())

TOKEN_POOLS: list[list[str]] = list(get_token_pools().values())
GENERIC_TOKENS: list[str] = get_generic_tokens()
CONFUSION_NAMES: list[str] = get_confusion_names()
GENERIC_TAGS: list[str] = get_generic_tags()
TAG_RULES: dict[str, list[str]] = get_tag_rules()


# ── Утиліти ────────────────────────────────────────────────────

def random_separator() -> str:
    return random.choice(["_", "-", " "])


def typo(word: str) -> str:
    """Вносить опечатку з заданою ймовірністю (перестановка двох символів)."""
    prob = dcfg["typo_probability"]
    if len(word) < 4 or random.random() > prob:
        return word
    i = random.randint(0, len(word) - 2)
    return word[:i] + word[i + 1] + word[i] + word[i + 2:]


# ── Генерація імені файлу ──────────────────────────────────────

def generate_filename(ext: str) -> str:
    tokens = []

    if random.random() < dcfg["confusion_probability"]:
        tokens.append(random.choice(CONFUSION_NAMES))
    else:
        domain = random.choice(TOKEN_POOLS)
        tokens.append(random.choice(domain))

        if random.random() < dcfg["extra_token_probability"]:
            tokens.append(random.choice(random.choice(TOKEN_POOLS)))

    if random.random() < dcfg["generic_token_probability"]:
        tokens.append(random.choice(GENERIC_TOKENS))

    if random.random() < dcfg["year_probability"]:
        tokens.append(str(random.randint(2017, 2024)))

    tokens = [typo(t) for t in tokens]
    name = random_separator().join(tokens)

    if random.random() < dcfg["no_extension_probability"]:
        return name

    return f"{name}.{ext}"


# ── Вилучення тегів ────────────────────────────────────────────

def extract_tags(filename: str, category: str) -> set[str]:
    tags: set[str] = set()
    name = filename.lower()

    for token, mapped in TAG_RULES.items():
        if token in name:
            tags.update(mapped)

    # категорія як тег (з невеликою ймовірністю пропускається)
    if random.random() > dcfg["category_tag_skip_probability"]:
        tags.add(category)

    # загальний тег
    if random.random() < dcfg["generic_tag_probability"]:
        tags.add(random.choice(GENERIC_TAGS))

    # шум: прибрати випадковий тег
    if tags and random.random() < dcfg["noise_remove_tag_probability"]:
        tags.remove(random.choice(list(tags)))

    # шум: додати неправильний тег
    if random.random() < dcfg["noise_add_wrong_tag_probability"]:
        tags.add(random.choice(GENERIC_TAGS))

    return tags


# ── Генерація одного семплу ────────────────────────────────────

def generate_sample() -> dict:
    ext = random.choice(EXTENSIONS)
    filename = generate_filename(ext)
    category = EXTENSION_TO_CATEGORY[ext]
    tags = extract_tags(filename, category)

    return {
        "text": filename,
        "category": category,
        "tags": sorted(tags),
    }


# ── Генерація датасету ─────────────────────────────────────────

def generate_dataset(output_dir: Path = BASE_DIR) -> None:
    data = [generate_sample() for _ in range(TOTAL_SAMPLES)]
    random.shuffle(data)

    split = int(TOTAL_SAMPLES * TRAIN_RATIO)

    train_path = output_dir / "train.jsonl"
    val_path = output_dir / "val.jsonl"

    with open(train_path, "w", encoding="utf-8") as f:
        for x in data[:split]:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")

    with open(val_path, "w", encoding="utf-8") as f:
        for x in data[split:]:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")

    print("✅ Dataset generated successfully")
    print(f"   Train : {split:,} samples → {train_path}")
    print(f"   Val   : {TOTAL_SAMPLES - split:,} samples → {val_path}")
    print(f"   Categories : {sorted(set(EXTENSION_TO_CATEGORY.values()))}")
    print(f"   Extensions : {len(EXTENSIONS)}")


if __name__ == "__main__":
    generate_dataset()
