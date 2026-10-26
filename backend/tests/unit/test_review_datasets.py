"""Review-fixture quality and holdout isolation guards."""

from scripts.build_review_datasets import (
    build_review_classification,
    assistant_cases,
    financial_histories,
    planning_cases,
)


def test_review_dataset_covers_taxonomy_and_keeps_merchants_and_templates_isolated():
    dataset, split = build_review_classification()
    assert dataset.manifest.source_kind.value == "synthetic"
    assert dataset.manifest.record_count == 20400
    assert len(dataset.manifest.label_counts) == 48
    assert {x.count for x in dataset.manifest.label_counts} == {425}
    assert [len(split.train), len(split.calibration), len(split.test)] == [
        12240,
        4080,
        4080,
    ]
    partitions = (split.train, split.calibration, split.test)
    merchants = [{r.normalized_merchant for r in rows} for rows in partitions]
    groups = [{r.group_id for r in rows} for rows in partitions]
    assert all(
        a.isdisjoint(b)
        for sets in (merchants, groups)
        for i, a in enumerate(sets)
        for b in sets[i + 1 :]
    )
    assert None not in merchants[0]
    assert len({r.record_id for r in dataset.records}) == 20400


def test_fixture_oracles_and_missing_masks_are_explicit():
    histories = financial_histories()
    assert len(histories) == 150
    assert {r["regime"] for r in histories} == {
        "regular",
        "irregular",
        "seasonal",
        "income_loss",
        "expense_shock",
        "missing_periods",
    }
    assert all(len(r["periods"]) == 36 for r in histories)
    for history in histories:
        for p in history["periods"]:
            assert (p["income"] is None) == p["missing"]
    cases = assistant_cases()
    assert len(cases) == 720
    for r in cases:
        assert int(r["context"]["income"]) - int(r["context"]["expenses"]) == int(
            r["expected_facts"]["net_cash_flow"]
        )
        assert "live model answer requires review" in r["review_status"]
    assert len(planning_cases()) == 1000


def test_materialization_preserves_conflicting_existing_data(tmp_path, monkeypatch):
    import json
    import pytest
    from scripts import build_review_datasets as module

    manifest = {"dataset_version": "fixture", "files": {}}

    def staged_generate(root, version):
        root.mkdir(parents=True, exist_ok=True)
        (root / "manifest.json").write_text(json.dumps(manifest))
        (root / "classification.jsonl").write_text("expected\n")
        (root / "missing.jsonl").write_text("missing\n")

    monkeypatch.setattr(module, "generate", staged_generate)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "classification.jsonl").write_text("private conflict\n")
    with pytest.raises(ValueError, match="Existing fixture differs"):
        module.materialize_missing(tmp_path, "fixture")
    assert (tmp_path / "classification.jsonl").read_text() == "private conflict\n"
    assert not (tmp_path / "missing.jsonl").exists()


def test_materialization_restores_only_missing_matching_files(tmp_path, monkeypatch):
    import json
    from scripts import build_review_datasets as module

    manifest = {"dataset_version": "fixture", "files": {}}

    def staged_generate(root, version):
        root.mkdir(parents=True, exist_ok=True)
        (root / "manifest.json").write_text(json.dumps(manifest))
        (root / "classification.jsonl").write_text("expected\n")

    monkeypatch.setattr(module, "generate", staged_generate)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    original = (tmp_path / "manifest.json").read_bytes()
    module.materialize_missing(tmp_path, "fixture")
    assert (tmp_path / "manifest.json").read_bytes() == original
    assert (tmp_path / "classification.jsonl").read_text() == "expected\n"


def test_materialization_accepts_crlf_metadata_without_rewriting_it(
    tmp_path, monkeypatch
):
    import json
    from scripts import build_review_datasets as module

    manifest = {"dataset_version": "fixture", "files": {}}
    metadata = json.dumps({"record_count": 20}, indent=2) + "\n"

    def staged_generate(root, version):
        root.mkdir(parents=True, exist_ok=True)
        (root / "manifest.json").write_bytes(
            (json.dumps(manifest, indent=2) + "\n").encode()
        )
        (root / "classification_manifest.json").write_bytes(metadata.encode())
        (root / "classification.jsonl").write_bytes(b"expected\n")

    monkeypatch.setattr(module, "generate", staged_generate)
    staged_generate(tmp_path, "fixture")
    for name in ("manifest.json", "classification_manifest.json"):
        path = tmp_path / name
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    original = (tmp_path / "classification_manifest.json").read_bytes()
    (tmp_path / "classification.jsonl").unlink()
    module.materialize_missing(tmp_path, "fixture")
    assert (tmp_path / "classification_manifest.json").read_bytes() == original
    assert (tmp_path / "classification.jsonl").read_bytes() == b"expected\n"


def test_materialization_still_rejects_crlf_jsonl_checksum_changes(
    tmp_path, monkeypatch
):
    import json
    import pytest
    from scripts import build_review_datasets as module

    def staged_generate(root, version):
        root.mkdir(parents=True, exist_ok=True)
        (root / "manifest.json").write_text(json.dumps({"files": {}}))
        (root / "classification.jsonl").write_bytes(b"expected\n")

    monkeypatch.setattr(module, "generate", staged_generate)
    staged_generate(tmp_path, "fixture")
    (tmp_path / "classification.jsonl").write_bytes(b"expected\r\n")
    with pytest.raises(ValueError, match="classification.jsonl"):
        module.materialize_missing(tmp_path, "fixture")
