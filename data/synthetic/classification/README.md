# Synthetic Transaction Classification Dataset

Dataset version `2026.1` contains 864 fictional INR transaction feature records,
18 for each of the 48 Phase 7 taxonomy leaves. Six independent fictional
merchant groups per leaf and three descriptions per group support an opaque
group-isolated train/calibration/test split.

The JSONL stores only the shared sanitized feature representation, opaque HMAC
record/group identifiers, taxonomy targets, and version metadata. It contains no
real user, account, statement, UPI, card, bank-reference, or transaction data.
It is balanced evaluation scaffolding, not proof of real-world model quality.

Files:

- `transactions_2026_1.jsonl`: deterministic sanitized records;
- `manifest_2026_1.json`: counts, versions, and SHA-256 integrity checksum.

Rebuild both files and the corresponding evaluation report from the repository
root after installing the backend `ml` extra:

```text
PYTHONPATH=backend/src python scripts/build_classification_evidence.py
```

Do not replace this dataset with user exports. Reviewed de-identified training
data requires approved private storage and a new reviewed dataset version.
