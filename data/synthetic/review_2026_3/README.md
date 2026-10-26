# Synthetic final-review fixtures 2026.3

`manifest.json` records counts, versions, template partitions and checksums.
`classification_manifest.json` uses the production classification schema.
The generated JSONL files are intentionally ignored to keep Git small.

From the repository root, after installing the backend ML extras:

```powershell
& .\.venv\Scripts\python.exe .\scripts\build_review_datasets.py --materialize-missing
```

`--materialize-missing` restores ignored JSONL bytes only if they match the
committed manifest and preserves existing files. Choose a new `--output` directory
when reproducing the committed generation metadata. See
[provenance](../../../docs/ml/DATASET_PROVENANCE.md) and
[final review](../../../docs/testing/FINAL_REVIEW.md).
