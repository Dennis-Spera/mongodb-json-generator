import json
from pathlib import Path

SCHEMAS_DIR = Path(__file__).parent / "schemas"
SCHEMAS_DIR.mkdir(exist_ok=True)


def load_schemas() -> dict[str, list]:
    schemas = {}
    for path in sorted(SCHEMAS_DIR.glob("*.json")):
        try:
            schemas[path.stem] = json.loads(path.read_text())
        except Exception:
            pass
    return schemas


def save_schema(collection: str, fields: list) -> None:
    (SCHEMAS_DIR / f"{collection}.json").write_text(json.dumps(fields, indent=2))


def delete_schema(collection: str) -> None:
    p = SCHEMAS_DIR / f"{collection}.json"
    if p.exists():
        p.unlink()
