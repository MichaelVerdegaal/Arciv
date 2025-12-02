"""NER evaluation for precision/recall testing."""

from pathlib import Path

from clotho.config import logger

ENTITY_TYPES = ["PER", "ORG", "PRODUCT", "PROJ", "LOC", "EVENT"]

# Ground truth for 2025-11-27
DOC1_GROUND_TRUTH: dict[str, set[str]] = {
    "PER": {"Tom", "Jasper", "Lisa", "Bas", "Daan"},
    "ORG": set(),
    "PRODUCT": {"Python", "Pip", "VSCode", "UV", "Git", "Mermaid", "SharePoint"},
    "PROJ": {"VBF-DF", "GLF-DF", "Tulipa"},
    "LOC": set(),
    "EVENT": set(),
}

# Ground truth for 2025-11-28
DOC2_GROUND_TRUTH: dict[str, set[str]] = {
    "PER": {"Tom", "Michelle", "Peter", "Bas", "Dennis", "Erik", "Frank", "Stefan", "Daan", "Lars"},
    "ORG": {"GreenLeaf", "VB Bloemen", "Telco", "Tesco UK"},
    "PRODUCT": {"DAX", "Power BI", "Commitizen", "Dagster", "MRP"},
    "PROJ": {"VBF-DF", "GLF-DF", "PLT-DEV-PROD", "GCAP", "VBF", "GLF"},
    "LOC": set(),
    "EVENT": set(),
}

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"


def calculate_metrics(predicted: set[str], ground_truth: set[str]) -> dict:
    """Calculate precision, recall, and F1 for a single entity type."""
    tp = len(predicted & ground_truth)
    fp = len(predicted - ground_truth)
    fn = len(ground_truth - predicted)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "false_positives": predicted - ground_truth,
        "missed": ground_truth - predicted,
    }


def evaluate(
    predictions: dict[str, set[str]],
    ground_truth: dict[str, set[str]],
    name: str = "Document",
) -> dict:
    """Evaluate NER predictions against ground truth."""
    logger.info(f"Evaluating: {name}")

    results = {
        et: calculate_metrics(predictions.get(et, set()), ground_truth.get(et, set()))
        for et in ENTITY_TYPES
    }

    # Macro average over types that have ground truth
    active = [et for et in ENTITY_TYPES if ground_truth.get(et)]
    if active:
        results["macro"] = {
            "precision": sum(results[et]["precision"] for et in active) / len(active),
            "recall": sum(results[et]["recall"] for et in active) / len(active),
            "f1": sum(results[et]["f1"] for et in active) / len(active),
        }
    else:
        results["macro"] = {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    return results


def print_report(results: dict) -> None:
    """Print evaluation report."""
    logger.info("\n" + "=" * 70)
    logger.info(f"{'Type':<10} {'Prec':>8} {'Recall':>8} {'F1':>8} {'TP':>5} {'FP':>5} {'FN':>5}")
    logger.info("-" * 70)

    for et in ENTITY_TYPES:
        r = results[et]
        logger.info(f"{et:<10} {r['precision']:>8.3f} {r['recall']:>8.3f} {r['f1']:>8.3f} "
                    f"{r['tp']:>5} {r['fp']:>5} {r['fn']:>5}")

    logger.info("-" * 70)
    m = results["macro"]
    logger.info(f"{'MACRO':<10} {m['precision']:>8.3f} {m['recall']:>8.3f} {m['f1']:>8.3f}")
    logger.info("=" * 70)

    # Errors
    has_errors = False
    for et in ENTITY_TYPES:
        r = results[et]
        if r["false_positives"]:
            logger.info(f"  {et} false positives: {r['false_positives']}")
            has_errors = True
        if r["missed"]:
            logger.info(f"  {et} missed: {r['missed']}")
            has_errors = True

    if not has_errors:
        logger.info("  Perfect score")


def load_document(path: Path) -> str:
    """Load document text."""
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    # Example: test with simulated predictions
    predictions = {
        "PER": {"Tom", "Jasper", "Lisa", "Bas"},  # Missing Daan
        "ORG": {"Unknown Corp"},  # False positive
        "PRODUCT": {"Python", "Pip", "VSCode", "UV", "Git"},  # Missing Mermaid, SharePoint
        "PROJ": {"VBF-DF", "GLF-DF", "Tulipa"},
        "LOC": set(),
        "EVENT": set(),
    }

    results = evaluate(predictions, DOC1_GROUND_TRUTH, "Example")
    print_report(results)
