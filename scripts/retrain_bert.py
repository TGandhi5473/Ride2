"""Train the classifier head from newly collected human feedback."""
import sys
from pathlib import Path

import pandas as pd
import torch
from sqlalchemy import text
from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import Config
from core.database import get_neon_engine
from core.logging import setup_logger

logger = setup_logger("BERTTraining")


class FeedbackDataset(torch.utils.data.Dataset):
    """Small in-memory tokenized dataset for the feedback batch."""
    def __init__(self, encodings, labels):
        self.encodings, self.labels = encodings, labels

    def __getitem__(self, index):
        return {**{key: torch.tensor(value[index]) for key, value in self.encodings.items()},
                "labels": torch.tensor(self.labels[index], dtype=torch.long)}

    def __len__(self):
        return len(self.labels)


def get_training_data() -> pd.DataFrame:
    """Fetch stable IDs with the text and label required to train."""
    query = text("""
        SELECT id, text, label_id AS label
        FROM gold.human_feedback
        WHERE used_for_training = FALSE AND text IS NOT NULL AND label_id IN (0, 1)
        ORDER BY created_at
    """)
    with get_neon_engine().connect() as conn:
        return pd.read_sql(query, conn)


def run_retraining() -> bool:
    Config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    df = get_training_data()
    if len(df) < Config.TRAINING_THRESHOLD:
        logger.info("Have %d unused labels; threshold is %d. Skipping.", len(df), Config.TRAINING_THRESHOLD)
        return False
    if df["label"].nunique() < 2:
        logger.warning("Training batch needs both approve and reject labels; leaving feedback pending.")
        return False

    logger.info("Training critic with %d feedback samples", len(df))
    model_path = Config.get_active_bert_path()
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_path,
        num_labels=2,
        id2label={0: "REJECT", 1: "APPROVE"},
        label2id={"REJECT": 0, "APPROVE": 1},
        ignore_mismatched_sizes=True,
    )
    # Keep the base representation fixed: this is inexpensive on CPU and reduces
    # overfitting with a small human-label dataset. Only the classification head learns.
    if hasattr(model, "base_model"):
        for parameter in model.base_model.parameters():
            parameter.requires_grad = False
    encodings = tokenizer(df["text"].astype(str).tolist(), truncation=True, padding=True,
                          max_length=Config.MAX_SEQ_LENGTH)
    dataset = FeedbackDataset(encodings, df["label"].astype(int).tolist())
    output_dir = Config.MODEL_DIR / "training_output"
    args = TrainingArguments(
        output_dir=str(output_dir), num_train_epochs=3, per_device_train_batch_size=8,
        learning_rate=5e-4, weight_decay=0.01, logging_strategy="no",
        save_strategy="no", report_to="none", use_cpu=True,
    )
    trainer = Trainer(model=model, args=args, train_dataset=dataset)
    trainer.train()

    # Save first; only archive exactly these IDs once model files are safely written.
    save_path = Config.BERT_REFINED_PATH
    temp_path = Config.MODEL_DIR / "refined_bert_staging"
    if temp_path.exists():
        import shutil
        shutil.rmtree(temp_path)
    temp_path.mkdir(parents=True)
    trainer.model.save_pretrained(temp_path)
    tokenizer.save_pretrained(temp_path)
    if save_path.exists():
        import shutil
        shutil.rmtree(save_path)
    temp_path.rename(save_path)
    ids = df["id"].tolist()
    with get_neon_engine().begin() as conn:
        conn.execute(text("UPDATE gold.human_feedback SET used_for_training = TRUE WHERE id = ANY(:ids)"), {"ids": ids})
    logger.info("Saved critic and archived %d trained labels", len(ids))
    return True


if __name__ == "__main__":
    run_retraining()
