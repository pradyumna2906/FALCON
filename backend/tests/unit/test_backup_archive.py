"""A corrupt or wrong-key backup must never publish plaintext for restore."""

import importlib.util
import os
from pathlib import Path

import pytest


def test_backup_roundtrip_and_tamper_rejection(tmp_path):
    path = Path(__file__).resolve().parents[3] / "scripts/backup-archive.py"
    spec = importlib.util.spec_from_file_location("backup_archive", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source, encrypted, restored = (tmp_path / name for name in ("dump", "encrypted", "restored"))
    source.write_bytes(os.urandom(2_100_000))
    key = os.urandom(32)
    module.transform(source, encrypted, key, decrypt=False)
    module.transform(encrypted, restored, key, decrypt=True)
    assert restored.read_bytes() == source.read_bytes()
    assert restored.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="must not exist"):
        module.transform(encrypted, restored, key, decrypt=True)
    with pytest.raises(Exception):
        module.transform(encrypted, tmp_path / "wrong", os.urandom(32), decrypt=True)
    damaged = bytearray(encrypted.read_bytes())
    damaged[-20] ^= 1
    encrypted.write_bytes(damaged)
    with pytest.raises(Exception):
        module.transform(encrypted, tmp_path / "tampered", key, decrypt=True)
    assert not (tmp_path / "wrong").exists() and not (tmp_path / "tampered").exists()
    assert not list(tmp_path.glob(".falcon-*"))
