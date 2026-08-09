"""
semantic_model.py — навчання моделі класифікатора файлів.

Всі гіперпараметри, назва енкодера, розміри батчу тощо
читаються з config.yaml через config_loader.
Тут немає жодного хардкоду.
"""

import json
import joblib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path

from sentence_transformers import SentenceTransformer
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.metrics import accuracy_score, f1_score, hamming_loss
from sklearn.model_selection import GridSearchCV

from config_loader import get_model_cfg

# ── Шляхи ─────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATASET_DIR = BASE_DIR
MODEL_DIR = BASE_DIR / "model"
MODEL_DIR.mkdir(exist_ok=True)

# ── Конфігурація ───────────────────────────────────────────────
mcfg = get_model_cfg()

ENCODER_NAME: str = mcfg["encoder_name"]
BATCH_SIZE: int = mcfg["batch_size"]

CAT_GRID_PARAMS: dict = {
    k: v for k, v in mcfg["category_grid"].items()
    if k != "max_iter"
}
CAT_MAX_ITER: int = mcfg["category_grid"]["max_iter"]

TAG_GRID_PARAMS: dict = {
    k: v for k, v in mcfg["tag_grid"].items()
    if k != "max_iter"
}
TAG_MAX_ITER: int = mcfg["tag_grid"]["max_iter"]


# ── Завантаження даних ─────────────────────────────────────────

def load_jsonl(path: Path) -> tuple[list, list, list]:
    texts, categories, tags = [], [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            texts.append(item["text"])
            categories.append(item["category"])
            tags.append(item["tags"])
    return texts, categories, tags


print("📥 Loading dataset...")
X_train_text, y_train_cat, y_train_tags = load_jsonl(DATASET_DIR / "train.jsonl")
X_val_text, y_val_cat, y_val_tags = load_jsonl(DATASET_DIR / "val.jsonl")

# ── Кодування ──────────────────────────────────────────────────

print(f"🔄 Loading encoder: {ENCODER_NAME!r}...")
encoder = SentenceTransformer(ENCODER_NAME)

X_train = encoder.encode(X_train_text, batch_size=BATCH_SIZE, show_progress_bar=True)
X_val = encoder.encode(X_val_text, batch_size=BATCH_SIZE, show_progress_bar=True)

# ── Класифікатор категорій ─────────────────────────────────────

print("\n🎯 CATEGORY CLASSIFICATION")

baseline_cat = LogisticRegression(max_iter=CAT_MAX_ITER)
baseline_cat.fit(X_train, y_train_cat)
y_pred_cat = baseline_cat.predict(X_val)

print("Baseline Category Metrics:")
print("  Accuracy :", accuracy_score(y_val_cat, y_pred_cat))
print("  Macro F1 :", f1_score(y_val_cat, y_pred_cat, average="macro"))

cat_grid = GridSearchCV(
    LogisticRegression(max_iter=CAT_MAX_ITER),
    param_grid=CAT_GRID_PARAMS,
    scoring="f1_macro",
    cv=3,
    n_jobs=-1,
)
cat_grid.fit(X_train, y_train_cat)
best_cat_model = cat_grid.best_estimator_

y_pred_cat_best = best_cat_model.predict(X_val)
print("\nBest Category Model params:", cat_grid.best_params_)
print("Grid Category Metrics:")
print("  Accuracy :", accuracy_score(y_val_cat, y_pred_cat_best))
print("  Macro F1 :", f1_score(y_val_cat, y_pred_cat_best, average="macro"))

# ── Класифікатор тегів ─────────────────────────────────────────

print("\n🏷 TAG CLASSIFICATION")

mlb = MultiLabelBinarizer()
Y_train = mlb.fit_transform(y_train_tags)
Y_val = mlb.transform(y_val_tags)

baseline_tag = OneVsRestClassifier(LogisticRegression(max_iter=TAG_MAX_ITER))
baseline_tag.fit(X_train, Y_train)
Y_pred = baseline_tag.predict(X_val)

print("Baseline Tag Metrics:")
print("  Micro F1     :", f1_score(Y_val, Y_pred, average="micro"))
print("  Macro F1     :", f1_score(Y_val, Y_pred, average="macro"))
print("  Hamming Loss :", hamming_loss(Y_val, Y_pred))

tag_grid = GridSearchCV(
    OneVsRestClassifier(LogisticRegression(max_iter=TAG_MAX_ITER)),
    param_grid=TAG_GRID_PARAMS,
    scoring="f1_micro",
    cv=3,
    n_jobs=-1,
)
tag_grid.fit(X_train, Y_train)
best_tag_model = tag_grid.best_estimator_

Y_pred_best = best_tag_model.predict(X_val)
print("\nBest Tag Model params:", tag_grid.best_params_)
print("Grid Tag Metrics:")
print("  Micro F1     :", f1_score(Y_val, Y_pred_best, average="micro"))
print("  Macro F1     :", f1_score(Y_val, Y_pred_best, average="macro"))
print("  Hamming Loss :", hamming_loss(Y_val, Y_pred_best))


# ── Побудова графіків ──────────────────────────────────────────

print("\n📊 Building training metrics plots...")

# ── Збір метрик ───────────────────────────────────────────────

cat_acc_base = accuracy_score(y_val_cat, y_pred_cat)
cat_f1_base  = f1_score(y_val_cat, y_pred_cat,      average="macro")
cat_acc_best = accuracy_score(y_val_cat, y_pred_cat_best)
cat_f1_best  = f1_score(y_val_cat, y_pred_cat_best, average="macro")

tag_micro_base = f1_score(Y_val, Y_pred,      average="micro")
tag_macro_base = f1_score(Y_val, Y_pred,      average="macro")
tag_hl_base    = hamming_loss(Y_val, Y_pred)
tag_micro_best = f1_score(Y_val, Y_pred_best, average="micro")
tag_macro_best = f1_score(Y_val, Y_pred_best, average="macro")
tag_hl_best    = hamming_loss(Y_val, Y_pred_best)

# ── Кольори ───────────────────────────────────────────────────
BLUE_BASE = "#5B8DEF"
BLUE_BEST = "#1D4ED8"
RED_BASE  = "#F87171"
RED_BEST  = "#B91C1C"
GRAY_TEXT = "#374151"

fig = plt.figure(figsize=(14, 9))
fig.patch.set_facecolor("#F8FAFC")
fig.suptitle(
    "Результати навчання класифікаторів",
    fontsize=14, fontweight="bold", color=GRAY_TEXT, y=0.98,
)

w = 0.32

# ── Subplot 1: категорії ──────────────────────────────────────
ax1 = fig.add_subplot(2, 2, 1)
ax1.set_facecolor("white")
x = np.arange(2)
bars_b = ax1.bar(x - w/2, [cat_acc_base, cat_f1_base], w,
                 label="Baseline", color=BLUE_BASE, edgecolor="white")
bars_g = ax1.bar(x + w/2, [cat_acc_best, cat_f1_best], w,
                 label="Best (GridSearch)", color=BLUE_BEST, edgecolor="white")
for bar in (*bars_b, *bars_g):
    h = bar.get_height()
    ax1.text(bar.get_x() + bar.get_width()/2, h + 0.005,
             f"{h:.3f}", ha="center", va="bottom", fontsize=9, color=GRAY_TEXT)
ax1.set_title("Класифікатор категорій", fontsize=12, fontweight="bold",
              color=GRAY_TEXT, pad=8)
ax1.set_xticks(x)
ax1.set_xticklabels(["Accuracy", "Macro F1"], fontsize=10)
ax1.set_ylim(0, 1.1)
ax1.set_ylabel("Значення метрики", fontsize=9, color=GRAY_TEXT)
ax1.legend(fontsize=9, framealpha=0.7)
ax1.spines[["top", "right"]].set_visible(False)
ax1.yaxis.grid(True, linestyle="--", alpha=0.5)
ax1.set_axisbelow(True)

# ── Subplot 2: теги F1 ────────────────────────────────────────
ax2 = fig.add_subplot(2, 2, 2)
ax2.set_facecolor("white")
x2 = np.arange(2)
bars_tb = ax2.bar(x2 - w/2, [tag_micro_base, tag_macro_base], w,
                  label="Baseline", color=BLUE_BASE, edgecolor="white")
bars_tg = ax2.bar(x2 + w/2, [tag_micro_best, tag_macro_best], w,
                  label="Best (GridSearch)", color=BLUE_BEST, edgecolor="white")
for bar in (*bars_tb, *bars_tg):
    h = bar.get_height()
    ax2.text(bar.get_x() + bar.get_width()/2, h + 0.005,
             f"{h:.3f}", ha="center", va="bottom", fontsize=9, color=GRAY_TEXT)
ax2.set_title("Класифікатор тегів — F1", fontsize=12, fontweight="bold",
              color=GRAY_TEXT, pad=8)
ax2.set_xticks(x2)
ax2.set_xticklabels(["Micro F1", "Macro F1"], fontsize=10)
ax2.set_ylim(0, 1.1)
ax2.set_ylabel("Значення метрики", fontsize=9, color=GRAY_TEXT)
ax2.legend(fontsize=9, framealpha=0.7)
ax2.spines[["top", "right"]].set_visible(False)
ax2.yaxis.grid(True, linestyle="--", alpha=0.5)
ax2.set_axisbelow(True)

# ── Subplot 3: Hamming Loss ───────────────────────────────────
ax3 = fig.add_subplot(2, 2, 3)
ax3.set_facecolor("white")
bars_hl = ax3.bar(["Baseline", "Best (GridSearch)"],
                  [tag_hl_base, tag_hl_best], width=0.4,
                  color=[RED_BASE, RED_BEST], edgecolor="white")
for bar, val in zip(bars_hl, [tag_hl_base, tag_hl_best]):
    ax3.text(bar.get_x() + bar.get_width()/2, val + 0.0005,
             f"{val:.4f}", ha="center", va="bottom",
             fontsize=10, fontweight="bold", color=GRAY_TEXT)
ax3.set_title("Hamming Loss (теги)", fontsize=12,
              fontweight="bold", color=GRAY_TEXT, pad=8)
ax3.set_ylabel("Hamming Loss", fontsize=9, color=GRAY_TEXT)
ax3.set_ylim(0, max(tag_hl_base, tag_hl_best) * 1.4)
ax3.spines[["top", "right"]].set_visible(False)
ax3.yaxis.grid(True, linestyle="--", alpha=0.5)
ax3.set_axisbelow(True)

plt.tight_layout(rect=[0, 0, 1, 0.96])
plots_path = MODEL_DIR / "training_metrics.png"
plt.savefig(plots_path, dpi=150, bbox_inches="tight",
            facecolor=fig.get_facecolor())
plt.show()
print(f"✅ Plots saved to: {plots_path}")

# ── Збереження артефактів ──────────────────────────────────────

print("\n💾 Saving model artifacts...")

encoder.save(str(MODEL_DIR / "encoder"))
joblib.dump(best_cat_model, MODEL_DIR / "category_model.pkl")
joblib.dump(best_tag_model, MODEL_DIR / "tag_model.pkl")
joblib.dump(mlb, MODEL_DIR / "tag_binarizer.pkl")

print(f"✅ Training complete. Artifacts saved to: {MODEL_DIR}")