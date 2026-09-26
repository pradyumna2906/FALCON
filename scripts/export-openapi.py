"""Generate deterministic frontend contracts without a database or secrets."""

import argparse
import json
from pathlib import Path

from falcon_api.core.config import Settings
from falcon_api.main import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "frontend" / "openapi.json"
    settings = Settings(_env_file=None, env="test", debug=False, docs_enabled=True)
    document = (
        json.dumps(create_app(settings).openapi(), indent=2, sort_keys=True) + "\n"
    )
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != document:
            raise SystemExit(
                "OpenAPI drift: run scripts/export-openapi.py and npm run generate:api"
            )
    else:
        target.write_text(document, encoding="utf-8")


if __name__ == "__main__":
    main()
