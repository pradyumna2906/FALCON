"""Encrypt/decrypt PostgreSQL custom archives with streaming AES-256-GCM.

Usage: backup-archive.py encrypt|decrypt INPUT OUTPUT --key-file PRIVATE_KEY
The key file contains exactly 32 random bytes. Output must not exist. Decryption
authenticates before publishing a file; never pipe unauthenticated data to SQL.
"""

import argparse
import os
from pathlib import Path
import tempfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"FALCON-BACKUP-v1\0"


def transform(source: Path, destination: Path, key: bytes, *, decrypt: bool):
    if len(key) != 32:
        raise ValueError("Backup key must contain exactly 32 bytes.")
    if destination.exists():
        raise ValueError("Destination must not exist.")
    fd, temporary = tempfile.mkstemp(prefix=".falcon-", dir=destination.parent)
    try:
        with source.open("rb") as incoming, os.fdopen(fd, "wb") as outgoing:
            if decrypt:
                if incoming.read(len(MAGIC)) != MAGIC:
                    raise ValueError("Invalid archive header.")
                nonce = incoming.read(12)
                start = incoming.tell()
                incoming.seek(-16, 2)
                end = incoming.tell()
                tag = incoming.read(16)
                incoming.seek(start)
                remaining = end - start
                if remaining < 0:
                    raise ValueError("Truncated archive.")
                engine = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            else:
                nonce = os.urandom(12)
                outgoing.write(MAGIC + nonce)
                remaining = source.stat().st_size
                engine = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
            engine.authenticate_additional_data(MAGIC)
            while remaining:
                chunk = incoming.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("Truncated archive.")
                remaining -= len(chunk)
                outgoing.write(engine.update(chunk))
            outgoing.write(engine.finalize())
            if not decrypt:
                outgoing.write(engine.tag)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        # Hard link is atomic and fails if another process created destination.
        os.link(temporary, destination)
    finally:
        os.unlink(temporary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("encrypt", "decrypt"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        transform(args.source, args.destination, args.key_file.read_bytes(), decrypt=args.mode == "decrypt")
    except Exception:
        parser.exit(1, "Archive operation failed; no destination was published.\n")
