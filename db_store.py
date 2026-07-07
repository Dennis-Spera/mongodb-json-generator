from pathlib import Path
from tinydb import TinyDB

DB_DIR = Path(__file__).parent / "db"
DB_DIR.mkdir(exist_ok=True)


def _open(collection: str) -> TinyDB:
    return TinyDB(DB_DIR / f"{collection}.json", indent=2)


def insert_documents(collection: str, docs: list[dict], clear_first: bool = False) -> int:
    with _open(collection) as db:
        if clear_first:
            db.clear()
        db.insert_multiple(docs)
    return len(docs)


def get_documents(collection: str, page: int = 1, per_page: int = 20) -> tuple[list[dict], int]:
    with _open(collection) as db:
        all_docs = db.all()
    total = len(all_docs)
    start = (page - 1) * per_page
    return all_docs[start: start + per_page], total


def list_collections() -> list[dict]:
    result = []
    for path in sorted(DB_DIR.glob("*.json")):
        with TinyDB(path, indent=2) as db:
            count = len(db.all())
        result.append({"name": path.stem, "count": count})
    return result


def drop_collection(collection: str) -> None:
    path = DB_DIR / f"{collection}.json"
    if path.exists():
        path.unlink()
