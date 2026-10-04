# Review dataset provenance and validation

All review fixtures are synthetic and project-generated. No user database,
statement, provider key or third-party dataset was read. Repository licensing
is not explicitly declared in a root LICENSE file at this repository revision.
These project-generated fixtures contain no third-party observed data; the owner
should choose a license before external redistribution. The manifest wording
“repository license applies” does not grant a license by itself. These fixtures are engineering
evidence, not representative measurements of the Indian banking population.

The original 864-record `2026.1` classification dataset and report remain intact.
`2026.2-review` adds 20,400 records across the actual 48 taxonomy leaves. Each
label has 425 rows, with 25 template families and 17 variants per family.
`2026.3-review` preserves the same 12,240 training and 4,080 validation rows but
replaces the 4,080 final-test rows with five fresh template families and separate
merchants. Original test rows were not added to training or validation.

## Split and experiment history

1. Word TF-IDF logistic regression and calibrated SVM were evaluated on version 2.
2. A separate validation-only experiment compared character + word features at
   SVM C=0.5, 1 and 4. C=1 won validation macro-F1.
3. That representation and C were frozen before version 3 final-test evaluation.
4. Version 3 final-test outcomes were reported without tuning against them.

Both iterations and their negative results are preserved. Version 3 is a fresh
synthetic holdout, **not an external real-world test**. Both versions share a
controlled generator, hand-authored financial phrases and source taxonomy.
Validation/test reuse of semantic phrase vocabulary limits distributional
independence even though template families, merchants and opaque group IDs are
isolated. This benchmark cannot establish performance across real banks.

Generation deliberately makes 1/17 examples ambiguous by removing category
purpose while retaining a generator-assigned latent label. Those labels are
not always inferable from model-visible text; a safe system may abstain.
Generated class frequencies are balanced, unlike typical personal ledgers.
Transaction type and channel can legitimately inform categorization. Merchant
names use neutral synthetic tokens without embedded category names.

## Integrity and data quality

- Deterministic seed: 20261004. Synthetic HMAC key is public fixture metadata,
  never a privacy key for real exports.
- Shared production feature builder and taxonomy validation are used.
- Dataset builder rejects duplicate source IDs, duplicate labelled feature
  records and mixed-label groups.
- Split validation rejects cross-partition group/merchant overlap.
- SHA-256 and row counts are checked before classification evaluation.
- Source IDs, exact transaction amounts and owner IDs are absent from the
  classification feature export. These fictional descriptions are safe to share;
  the same would not automatically be true for real normalized descriptions.

| Fixture | Count / grain | Intended use and limitation |
|---|---:|---|
| Classification | 20,400 records/version | Training, validation, synthetic generalization |
| Forecast histories | 150 histories × 36 months | Six regimes; 300 income/expense series |
| Assistant | 720 question/context cases | Offline grounding and guardrail replay; live answers need review |
| Planning | 1,000 arithmetic cases | Summary calculations and bounded HiGHS adapter; broader goal logic has separate tests |
| Performance | 100,000 records | Feature extraction benchmark; not database/HTTP throughput |

Forecast fixtures include missing-month masks and labelled shocks. Evaluation
uses causal carry-forward only for missing training values, preserves monthly
calendar positions and holds out the last three observed months. This is an
explicit benchmark preprocessing choice, not a new automatic imputation rule
for live user records.

## Files and reproduction

Generators and manifests are committed. Large generated JSONL files are ignored
and delivered as a separate dataset archive; they can be reproduced locally:

```powershell
& .\.venv\Scripts\python.exe .\scripts\build_review_datasets.py --version 2026.2-review --output data/synthetic/local_v2
& .\.venv\Scripts\python.exe .\scripts\build_review_datasets.py --version 2026.3-review --output data/synthetic/local_v3
```

An existing output manifest causes generation to stop rather than overwrite
published evidence. The explicit `--materialize-missing` option restores only
missing ignored files after checking generated manifests and all existing bytes;
it refuses conflicts and never replaces existing data. Compare generated
manifests/checksums with the committed
version metadata. Different training-library versions may change fitted model
bytes, so local artifacts must be rebuilt with their own verified manifests.
Never deserialize a model downloaded from an untrusted source.

Consented/licensed real-data evaluation remains unavailable. Do not call these
fixtures “real-life accurate datasets” or use them to claim production ML
accuracy. Do not import them into existing user accounts.
