import copy
import html
import json
import os
import random
import socket
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from nicegui import ui, run
from faker_fields import generate_documents
from schema_store import load_schemas, save_schema, delete_schema

OUTPUT_DIR  = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_FILENAME = "{collection}.json"  # supports {collection} placeholder
ATLAS_URI = ""
ATLAS_DB = ""

# ── State ─────────────────────────────────────────────────────────────────────

_id_ctr = 100

def _new_id() -> int:
    global _id_ctr
    _id_ctr += 1
    return _id_ctr


TYPE_OPTIONS = [
    "String", "Int32", "Int64", "Double", "Decimal128",
    "Boolean", "Date", "ObjectId", "UUID", "Binary",
    "Array", "Object", "Null", "Timestamp",
    "Enum", "Range",
]
_TYPE_LOOKUP = {t.lower(): t for t in TYPE_OPTIONS}
ARRAY_ELEMENT_TYPE_OPTIONS = [
    "String", "Int32", "Int64", "Double", "Decimal128",
    "Boolean", "Date", "ObjectId", "UUID", "Binary", "Null", "Timestamp",
]


def _canonical_type(value) -> str:
    if isinstance(value, str):
        candidate = value
    elif isinstance(value, int):
        candidate = TYPE_OPTIONS[value] if 0 <= value < len(TYPE_OPTIONS) else "String"
    elif isinstance(value, dict):
        target = value.get("target") if isinstance(value.get("target"), dict) else {}
        candidate = (
            value.get("value")
            or value.get("label")
            or value.get("model")
            or target.get("value")
            or "String"
        )
    elif isinstance(value, (list, tuple)):
        candidate = value[0] if value else "String"
    else:
        candidate = "String"
    if not isinstance(candidate, str):
        candidate = "String"
    return _TYPE_LOOKUP.get(candidate.lower(), candidate)


def _normalize_field_types(fields: list[dict]) -> None:
    for field in fields:
        field["type"] = _canonical_type(field.get("type", "String"))
        if field["type"] == "Object":
            _normalize_field_types(field.get("fields", []))


def _array_element_type_default(field: dict) -> str:
    element_type = field.get("element_type")
    if isinstance(element_type, str) and element_type in ARRAY_ELEMENT_TYPE_OPTIONS:
        return element_type
    # Legacy mapping from element_faker to new element_type.
    faker = field.get("element_faker", "")
    if faker == "uuid":
        return "UUID"
    if faker == "number":
        return "Int32"
    if faker == "boolean":
        return "Boolean"
    if faker == "date":
        return "Date"
    return "String"


def _array_size_default(field: dict) -> int:
    if "size" in field:
        try:
            return max(0, int(field.get("size", 1)))
        except (TypeError, ValueError):
            return 1
    try:
        min_items = int(field.get("min_items", 1))
        max_items = int(field.get("max_items", min_items))
        if min_items == max_items:
            return max(0, min_items)
    except (TypeError, ValueError):
        pass
    return 1

DEFAULT_FIELDS = [
    {"id": 0, "name": "_id", "type": "ObjectId", "locked": True, "required": True},
]

schemas = load_schemas()
for _fields in schemas.values():
    _normalize_field_types(_fields)
if not schemas:
    schemas = {"users": copy.deepcopy(DEFAULT_FIELDS)}
    save_schema("users", schemas["users"])

collections: list[str] = list(schemas.keys())
current_col: str = collections[0]

gen_settings: dict = {
    "count": 1000,
    "seed": 42,
    "clear_first": True,
    "load_pymongo": False,
    "load_mongoimport": True,
}

preview_docs: list[dict] = []
preview_index: int = 0

is_generating: bool = False
progress_current: int = 0

# ── Helpers ───────────────────────────────────────────────────────────────────

def find_open_port(start_port: int = 8080, max_tries: int = 100) -> int:
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"No open port found in range {start_port}-{start_port + max_tries - 1}")

def cur_fields() -> list[dict]:
    return schemas.get(current_col, [])


def find_field(fid: int, fields: list | None = None) -> dict | None:
    if fields is None:
        fields = cur_fields()
    for f in fields:
        if f["id"] == fid:
            return f
        if f["type"] == "Object":
            found = find_field(fid, f.get("fields", []))
            if found:
                return found
    return None


def shuffler_weights(values: list, shuffler: int) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    if shuffler <= 1:
        return [round(1.0, 2)] * n
    base = [random.expovariate(1.0) for _ in range(n)]
    mean = sum(base) / n
    scaled = [mean + (x - mean) * (shuffler / 10.0) for x in base]
    total = sum(scaled)
    return [round(x * n / total, 2) for x in scaled]


def json_to_html(obj, indent: int = 0) -> str:
    pad = "  " * indent
    ipad = "  " * (indent + 1)
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        lines = ["{"]
        items = list(obj.items())
        for i, (k, v) in enumerate(items):
            comma = "," if i < len(items) - 1 else ""
            lines.append(f'{ipad}<span class="code-key">"{k}"</span>: {json_to_html(v, indent+1)}{comma}')
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    if isinstance(obj, list):
        if not obj:
            return "[]"
        lines = ["["]
        for i, v in enumerate(obj):
            comma = "," if i < len(obj) - 1 else ""
            lines.append(f"{ipad}{json_to_html(v, indent+1)}{comma}")
        lines.append(f"{pad}]")
        return "\n".join(lines)
    if isinstance(obj, str):
        if obj.startswith("ObjectId("):
            return f'<span class="code-comment">{obj}</span>'
        esc = obj.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<span class="code-string">"{esc}"</span>'
    if isinstance(obj, bool):
        return f'<span class="code-number">{"true" if obj else "false"}</span>'
    if isinstance(obj, (int, float)):
        return f'<span class="code-number">{obj}</span>'
    if obj is None:
        return '<span class="code-comment">null</span>'
    return str(obj)


def build_cli_html() -> str:
    col = current_col
    count = gen_settings["count"]
    seed = gen_settings["seed"]
    clear = "\n  <span class='flag'>--overwrite</span>" if gen_settings["clear_first"] else ""
    return (
        f"mongodocgen generate <span class='cont'>\\</span>\n"
        f"  <span class='flag'>--collection</span> <span class='val'>{col}</span> <span class='cont'>\\</span>\n"
        f"  <span class='flag'>--schema</span> <span class='val'>schemas/{col}.json</span> <span class='cont'>\\</span>\n"
        f"  <span class='flag'>--count</span> <span class='val'>{count}</span> <span class='cont'>\\</span>\n"
        f"  <span class='flag'>--seed</span> <span class='val'>{seed}</span> <span class='cont'>\\</span>\n"
        f"  <span class='flag'>--output</span> <span class='val'>output/{col}.json</span>{clear}"
    )


def atlas_uri_status_label() -> str:
    return "set" if ATLAS_URI.strip() else "not set"


def _resolve_target_database() -> str:
    explicit = ATLAS_DB.strip()
    if explicit:
        return explicit

    uri = ATLAS_URI.strip()
    if not uri:
        return "test"

    try:
        parsed = urlparse(uri)
        db_name = unquote(parsed.path.lstrip("/").split("/")[0])
        return db_name or "test"
    except Exception:
        return "test"


def build_connection_help_html() -> str:
    col = current_col
    fname = OUTPUT_FILENAME.replace("{collection}", col)
    out_path = str((OUTPUT_DIR / fname).resolve()).replace("\\", "/")
    db_name = html.escape(_resolve_target_database())

    if not ATLAS_URI.strip():
        return (
            '<div style="margin-top:12px;font-size:11px;color:#9ca3af">'
            "Set an Atlas connection string in Output settings to show mongoimport and pymongo examples."
            "</div>"
        )

    safe_uri = html.escape(ATLAS_URI.strip())
    return (
        '<div style="margin-top:12px;font-size:11px;color:#666">'
        '<div style="font-weight:600;color:#2a2a2a;margin-bottom:6px">Atlas import helpers</div>'
        '<div style="font-family:\'Monaco\',\'Menlo\',monospace;background:#f9f7f5;border:.5px solid #e0dcd8;border-radius:6px;padding:10px;line-height:1.55">'
        f"mongoimport --uri \"{safe_uri}\" --db {db_name} --collection {col} --file \"{html.escape(out_path)}\" --jsonArray"
        "<br><br>"
        "from pymongo import MongoClient"
        "<br>"
        f"client = MongoClient(\"{safe_uri}\")"
        "<br>"
        f"collection = client[\"{db_name}\"][\"{col}\"]"
        "</div>"
        "</div>"
    )


def build_connection_help_text() -> str:
    col = current_col
    fname = OUTPUT_FILENAME.replace("{collection}", col)
    out_path = str((OUTPUT_DIR / fname).resolve())
    db_name = _resolve_target_database()

    if not ATLAS_URI.strip():
        return ""

    uri = ATLAS_URI.strip()
    return (
        "\n\n# Atlas import helpers\n"
        f"mongoimport --uri \"{uri}\" --db {db_name} --collection {col} --file \"{out_path}\" --jsonArray\n\n"
        "from pymongo import MongoClient\n"
        f"client = MongoClient(\"{uri}\")\n"
        f"collection = client[\"{db_name}\"][\"{col}\"]"
    )


def _normalize_type_value(value) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("value", "model-value", "modelValue"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
        if len(value) == 1:
            only_value = next(iter(value.values()))
            if isinstance(only_value, str):
                return only_value
        return None
    if isinstance(value, (list, tuple)):
        first = value[0] if value else None
        return first if isinstance(first, str) else None
    return None


_HEX24_RE = re.compile(r"^[0-9a-fA-F]{24}$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def _looks_like_iso_date(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _guess_faker_for_name(name: str) -> str:
    lowered = name.lower()
    hints = [
        ("email", "email"),
        ("phone", "phone"),
        ("mobile", "phone"),
        ("name", "fullName"),
        ("first", "firstName"),
        ("last", "lastName"),
        ("user", "username"),
        ("company", "companyName"),
        ("address", "street"),
        ("street", "street"),
        ("city", "city"),
        ("state", "state"),
        ("country", "country"),
        ("zip", "zipCode"),
        ("postal", "zipCode"),
        ("url", "url"),
        ("ip", "ipAddress"),
        ("date", "date"),
        ("created", "date"),
        ("updated", "date"),
    ]
    for needle, faker in hints:
        if needle in lowered:
            return faker
    return "word"


def _infer_type_from_value(value) -> str:
    if value is None:
        return "Null"
    if isinstance(value, bool):
        return "Boolean"
    if isinstance(value, int):
        if -2147483648 <= value <= 2147483647:
            return "Int32"
        return "Int64"
    if isinstance(value, float):
        return "Double"
    if isinstance(value, dict):
        return "Object"
    if isinstance(value, list):
        return "Array"
    if isinstance(value, str):
        txt = value.strip()
        if txt.startswith("ObjectId("):
            return "ObjectId"
        if _HEX24_RE.fullmatch(txt):
            return "ObjectId"
        if _UUID_RE.fullmatch(txt):
            return "UUID"
        if _looks_like_iso_date(txt):
            return "Date"
        return "String"
    return "String"


def _infer_field(name: str, value, *, locked: bool = False) -> dict:
    field_type = _infer_type_from_value(value)
    field = {
        "id": _new_id(),
        "name": name,
        "type": field_type,
        "required": True,
    }
    if locked:
        field["locked"] = True

    if field_type == "String":
        field["faker"] = _guess_faker_for_name(name)
    elif field_type == "Int32":
        field.update({"min": 0, "max": 2147483647})
    elif field_type == "Int64":
        field.update({"min": 0, "max": 9007199254740991})
    elif field_type == "Double":
        field.update({"min": 0.0, "max": 1000.0})
    elif field_type == "Array":
        min_items = 0 if len(value) == 0 else 1
        max_items = max(1, min(10, len(value) if len(value) > 0 else 3))
        field.update({
            "element_faker": "word",
            "min_items": min_items,
            "max_items": max_items,
        })
        if value:
            first = value[0]
            if isinstance(first, bool):
                field["element_faker"] = "boolean"
            elif isinstance(first, (int, float)):
                field["element_faker"] = "number"
            elif isinstance(first, str):
                field["element_faker"] = _guess_faker_for_name(name)
    elif field_type == "Object":
        field["fields"] = _infer_fields_from_document(value)
    elif field_type == "Range":
        field.update({"min": 0, "max": 100})

    return field


def _infer_fields_from_document(doc: dict) -> list[dict]:
    fields: list[dict] = []
    for key, value in doc.items():
        is_locked_id = key == "_id"
        inferred = _infer_field(key, value, locked=is_locked_id)
        fields.append(inferred)

    if not any(f["name"] == "_id" for f in fields):
        fields.insert(0, copy.deepcopy(DEFAULT_FIELDS[0]))
    return fields


def _change_type(fid: int, new_type) -> bool:
    field = find_field(fid)
    if not field or field.get("locked"):
        return False
    new_type = _canonical_type(new_type)
    if not new_type or new_type == field["type"]:
        return False
    # keep name/id/required, reset type-specific keys
    for k in ["faker", "min", "max", "values", "weights", "shuffler",
              "element_faker", "element_type", "size", "seed_values", "seed_randomize", "min_items", "max_items", "fields", "cardinality"]:
        field.pop(k, None)
    field["type"] = new_type
    if new_type == "String":
        field["faker"] = "word"
    elif new_type in ("Int32", "Int64"):
        field.update({"min": 0, "max": 2147483647 if new_type == "Int32" else 9007199254740991})
    elif new_type == "Double":
        field.update({"min": 0.0, "max": 1000.0})
    elif new_type == "Decimal128":
        field.update({"min": 0.0, "max": 9999.99, "precision": 2})
    elif new_type == "Range":
        field.update({"min": 0, "max": 100})
    elif new_type == "Enum":
        field.update({"values": ["option1", "option2"], "weights": [1.0, 1.0], "shuffler": 1})
    elif new_type == "Array":
        field.update({"element_type": "String", "size": 1, "seed_randomize": False, "cardinality": "1"})
    elif new_type == "Object":
        field["fields"] = []
    save_schema(current_col, schemas[current_col])
    return True


def update_field_prop(fid: int, key: str, value) -> None:
    field = find_field(fid)
    if field and not field.get("locked"):
        field[key] = value
        save_schema(current_col, schemas[current_col])


def type_label(field: dict) -> str:
    return field.get("type", "String")


def cardinality_of(field: dict) -> str:
    if field["type"] == "Array":
        return str(_array_size_default(field))
    return field.get("cardinality", "1")


def default_display(field: dict) -> str:
    t = field["type"]
    if t == "ObjectId":
        return '<span class="field-default italic">auto</span>'
    if t == "String":
        return '<span class="field-default">""</span>'
    if t == "Range":
        return f'<span class="field-default">{field.get("min", 0)} → {field.get("max", 100)}</span>'
    if t == "Object":
        return '<span class="field-default">{...}</span>'
    if t == "Array":
        return '<span class="field-default">[]</span>'
    if t == "Enum":
        vals = field.get("values", [])
        chips = "".join(f'<span class="chip">{v}</span>' for v in vals)
        chips += '<span class="chip chip-add">+ add</span>'
        sh = field.get("shuffler", 1)
        return f'<div class="chips">{chips}</div><span class="shuffler-chip">🔀 shuffler: {sh}</span>'
    return ""


def tr_class(field: dict) -> str:
    t = field["type"]
    return {"Range": "badge-range", "Enum": "badge-enum",
            "Array": "badge-array", "Object": "badge-object"}.get(t, "")


# ── CSS ───────────────────────────────────────────────────────────────────────

APP_CSS = """<style>
*{margin:0;padding:0;box-sizing:border-box}
body,.q-page,.q-page-container{background:#f5f1ed!important;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.q-page{padding:6px!important}
.q-header{display:none!important}
.container{width:100%;max-width:none}
.card{background:#fff;border:.5px solid #e0dcd8;border-radius:6px;display:flex;flex-direction:column;height:calc(100vh - 12px);position:relative;overflow:hidden}
.title-bar{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;border-bottom:.5px solid #e0dcd8;flex-shrink:0}
.title-left{display:flex;gap:12px;align-items:center}
.app-icon{width:28px;height:28px;background:linear-gradient(135deg,#6b5b95,#88498f);border-radius:6px;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:14px}
.app-title{font-size:15px;font-weight:500;color:#2a2a2a}
.title-right{display:flex;gap:8px}
.pill{padding:6px 12px;border-radius:16px;font-size:12px;font-weight:500}
.pill-blue{background:#dbeafe;color:#1e40af}
.pill-teal{background:#ccfbf1;color:#0d9488}
.pill-purple{background:#e9d5ff;color:#6b21a8}
.collection-tabs{display:flex;align-items:center;gap:4px;padding:10px 20px;border-bottom:.5px solid #e0dcd8;overflow-x:auto;flex-shrink:0}
.collection-tab{padding:6px 14px;border-radius:6px;font-size:12px;font-weight:500;color:#888;cursor:pointer;white-space:nowrap;border:none;background:transparent}
.collection-tab.active{background:#f3f1f0;color:#2a2a2a}
.collection-tab:hover:not(.active){background:#f9f7f5}
.collection-tab-add{padding:6px 12px;border-radius:6px;font-size:12px;color:#aaa;border:1px dashed #d0ccc8;cursor:pointer;background:transparent;white-space:nowrap}
.tabs-spacer{flex:1}
.save-indicator{font-size:11px;color:#aaa;display:flex;align-items:center;gap:5px;white-space:nowrap}
.save-indicator.saved{color:#10b981}
.settings-btn{display:flex;align-items:center;gap:6px;padding:6px 12px;border-radius:6px;font-size:12px;color:#666;background:#f9f7f5;border:.5px solid #e0dcd8;cursor:pointer;white-space:nowrap}
.body{display:flex;flex:1;overflow:hidden}
.left-column{flex:0 0 55%;border-right:.5px solid #e0dcd8;display:flex;flex-direction:column;overflow:hidden}
.right-column{flex:0 0 45%;display:flex;flex-direction:column;overflow:hidden}
.column-header{padding:16px 20px 12px;border-bottom:.5px solid #e0dcd8;flex-shrink:0}
.column-title{font-size:14px;font-weight:600;color:#2a2a2a}
.column-subtitle{font-size:12px;color:#999;margin-top:4px}
.table-container{flex:1;overflow-y:auto;padding:0 20px;scrollbar-width:thin;scrollbar-color:#ddd transparent}
.table{width:100%;border-collapse:collapse;margin-top:12px;font-size:13px}
.table th{background:transparent;padding:8px 0;text-align:left;font-weight:600;color:#666;border-bottom:.5px solid #e0dcd8;font-size:11px;text-transform:uppercase;letter-spacing:.3px}
.table td{padding:10px 0;border-bottom:.5px solid #f0ebe8;vertical-align:middle}
.table tr.nested td{padding-left:32px;border-left:2px solid #d8c5e8;font-size:12px}
.field-name{font-family:'Monaco','Menlo',monospace;font-size:12px;color:#2a2a2a;font-weight:500}
.field-type{font-family:'Monaco','Menlo',monospace;font-size:11px;color:#666}
.field-default{font-family:'Monaco','Menlo',monospace;font-size:11px;color:#888}
.field-default.italic{font-style:italic}
.badge-range td{background:#dbeafe10}
.badge-enum td{background:#fce7f310}
.badge-array td{background:#fef3c710}
.badge-object td{background:#e9d5ff10}
.drag-handle{color:#ccc;font-size:12px;cursor:grab;padding-right:8px}
.req-toggle{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:#999;cursor:pointer}
.req-toggle .dot{width:8px;height:8px;border-radius:50%;background:#ddd;display:inline-block}
.req-toggle.required{color:#0d9488}
.req-toggle.required .dot{background:#10b981}
.icon{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;color:#999;font-size:12px;cursor:pointer}
.icon.lock{color:#d4a574;cursor:default}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:4px}
.chip{background:#f3f1f0;color:#4a4a4a;padding:4px 10px;border-radius:12px;font-size:11px}
.chip-add{background:transparent;border:1px dashed #d0ccc8;color:#999}
.shuffler-chip{display:inline-flex;align-items:center;gap:4px;background:#fce7f3;color:#9f1239;padding:3px 9px;border-radius:10px;font-size:10px;font-family:'Monaco','Menlo',monospace}
.array-meta{font-size:11px;color:#888;margin-top:4px;font-family:'Monaco','Menlo',monospace}
.action-buttons{display:flex;gap:8px;padding:12px 20px;border-top:.5px solid #e0dcd8;flex-shrink:0;flex-wrap:wrap}
.btn-action{padding:7px 12px;background:#f9f7f5;border:.5px solid #e0dcd8;border-radius:6px;font-size:12px;color:#4a4a4a;cursor:pointer}
.btn-action:hover{background:#f0ebe8}
.preset-row{padding:10px 20px 12px;border-top:.5px solid #e0dcd8;flex-shrink:0}
.preset-row-label{font-size:11px;color:#999;text-transform:uppercase;letter-spacing:.3px;margin-bottom:8px}
.preset-chips{display:flex;gap:6px;flex-wrap:wrap}
.preset-chip{padding:5px 12px;border-radius:12px;font-size:11px;background:#eef2ff;color:#3730a3;cursor:pointer;font-family:'Monaco','Menlo',monospace}
.preset-chip:hover{background:#e0e7ff}
.preview-header{display:flex;justify-content:space-between;align-items:center;padding:16px 20px 12px;border-bottom:.5px solid #e0dcd8;flex-shrink:0}
.preview-title{font-size:14px;font-weight:600;color:#2a2a2a}
.preview-nav{display:flex;align-items:center;gap:8px;font-size:11px;color:#999}
.nav-arrow{width:22px;height:22px;border:none;background:#f9f7f5;border-radius:4px;cursor:pointer;color:#666;font-size:11px}
.nav-arrow:hover{background:#f0ebe8}
.preview-icons{display:flex;gap:8px}
.icon-btn{width:28px;height:28px;border:none;background:#f9f7f5;border-radius:4px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:#666;font-size:13px}
.icon-btn:hover{background:#f0ebe8}
.icon-btn.check{color:#10b981}
.code-block{flex:1;padding:16px 20px;overflow-y:auto;background:#f9f7f5;border-radius:6px;margin:12px 20px;font-family:'Monaco','Menlo',monospace;font-size:11px;line-height:1.6;scrollbar-width:thin;scrollbar-color:#ddd transparent;white-space:pre-wrap;word-break:break-word}
.code-key{color:#1e40af}
.code-string{color:#059669}
.code-number{color:#d97706}
.code-comment{color:#999}
.value-pool{margin:0 20px 12px;padding:12px 14px;background:#fce7f3;border-radius:6px;border:.5px solid #fbcfe8;flex-shrink:0}
.pool-title{font-size:12px;font-weight:600;color:#9f1239}
.pool-subtitle{font-size:11px;color:#be185d;margin-top:2px;margin-bottom:8px}
.shuffler-row{display:flex;flex-direction:column;gap:6px;margin-bottom:12px;padding-bottom:12px;border-bottom:.5px solid #fbcfe8}
.shuffler-top{display:flex;justify-content:space-between;align-items:baseline}
.shuffler-name{font-size:11px;font-weight:600;color:#9f1239}
.shuffler-value{font-size:11px;font-family:'Monaco','Menlo',monospace;color:#be185d}
.shuffler-slider{width:100%;accent-color:#be185d;height:4px;flex:1}
.shuffler-labels{display:flex;justify-content:space-between;font-size:10px;color:#be185d;opacity:.7}
.pool-chips{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
.pool-chip-row{display:flex;align-items:center;gap:8px;background:#fff;border-radius:12px;padding:4px 10px}
.pool-chip{font-size:11px;color:#be185d}
.pool-weight{width:38px;border:.5px solid #fbcfe8;border-radius:8px;font-size:10px;text-align:center;color:#be185d;font-family:'Monaco','Menlo',monospace;padding:2px 0;background:#fff}
.pool-meta{display:flex;gap:12px;font-size:11px;color:#be185d;align-items:center;flex-wrap:wrap}
.pool-csv-btn{background:#fff;border:.5px solid #fbcfe8;color:#be185d;padding:4px 10px;border-radius:12px;font-size:11px;cursor:pointer}
.output-link{color:#1e40af;cursor:pointer;text-decoration:underline;font-size:11px}
.output-link:hover{color:#1d4ed8}
.output-detail{font-family:'Monaco','Menlo',monospace;font-size:11px;color:#666;padding:8px 0 10px}
.output-viewer{background:#f9f7f5;border:.5px solid #e0dcd8;border-radius:6px;max-height:52vh;overflow:auto}
.ov-line{display:grid;grid-template-columns:56px 1fr;gap:10px;padding:2px 10px;cursor:pointer}
.ov-line:hover{background:#eef2ff}
.ov-ln{font-family:'Monaco','Menlo',monospace;font-size:11px;color:#9ca3af;text-align:right;user-select:none}
.ov-code{font-family:'Monaco','Menlo',monospace;font-size:12px;color:#2a2a2a;white-space:pre}
.gen-options{display:flex;align-items:center;gap:16px;padding:10px 20px;border-top:.5px solid #e0dcd8;font-size:12px;color:#666;flex-wrap:wrap;flex-shrink:0}
.gen-option{display:flex;align-items:center;gap:6px}
.checkbox-fake{width:14px;height:14px;border:.5px solid #d0ccc8;border-radius:3px;display:inline-block;position:relative;cursor:pointer;flex-shrink:0}
.checkbox-fake.checked{background:#2a2a2a;border-color:#2a2a2a}
.checkbox-fake.checked::after{content:"✓";color:#fff;font-size:10px;position:absolute;top:-2px;left:1px}
.seed-input{width:80px;padding:4px 8px;border:.5px solid #e0dcd8;border-radius:4px;font-family:'Monaco','Menlo',monospace;font-size:11px;background:#fff}
.target-select{display:flex;gap:4px;background:#f3f1f0;border-radius:6px;padding:2px}
.target-option{padding:4px 10px;border-radius:5px;font-size:11px;color:#888;cursor:pointer}
.target-option.active{background:#fff;color:#2a2a2a;font-weight:500;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.action-bar{display:flex;align-items:center;justify-content:space-between;padding:14px 20px;border-top:.5px solid #e0dcd8;flex-shrink:0}
.docs-input{display:flex;align-items:center;gap:8px}
.docs-label{font-size:12px;color:#666;font-weight:500}
.docs-number{width:70px;padding:6px 10px;border:.5px solid #e0dcd8;border-radius:4px;font-family:'Monaco','Menlo',monospace;font-size:12px;text-align:center;background:#fff}
.status-section{flex:1;text-align:center}
.status-text{font-size:12px;color:#666}
.progress-container{display:flex;align-items:center;gap:8px;margin-top:6px;justify-content:center}
.progress-bar{width:200px;height:4px;background:#e0dcd8;border-radius:2px;overflow:hidden}
.progress-fill{height:100%;background:#10b981;transition:width .2s}
.progress-percent{font-size:12px;color:#666;min-width:28px;text-align:right}
.btn-generate{padding:8px 18px;background:#2a2a2a;color:#fff;border:none;border-radius:6px;font-size:12px;font-weight:500;cursor:pointer;display:flex;align-items:center;gap:6px}
.btn-generate:hover{background:#1a1a1a}
.btn-generate:disabled{background:#999;cursor:not-allowed}
.btn-pause{padding:8px 14px;background:#f9f7f5;border:.5px solid #e0dcd8;border-radius:6px;font-size:12px;color:#4a4a4a;cursor:pointer}
.btn-cli{padding:8px 14px;background:#f9f7f5;border:.5px solid #e0dcd8;border-radius:6px;font-size:12px;color:#4a4a4a;cursor:pointer;font-family:'Monaco','Menlo',monospace}
.bar-right{display:flex;gap:8px}
.modal-overlay{position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(42,42,42,.35);display:flex;align-items:center;justify-content:center;border-radius:10px;z-index:10}
.modal-dialog{background:#fff;border:.5px solid #e0dcd8;border-radius:10px;width:560px;max-width:90%;box-shadow:0 12px 32px rgba(0,0,0,.18)}
.modal-header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:.5px solid #e0dcd8}
.modal-title{font-size:14px;font-weight:600;color:#2a2a2a}
.modal-subtitle{font-size:12px;color:#999;margin-top:2px}
.modal-close{width:26px;height:26px;border:none;background:#f9f7f5;border-radius:4px;cursor:pointer;color:#666;font-size:13px}
.modal-close:hover{background:#f0ebe8}
.modal-body{padding:18px}
.modal-code{background:#f9f7f5;border:.5px solid #e0dcd8;border-radius:6px;padding:14px 16px;font-family:'Monaco','Menlo',monospace;font-size:12px;line-height:1.7;color:#2a2a2a;overflow-x:auto;white-space:pre}
.modal-code .flag{color:#1e40af}
.modal-code .val{color:#059669}
.modal-code .cont{color:#999}
.modal-foot{display:flex;justify-content:space-between;align-items:center;margin-top:12px;font-size:11px;color:#999}
.modal-copy{display:flex;align-items:center;gap:6px;padding:7px 14px;background:#2a2a2a;color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer}
.modal-copy:hover{background:#1a1a1a}
.status-ok{color:#10b981;font-size:12px;font-weight:500}
.schema-header,.schema-row{display:grid;grid-template-columns:20px 1fr 140px 110px 80px 24px;gap:6px;align-items:center;padding:8px 0}
.schema-header{font-size:11px;text-transform:uppercase;color:#666;font-weight:600;letter-spacing:.3px;border-bottom:.5px solid #e0dcd8}
.schema-row{border-bottom:.5px solid #f0ebe8;cursor:pointer}
.schema-row.nested-row{grid-template-columns:20px 1fr 140px 110px 80px 24px;padding-left:32px;border-left:2px solid #d8c5e8;font-size:12px}
.shuffler-inline{display:flex;align-items:center;gap:4px}
.shuffler-inline input[type=range]{width:68px;accent-color:#6b5b95;height:3px;cursor:pointer}
.shuffler-inline .shuf-val{font-size:10px;font-family:'Monaco','Menlo',monospace;color:#6b5b95;min-width:18px}
.schema-row:hover{background:#fafaf9}
.schema-row.selected{background:#f0f0ff}
.schema-row.selected:hover{background:#eaeaff}
.detail-panel{margin:0 20px 12px;padding:12px 14px;background:#f9f7f5;border-radius:6px;border:.5px solid #e0dcd8;flex-shrink:0}
.detail-title{font-size:12px;font-weight:600;color:#4a4a4a;margin-bottom:10px}
.detail-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.detail-row:last-child{margin-bottom:0}
.detail-label{font-size:11px;color:#888;white-space:nowrap}
.detail-input{padding:4px 8px;border:.5px solid #e0dcd8;border-radius:4px;font-family:'Monaco','Menlo',monospace;font-size:11px;background:#fff;width:80px}
.detail-select{padding:4px 8px;border:.5px solid #e0dcd8;border-radius:4px;font-size:11px;background:#fff;color:#4a4a4a}
.detail-shuffler{width:140px;accent-color:#6b5b95;height:4px}
.detail-shuffler-val{font-size:11px;font-family:'Monaco','Menlo',monospace;color:#6b5b95;min-width:28px}
.cell-name .q-field{font-family:'Monaco','Menlo',monospace!important;font-size:12px!important}
.cell-name .q-field__native{font-family:'Monaco','Menlo',monospace!important;font-size:12px!important;color:#2a2a2a!important;padding:0!important}
.cell-name .q-field--borderless .q-field__control{padding:0!important;min-height:24px!important}
.cell-type{font-family:'Monaco','Menlo',monospace;font-size:11px;color:#666}
.cell-req{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:#999;cursor:pointer;user-select:none}
.cell-req .dot{width:8px;height:8px;border-radius:50%;background:#ddd;display:inline-block;flex-shrink:0}
.cell-req.required{color:#0d9488}
.cell-req.required .dot{background:#10b981}
.cell-del{color:#ccc;font-size:14px;cursor:pointer;text-align:center}
.cell-del:hover{color:#e05c5c}
</style>
<script>
document.addEventListener('input', function(e) {
    if (e.target && e.target.id === 'shuf-slider') {
        var s = e.target.nextElementSibling;
        if (s) s.textContent = e.target.value;
    }
});
</script>"""

QUICK_ADD_PRESETS = [
    ("full_name",      {"type": "String", "faker": "fullName"}),
    ("email",          {"type": "String", "faker": "email"}),
    ("phone",          {"type": "String", "faker": "phone"}),
    ("date_of_birth",  {"type": "Range",  "min": -20000, "max": -6000}),
    ("uuid",           {"type": "String", "faker": "uuid"}),
    ("created_at",     {"type": "String", "faker": "date"}),
    ("street_address", {"type": "String", "faker": "street"}),
    ("company",        {"type": "String", "faker": "companyName"}),
]

# ── Page ──────────────────────────────────────────────────────────────────────

@ui.page("/")
def index():
    global current_col, preview_docs, preview_index
    global is_generating, progress_current

    ui.add_head_html(APP_CSS)

    saved_label_ref: list = []   # [label_element]
    output_dialog_ref: list = []
    output_path_ref: list = []
    output_detail_ref: list = []
    output_lines_ref: list = []
    output_page_ref: list = []
    output_meta = {"line_count": 1, "documents": 0, "lines": [], "page": 0, "page_size": 400}

    # ── Refreshable sections ──────────────────────────────────────────────────

    @ui.refreshable
    def render_tabs():
        for col in collections:
            active = "active" if col == current_col else ""
            ui.html(f'<button class="collection-tab {active}">{col}</button>') \
                .on("click", lambda c=col: switch_collection(c))
        ui.html('<button class="collection-tab-add">+ Collection</button>') \
            .on("click", add_collection)
        ui.html('<div class="tabs-spacer"></div>')
        saved_lbl = ui.html('<div class="save-indicator saved">● saved</div>')
        saved_label_ref.clear()
        saved_label_ref.append(saved_lbl)
        ui.html('<button class="settings-btn">⚙ Output</button>') \
            .on("click", open_settings_dialog)

    @ui.refreshable
    def render_col_header():
        with ui.element("div").style("display:flex;justify-content:space-between;align-items:flex-start"):
            ui.html(f'''
                <div>
                    <div class="column-title">Schema fields</div>
                    <div class="column-subtitle">collection: {current_col}</div>
                </div>
            ''')
            with ui.row().style("gap:8px"):
                ui.html('<button class="btn-action">Import JSON</button>') \
                    .on("click", open_import_json_dialog)
                ui.html('<button class="btn-action">+ Field</button>') \
                    .on("click", lambda: add_field_of_type("String"))

    @ui.refreshable
    def render_schema_table():
        fields = cur_fields()

        def render_row(field, nested: bool = False):
            locked = field.get("locked", False)
            fid    = field["id"]
            req    = field.get("required", False)
            row_cls = "schema-row nested-row" if nested else "schema-row"

            with ui.element("div").classes(row_cls) \
                    .on("input", lambda e, f=field: _handle_row_input(e, f["id"])):
                # drag handle / indent spacer
                if locked:
                    ui.html('<span style="width:20px"></span>')
                else:
                    ui.html('<span class="drag-handle">⠿</span>')

                # field name — editable input
                with ui.element("div").classes("cell-name"):
                    if locked:
                        ui.html(f'<span class="field-name">{field["name"]}</span>')
                    else:
                        inp = ui.input(value=field["name"]).props("dense borderless") \
                                 .style("font-family:'Monaco','Menlo',monospace;font-size:12px;width:100%")
                        inp.on("blur",
                               lambda e, f=field: update_field_prop(f["id"], "name", e.sender.value))

                # type dropdown
                with ui.element("div").classes("cell-type"):
                    if locked:
                        ui.html(type_label(field))
                    else:
                        canonical = _TYPE_LOOKUP.get(field["type"].lower(), field["type"])

                        def _on_type_change(e, f=field):
                            raw_value = getattr(e, "value", None)
                            if raw_value is None and hasattr(e, "sender"):
                                raw_value = getattr(e.sender, "value", None)
                            if raw_value is None:
                                raw_value = e.args
                            chosen_type = _normalize_type_value(raw_value)
                            chosen_type = _TYPE_LOOKUP.get(chosen_type.lower(), chosen_type) if isinstance(chosen_type, str) else None
                            changed = _change_type(f["id"], chosen_type)
                            render_schema_table.refresh()
                            if changed and chosen_type == "Range":
                                open_range_dialog(f["id"])

                        with ui.row().style("gap:4px;align-items:center;flex-wrap:nowrap"):
                            ui.select(TYPE_OPTIONS, value=canonical) \
                              .props("dense borderless options-dense") \
                              .style("font-family:'Monaco','Menlo',monospace;font-size:11px;color:#666;min-width:110px") \
                              .on("update:model-value", _on_type_change)
                            if field["type"] == "Range":
                                ui.button("Set", on_click=lambda f=field: open_range_dialog(f["id"])) \
                                  .props("flat dense no-caps") \
                                  .style("font-size:10px;color:#4b5563;min-width:34px;height:24px;padding:0 6px")
                                                        if field["type"] == "Array":
                                                                ui.html('<span class="chip" style="margin-left:6px;cursor:pointer">⚙ Array</span>') \
                                                                    .on("click", lambda f=field: open_array_settings_dialog(f["id"]))

                # shuffler slider (inline)
                sh = field.get("shuffler", 1)
                if locked:
                    ui.html('<span></span>')
                else:
                    ui.html(
                        f'<div class="shuffler-inline">'
                        f'<input type="range" id="shuf-slider" data-fid="{fid}" min="1" max="50" value="{sh}">'
                        f'<span class="shuf-val">{sh}</span>'
                        f'</div>'
                    )

                # required toggle
                req_cls = "cell-req required" if req else "cell-req"
                req_lbl = "required" if req else "optional"
                tog = ui.html(
                    f'<span class="{req_cls}"><span class="dot"></span>{req_lbl}</span>'
                )
                if not locked:
                    tog.on("click", lambda f=field: toggle_required(f["id"]))

                # delete
                if locked:
                    ui.html('<span class="icon lock" style="font-size:13px">🔒</span>')
                else:
                    ui.html('<span class="cell-del">✕</span>') \
                      .on("click", lambda f=field: delete_field(f["id"]))

        # Header
        ui.html('''
        <div class="schema-header">
            <span></span>
            <span>Field name</span>
            <span>Type</span>
            <span>Shuffler</span>
            <span>Required</span>
            <span></span>
        </div>''')

        for field in fields:
            render_row(field)
            if field["type"] == "Object":
                for sf in field.get("fields", []):
                    render_row(sf, nested=True)
                ui.html(
                    f'<div class="schema-row nested-row" style="padding-left:32px;border-left:2px solid #d8c5e8">'
                    f'<span></span>'
                    f'<span class="chip chip-add" style="cursor:pointer" '
                    f'data-parent="{field["id"]}">+ add nested field</span>'
                    f'</div>'
                ).on("click", lambda f=field: add_nested_field(f["id"]))

    @ui.refreshable
    def render_preview():
        if not preview_docs:
            return
        doc = preview_docs[preview_index]
        html_body = json_to_html(doc)
        ui.html(f'<div class="code-block">{html_body}</div>')


    @ui.refreshable
    def render_gen_options():
        clear_cls = "checked" if gen_settings["clear_first"] else ""
        pymongo_cls = "checked" if gen_settings["load_pymongo"] else ""
        mongoimport_cls = "checked" if gen_settings["load_mongoimport"] else ""
        seed_val  = gen_settings["seed"]
        fname     = OUTPUT_FILENAME.replace("{collection}", current_col)
        out_path  = str(OUTPUT_DIR / fname).replace("\\", "/")
        atlas_status = atlas_uri_status_label()

        opt_html = f'''
        <div class="gen-option">
            <span class="checkbox-fake {clear_cls}" id="clear-chk"></span>
            <span>Overwrite existing file</span>
        </div>
        <div class="gen-option">
            <span>Seed</span>
            <input class="seed-input" value="{seed_val}" id="seed-input" type="number">
        </div>
        <div class="gen-option" style="color:#aaa;font-family:'Monaco','Menlo',monospace;font-size:11px">
            → {out_path}
        </div>
        <div class="gen-option" style="font-family:'Monaco','Menlo',monospace;font-size:11px;color:#666">
            Atlas URI: {atlas_status} (open Output settings)
        </div>
        <div class="gen-option">
            <span class="checkbox-fake {mongoimport_cls}" id="load-mongoimport-chk"></span>
            <span>Load via mongoimport</span>
        </div>
        <div class="gen-option">
            <span class="checkbox-fake {pymongo_cls}" id="load-pymongo-chk"></span>
            <span>Load via pymongo</span>
        </div>'''

        opt_el = ui.html(opt_html)
        opt_el.on("click",  handle_gen_option_click)
        opt_el.on("change", handle_seed_change)
        ui.html('<span class="output-link">View output</span>').on("click", lambda: open_output_viewer_page())

    @ui.refreshable
    def render_action_bar():
        count = gen_settings["count"]
        pct   = int((progress_current / count) * 100) if is_generating and count else 0

        if is_generating:
            status_html = (
                f'<div class="status-text">Generating documents · {progress_current:,} / {count:,}</div>'
                f'<div class="progress-container">'
                f'<div class="progress-bar"><div class="progress-fill" style="width:{pct}%"></div></div>'
                f'<div class="progress-percent">{pct}%</div></div>'
            )
        else:
            done_count = progress_current if progress_current > 0 else 0
            status_html = (
                f'<div class="status-text status-ok">✓ {done_count:,} documents generated</div>'
                if done_count else
                '<div class="status-text">Ready to generate</div>'
            )

        docs_el = ui.html(
            f'<div class="docs-input">'
            f'<span class="docs-label">Documents</span>'
            f'<input type="number" class="docs-number" value="{count}" id="docs-count" min="1" max="100000">'
            f'</div>'
        )
        docs_el.on("change", handle_count_change)

        ui.html(f'<div class="status-section" style="flex:1;text-align:center">{status_html}</div>')

    # ── Settings dialog ───────────────────────────────────────────────────────

    def open_array_settings_dialog(fid: int):
        field = find_field(fid)
        if not field or field.get("type") != "Array":
            return
        with ui.dialog().props("persistent") as dlg:
            with ui.element("div").style(
                "width:520px;max-width:90vw;background:#fff;border-radius:10px;"
                "border:.5px solid #e0dcd8;box-shadow:0 12px 32px rgba(0,0,0,.18);"
                "display:flex;flex-direction:column;overflow:hidden"
            ):
                with ui.element("div").style(
                    "display:flex;justify-content:space-between;align-items:center;"
                    "padding:14px 18px;border-bottom:.5px solid #e0dcd8"
                ):
                    ui.html(f'<div class="modal-title">Array settings · {field.get("name", "field")}</div>')
                    ui.button("✕", on_click=dlg.close).props("flat dense round") \
                        .style("color:#666;font-size:13px;min-width:28px;height:28px")

                with ui.element("div").style("padding:18px;display:flex;flex-direction:column;gap:12px"):
                    ui.html('<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.3px;font-weight:600">Element type</div>')
                    element_type = ui.select(
                        ARRAY_ELEMENT_TYPE_OPTIONS,
                        value=_array_element_type_default(field),
                    ).props("outlined dense") \
                     .style("width:100%;font-family:'Monaco','Menlo',monospace;font-size:12px")

                    ui.html('<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.3px;font-weight:600">Size</div>')
                    size_inp = ui.input(value=str(_array_size_default(field))) \
                        .props("outlined dense type=number") \
                        .style("width:100%;font-family:'Monaco','Menlo',monospace;font-size:12px")

                    seed_default = ", ".join(str(v) for v in field.get("seed_values", []))
                    ui.html('<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.3px;font-weight:600">Seed values (comma-separated)</div>')
                    seed_values_inp = ui.input(value=seed_default, placeholder="a, b, c") \
                        .props("outlined dense") \
                        .style("width:100%;font-family:'Monaco','Menlo',monospace;font-size:12px")

                    randomize_default = bool(field.get("seed_randomize", False))
                    randomize_seed_chk = ui.checkbox("Randomize seed values", value=randomize_default) \
                        .style("font-size:12px;color:#555")

                with ui.element("div").style("display:flex;justify-content:flex-end;gap:8px;padding:12px 18px 18px"):
                    ui.button("Cancel", on_click=dlg.close).props("flat no-caps") \
                        .style("color:#666;font-size:12px")

                    def save_array_settings():
                        arr = find_field(fid)
                        if not arr or arr.get("type") != "Array":
                            dlg.close()
                            return

                        try:
                            size = max(0, int(float((size_inp.value or "1").strip())))
                        except ValueError:
                            size = 1

                        arr["element_type"] = element_type.value or "String"
                        arr["size"] = size
                        raw_seed_values = (seed_values_inp.value or "").strip()
                        if raw_seed_values:
                            arr["seed_values"] = [
                                token.strip() for token in raw_seed_values.split(",") if token.strip()
                            ]
                            arr["seed_randomize"] = bool(randomize_seed_chk.value)
                        else:
                            arr.pop("seed_values", None)
                            arr.pop("seed_randomize", None)
                        # Remove legacy keys from older schema format.
                        arr.pop("element_faker", None)
                        arr.pop("min_items", None)
                        arr.pop("max_items", None)
                        arr["cardinality"] = str(size)
                        _auto_save()
                        render_schema_table.refresh()
                        dlg.close()

                    ui.button("Save", on_click=save_array_settings).props("no-caps unelevated") \
                        .style("background:#2a2a2a;color:#fff;border-radius:6px;font-size:12px;padding:7px 18px;box-shadow:none")
        dlg.open()

    def open_settings_dialog():
        global OUTPUT_DIR, OUTPUT_FILENAME, ATLAS_URI, ATLAS_DB
        with ui.dialog().props("persistent") as dlg:
            with ui.element("div").style(
                "width:480px;max-width:90vw;background:#fff;border-radius:10px;"
                "border:.5px solid #e0dcd8;box-shadow:0 12px 32px rgba(0,0,0,.18);"
                "display:flex;flex-direction:column;overflow:hidden;max-height:85vh"
            ):
                with ui.element("div").style(
                    "display:flex;justify-content:space-between;align-items:center;"
                    "padding:14px 18px;border-bottom:.5px solid #e0dcd8"
                ):
                    ui.html('<div class="modal-title">Output settings</div>')
                    ui.button("✕", on_click=dlg.close).props("flat dense round") \
                        .style("color:#666;font-size:13px;min-width:28px;height:28px")

                with ui.element("div").style("padding:18px;display:flex;flex-direction:column;gap:14px;overflow:auto"):
                    ui.html('<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.3px;font-weight:600">Output directory</div>')
                    with ui.element("div").style("display:flex;gap:8px;align-items:center"):
                        dir_inp = ui.input(value=str(OUTPUT_DIR)).props("outlined dense") \
                            .style("flex:1;font-family:'Monaco','Menlo',monospace;font-size:12px")

                        def browse_dir():
                            import tkinter as tk
                            from tkinter import filedialog

                            root = tk.Tk()
                            root.withdraw()
                            root.wm_attributes("-topmost", 1)
                            chosen = filedialog.askdirectory(
                                title="Select output directory",
                                initialdir=dir_inp.value or str(OUTPUT_DIR),
                            )
                            root.destroy()
                            if chosen:
                                dir_inp.set_value(chosen)

                        ui.button("Browse…", on_click=browse_dir).props("no-caps unelevated") \
                            .style("background:#f3f1f0;color:#4a4a4a;border:.5px solid #e0dcd8;"
                                   "border-radius:6px;font-size:12px;padding:7px 12px;box-shadow:none;white-space:nowrap")

                    ui.html('<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.3px;font-weight:600;margin-top:4px">Filename pattern</div>')
                    ui.html('<div style="font-size:11px;color:#aaa;margin-bottom:4px">Use <code style="background:#f3f1f0;padding:1px 5px;border-radius:3px">{collection}</code> as a placeholder for the collection name</div>')
                    name_inp = ui.input(value=OUTPUT_FILENAME).props("outlined dense") \
                        .style("width:100%;font-family:'Monaco','Menlo',monospace;font-size:12px")

                    ui.html('<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.3px;font-weight:600;margin-top:4px">Atlas connection string (optional)</div>')
                    ui.html('<div style="font-size:11px;color:#aaa;margin-bottom:4px">Used for generated mongoimport and pymongo helper commands in the CLI modal.</div>')
                    atlas_inp = ui.input(
                        value=ATLAS_URI,
                        placeholder="mongodb+srv://user:pass@cluster.example.mongodb.net/?retryWrites=true&w=majority",
                    ).props("outlined dense") \
                        .style("width:100%;font-family:'Monaco','Menlo',monospace;font-size:12px")

                    ui.html('<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.3px;font-weight:600;margin-top:4px">Atlas database name (optional)</div>')
                    ui.html('<div style="font-size:11px;color:#aaa;margin-bottom:4px">Used by Data Load. If empty, the database in your URI is used, otherwise test.</div>')
                    atlas_db_inp = ui.input(value=ATLAS_DB, placeholder="sample_mflix") \
                        .props("outlined dense") \
                        .style("width:100%;font-family:'Monaco','Menlo',monospace;font-size:12px")

                with ui.element("div").style(
                    "display:flex;justify-content:flex-end;gap:8px;padding:12px 18px 18px"
                ):
                    ui.button("Cancel", on_click=dlg.close).props("flat no-caps") \
                        .style("color:#666;font-size:12px")
                    def save_settings():
                        global OUTPUT_DIR, OUTPUT_FILENAME, ATLAS_URI, ATLAS_DB
                        new_dir = Path(dir_inp.value.strip()) if dir_inp.value.strip() else OUTPUT_DIR
                        new_dir.mkdir(parents=True, exist_ok=True)
                        OUTPUT_DIR = new_dir
                        OUTPUT_FILENAME = name_inp.value.strip() or "{collection}.json"
                        ATLAS_URI = (atlas_inp.value or "").strip()
                        ATLAS_DB = (atlas_db_inp.value or "").strip()
                        render_gen_options.refresh()
                        dlg.close()
                    ui.button("Save", on_click=save_settings).props("no-caps unelevated") \
                        .style("background:#2a2a2a;color:#fff;border-radius:6px;font-size:12px;padding:7px 18px;box-shadow:none")
        dlg.open()

    def open_import_json_dialog():
        selected_path = {"value": ""}
        pending_upload = {"payload": None, "name": ""}

        def import_payload(payload, source_name: str):
            doc = None
            if isinstance(payload, dict):
                doc = payload
            elif isinstance(payload, list):
                doc = next((x for x in payload if isinstance(x, dict)), None)

            if doc is None:
                ui.notify("JSON must be an object or an array containing at least one object", color="warning")
                return

            schemas[current_col] = _infer_fields_from_document(doc)
            _auto_save()

            preview_docs.clear()
            preview_docs.append(doc)
            render_schema_table.refresh()
            render_preview.refresh()

            ui.notify(f"Imported schema from {source_name}", color="positive")

        with ui.dialog().props("persistent") as dlg:
            with ui.element("div").style(
                "width:560px;max-width:92vw;background:#fff;border-radius:10px;"
                "border:.5px solid #e0dcd8;box-shadow:0 12px 32px rgba(0,0,0,.18);"
                "display:flex;flex-direction:column;overflow:hidden"
            ):
                with ui.element("div").style(
                    "display:flex;justify-content:space-between;align-items:center;"
                    "padding:14px 18px;border-bottom:.5px solid #e0dcd8"
                ):
                    ui.html('<div class="modal-title">Import schema from JSON</div>')
                    ui.button("✕", on_click=dlg.close).props("flat dense round") \
                        .style("color:#666;font-size:13px;min-width:28px;height:28px")

                with ui.element("div").style("padding:18px;display:flex;flex-direction:column;gap:12px"):
                    ui.html('<div style="font-size:12px;color:#777">Upload a JSON file (or provide a local path). The first object will be used to infer field types.</div>')

                    def _read_upload_text(e) -> str:
                        content = getattr(e, "content", None)
                        if content is None:
                            raise ValueError("Uploaded file content is empty")
                        if isinstance(content, (bytes, bytearray)):
                            return bytes(content).decode("utf-8")
                        if hasattr(content, "read"):
                            if hasattr(content, "seek"):
                                try:
                                    content.seek(0)
                                except Exception:
                                    pass
                            raw = content.read()
                            if (raw is None or raw == b"" or raw == "") and hasattr(content, "getvalue"):
                                try:
                                    raw = content.getvalue()
                                except Exception:
                                    raw = raw
                            if isinstance(raw, bytes):
                                if not raw and hasattr(content, "name") and content.name:
                                    try:
                                        raw = Path(content.name).read_bytes()
                                    except Exception:
                                        pass
                                return raw.decode("utf-8")
                            if (raw is None or raw == "") and hasattr(content, "name") and content.name:
                                try:
                                    return Path(content.name).read_text(encoding="utf-8")
                                except Exception:
                                    pass
                            return str(raw)
                        return str(content)

                    async def handle_upload(e):
                        try:
                            uploaded_file = getattr(e, "file", None)
                            if uploaded_file is not None:
                                payload = await uploaded_file.json()
                                source_name = uploaded_file.name or "uploaded file"
                            else:
                                payload = json.loads(_read_upload_text(e))
                                source_name = getattr(e, "name", "uploaded file")
                        except Exception as exc:
                            ui.notify(f"Failed to parse JSON: {exc}", color="negative")
                            return
                        pending_upload["payload"] = payload
                        pending_upload["name"] = source_name
                        ui.notify(f"Loaded {source_name}. Click Import to apply.", color="info")

                    ui.upload(on_upload=handle_upload, auto_upload=True, max_files=1) \
                        .props("accept=.json") \
                        .style("border:.5px dashed #d0ccc8;border-radius:8px;padding:8px")

                    ui.html('<div style="font-size:11px;color:#aaa">or import by local file path</div>')
                    with ui.element("div").style("display:flex;gap:8px;align-items:center"):
                        file_inp = ui.input(placeholder="/path/to/file.json").props("outlined dense") \
                            .style("flex:1;font-family:'Monaco','Menlo',monospace;font-size:12px")
                        file_inp.on("change", lambda e: selected_path.update({"value": e.sender.value or ""}))

                with ui.element("div").style("display:flex;justify-content:flex-end;gap:8px;padding:12px 18px 18px"):
                    ui.button("Cancel", on_click=dlg.close).props("flat no-caps") \
                        .style("color:#666;font-size:12px")

                    def do_import():
                        if pending_upload.get("payload") is not None:
                            import_payload(pending_upload["payload"], pending_upload.get("name") or "uploaded file")
                            dlg.close()
                            return

                        path_text = (selected_path.get("value") or file_inp.value or "").strip().strip('"').strip("'")
                        if not path_text:
                            ui.notify("Upload a JSON file or provide a file path first", color="warning")
                            return
                        path = Path(path_text).expanduser()
                        if not path.is_absolute():
                            path = (Path(__file__).parent / path).resolve()
                        if not path.exists() or not path.is_file():
                            ui.notify(f"File not found: {path}", color="negative")
                            return
                        try:
                            payload = json.loads(path.read_text(encoding="utf-8"))
                        except Exception as exc:
                            ui.notify(f"Failed to parse JSON: {exc}", color="negative")
                            return

                        import_payload(payload, path.name)
                        dlg.close()

                    ui.button("Import", on_click=do_import).props("no-caps unelevated") \
                        .style("background:#2a2a2a;color:#fff;border-radius:6px;font-size:12px;padding:7px 18px;box-shadow:none")

        dlg.open()

    # ── CLI modal ─────────────────────────────────────────────────────────────

    def open_cli_modal():
        cmd_html = build_cli_html()
        connection_html = build_connection_help_html()
        plain_cmd = (
            f"mongodocgen generate \\\n"
            f"  --collection {current_col} \\\n"
            f"  --schema schemas/{current_col}.json \\\n"
            f"  --count {gen_settings['count']} \\\n"
            f"  --seed {gen_settings['seed']} \\\n"
            f"  --output output/{current_col}.json"
            + ("\\\n  --overwrite" if gen_settings["clear_first"] else "")
        )
        plain_cmd += build_connection_help_text()

        with ui.dialog().props("persistent") as dlg:
            with ui.element("div").style(
                "width:560px;max-width:90vw;background:#fff;border-radius:10px;"
                "border:.5px solid #e0dcd8;box-shadow:0 12px 32px rgba(0,0,0,.18);"
                "display:flex;flex-direction:column;overflow:hidden"
            ):
                # header
                with ui.element("div").style(
                    "display:flex;justify-content:space-between;align-items:center;"
                    "padding:14px 18px;border-bottom:.5px solid #e0dcd8;flex-shrink:0"
                ):
                    ui.html('''
                        <div>
                            <div class="modal-title">Run from the command line</div>
                            <div class="modal-subtitle">Equivalent to clicking Generate with the current settings</div>
                        </div>
                    ''')
                    ui.button("✕", on_click=dlg.close) \
                        .props("flat dense round") \
                        .style("color:#666;font-size:13px;min-width:28px;height:28px")
                # code block
                ui.html(f'<div style="padding:18px 18px 0"><div class="modal-code">{cmd_html}</div></div>')
                ui.html(f'<div style="padding:0 18px 0">{connection_html}</div>')
                # footer
                with ui.element("div").style(
                    "display:flex;justify-content:space-between;align-items:center;"
                    "padding:12px 18px 18px"
                ):
                    ui.html('<span style="font-size:11px;color:#999">Updates automatically as you change settings</span>')
                    ui.button("📋 Copy commands", on_click=lambda: ui.run_javascript(
                        f"navigator.clipboard.writeText({json.dumps(plain_cmd)}).catch(()=>{{}})", timeout=5
                    )).props("no-caps unelevated") \
                      .style("background:#2a2a2a;color:#fff;border-radius:6px;font-size:12px;"
                             "padding:7px 14px;box-shadow:none")
        dlg.open()

    # ── Event handlers ────────────────────────────────────────────────────────

    def switch_collection(col: str):
        global current_col, preview_docs, preview_index
        current_col = col
        preview_docs = []
        preview_index = 0
        render_tabs.refresh()
        render_col_header.refresh()
        render_schema_table.refresh()
        render_preview.refresh()

    def add_collection():
        with ui.dialog() as dlg, ui.card().style("padding:20px;min-width:300px;background:#fff"):
            ui.label("New collection name").style("font-size:14px;font-weight:600;margin-bottom:12px")
            name_inp = ui.input(placeholder="collection_name") \
                .props("outlined dense").style("width:100%")
            with ui.row().style("gap:8px;margin-top:12px;justify-content:flex-end"):
                ui.button("Cancel", on_click=dlg.close).props("flat")
                def do_add():
                    n = (name_inp.value or "").strip().replace(" ", "_")
                    if n and n not in collections:
                        import copy as _copy
                        collections.append(n)
                        schemas[n] = _copy.deepcopy(DEFAULT_FIELDS)
                        save_schema(n, schemas[n])
                        dlg.close()
                        switch_collection(n)
                ui.button("Create", on_click=do_add).props("unelevated color=dark")
        dlg.open()

    def toggle_required(fid: int):
        field = find_field(fid)
        if field:
            field["required"] = not field.get("required", False)
            _auto_save()
            render_schema_table.refresh()

    def delete_field(fid: int, parent_id: int | None = None):
        fields = cur_fields()
        if parent_id is not None:
            parent = find_field(parent_id)
            if parent:
                parent["fields"] = [f for f in parent.get("fields", []) if f["id"] != fid]
        else:
            schemas[current_col] = [f for f in fields if f["id"] != fid]
        _auto_save()
        render_schema_table.refresh()

    def handle_gen_option_click(e):
        args = e.args or {}
        target = args.get("target", {}) if isinstance(args, dict) else {}
        el_id = target.get("id", "")
        if el_id == "clear-chk":
            gen_settings["clear_first"] = not gen_settings["clear_first"]
            render_gen_options.refresh()
        elif el_id == "load-mongoimport-chk":
            gen_settings["load_mongoimport"] = not gen_settings["load_mongoimport"]
            render_gen_options.refresh()
        elif el_id == "load-pymongo-chk":
            gen_settings["load_pymongo"] = not gen_settings["load_pymongo"]
            render_gen_options.refresh()
        elif el_id == "view-output-link":
            open_output_viewer_dialog()

    def handle_seed_change(e):
        args = e.args or {}
        target = args.get("target", {}) if isinstance(args, dict) else {}
        if target.get("id") == "seed-input":
            try:
                gen_settings["seed"] = int(float(target.get("value", 42)))
            except ValueError:
                pass

    def handle_count_change(e):
        args = e.args or {}
        target = args.get("target", {}) if isinstance(args, dict) else {}
        if target.get("id") == "docs-count":
            try:
                gen_settings["count"] = max(1, int(float(target.get("value", 1000))))
            except ValueError:
                pass



    def _handle_row_input(e, fid: int):
        args   = e.args or {}
        target = args.get("target", {}) if isinstance(args, dict) else {}
        if target.get("id") != "shuf-slider":
            return
        try:
            sh = int(float(target.get("value", 1)))
        except ValueError:
            return
        field = find_field(fid)
        if not field:
            return
        field["shuffler"] = sh
        if field["type"] == "Enum":
            field["weights"] = shuffler_weights(field["values"], sh)
        _auto_save()

    def do_generate():
        global is_generating, progress_current, preview_docs, preview_index
        if is_generating:
            return
        fields  = cur_fields()
        count   = gen_settings["count"]
        seed    = gen_settings["seed"]
        clear   = gen_settings["clear_first"]

        is_generating   = True
        progress_current = 0
        render_action_bar.refresh()

        # Generate in chunks, updating progress
        CHUNK = max(1, min(count // 20, 500))
        all_docs: list[dict] = []
        random.seed(seed)
        from faker import Faker as _Faker; _Faker.seed(seed)

        from faker_fields import _gen_value

        def run_chunks():
            global is_generating, progress_current
            remaining = count
            first_chunk = True
            while remaining > 0:
                batch_size = min(CHUNK, remaining)
                batch = [{f["name"]: _gen_value(f) for f in fields} for _ in range(batch_size)]
                all_docs.extend(batch)
                remaining -= batch_size
                progress_current = count - remaining
                render_action_bar.refresh()
                if first_chunk:
                    preview_docs.clear()
                    preview_docs.extend(all_docs[:5])
                    preview_index = 0
                    render_preview.refresh()
                    first_chunk = False

            fname = OUTPUT_FILENAME.replace("{collection}", current_col)
            out_path = OUTPUT_DIR / fname
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(all_docs, f, indent=2, default=str)
            is_generating = False
            render_action_bar.refresh()

        import threading
        import contextvars
        ctx = contextvars.copy_context()
        t = threading.Thread(target=lambda: ctx.run(run_chunks), daemon=True)
        t.start()

    def do_data_load():
        uri = ATLAS_URI.strip()
        if not uri:
            ui.notify("Set Atlas connection string in Output settings before Data Load", color="warning")
            return

        if not (gen_settings["load_mongoimport"] or gen_settings["load_pymongo"]):
            ui.notify("Select at least one load method: mongoimport or pymongo", color="warning")
            return

        if gen_settings["load_mongoimport"] and shutil.which("mongoimport") is None:
            ui.notify("mongoimport binary not found in PATH", color="negative")
            return

        fname = OUTPUT_FILENAME.replace("{collection}", current_col)
        out_path = OUTPUT_DIR / fname
        if not out_path.exists() or not out_path.is_file():
            ui.notify(f"Output file not found: {out_path}", color="warning")
            return

        db_name = _resolve_target_database()
        loaded_via: list[str] = []

        if gen_settings["load_mongoimport"]:
            cmd = [
                "mongoimport",
                "--uri",
                uri,
                "--db",
                db_name,
                "--collection",
                current_col,
                "--file",
                str(out_path),
                "--jsonArray",
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            except FileNotFoundError:
                ui.notify("mongoimport not found in PATH", color="negative")
                return
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "mongoimport failed").strip()
                ui.notify(f"mongoimport failed: {err[:180]}", color="negative")
                return
            loaded_via.append("mongoimport")

        if gen_settings["load_pymongo"]:
            try:
                from pymongo import MongoClient
            except Exception:
                ui.notify("pymongo is not installed. Run: uv add pymongo", color="negative")
                return

            try:
                payload = json.loads(out_path.read_text(encoding="utf-8"))
            except Exception as exc:
                ui.notify(f"Could not parse output JSON: {exc}", color="negative")
                return

            docs = payload if isinstance(payload, list) else [payload]
            docs = [d for d in docs if isinstance(d, dict)]
            if not docs:
                ui.notify("No JSON documents found to insert", color="warning")
                return

            try:
                client = MongoClient(uri, serverSelectionTimeoutMS=10000)
                collection = client[db_name][current_col]
                if len(docs) == 1:
                    collection.insert_one(docs[0])
                else:
                    collection.insert_many(docs, ordered=False)
            except Exception as exc:
                ui.notify(f"pymongo load failed: {exc}", color="negative")
                return
            loaded_via.append("pymongo")

        ui.notify(
            f"Data Load complete via {', '.join(loaded_via)} -> {db_name}.{current_col}",
            color="positive",
        )

    def prev_sample():
        global preview_index
        if preview_docs and preview_index > 0:
            preview_index -= 1
            render_preview.refresh()

    def next_sample():
        global preview_index
        if preview_docs and preview_index < len(preview_docs) - 1:
            preview_index += 1
            render_preview.refresh()

    def add_field_of_type(ftype: str, extra: dict | None = None):
        ftype = _TYPE_LOOKUP.get(ftype.lower(), ftype)
        names = {"String": "new_field", "Range": "age", "Enum": "status",
                 "Array": "tags", "Object": "nested"}
        field: dict = {"id": _new_id(), "name": names.get(ftype, "field"),
                       "type": ftype, "required": False}
        if ftype == "String":
            field["faker"] = "word"
        elif ftype == "Range":
            field.update({"min": 0, "max": 100})
        elif ftype == "Enum":
            field.update({"values": ["option1", "option2"], "weights": [1.0, 1.0], "shuffler": 1})
        elif ftype == "Array":
            field.update({"element_type": "String", "size": 1, "seed_randomize": False, "cardinality": "1"})
        elif ftype == "Object":
            field["fields"] = []
        if extra:
            field.update(extra)
        cur_fields().append(field)
        _auto_save()
        render_schema_table.refresh()

    def add_nested_field(parent_id: int):
        parent = find_field(parent_id)
        if parent and parent["type"] == "Object":
            parent.setdefault("fields", []).append(
                {"id": _new_id(), "name": "nested_field", "type": "String",
                 "faker": "word", "required": False}
            )
            _auto_save()
            render_schema_table.refresh()

    def quick_add(preset_name: str):
        for name, conf in QUICK_ADD_PRESETS:
            if name == preset_name:
                import copy as _copy
                extra = _copy.deepcopy(conf)
                ftype = extra.pop("type")
                extra["name"] = name
                add_field_of_type(ftype, extra)
                break

    def _parse_numeric_text(value: str, fallback):
        text = (value or "").strip()
        if not text:
            return fallback
        try:
            return float(text) if "." in text else int(text)
        except ValueError:
            return fallback

    def open_range_dialog(fid: int):
        field = find_field(fid)
        if not field or field.get("type") != "Range":
            return

        current_min = field.get("min", 0)
        current_max = field.get("max", 100)

        with ui.dialog().props("persistent") as dlg:
            with ui.element("div").style(
                "width:420px;max-width:92vw;background:#fff;border-radius:10px;"
                "border:.5px solid #e0dcd8;box-shadow:0 12px 32px rgba(0,0,0,.18);"
                "display:flex;flex-direction:column;overflow:hidden"
            ):
                with ui.element("div").style(
                    "display:flex;justify-content:space-between;align-items:center;"
                    "padding:14px 18px;border-bottom:.5px solid #e0dcd8"
                ):
                    ui.html('<div class="modal-title">Configure range</div>')
                    ui.button("✕", on_click=dlg.close).props("flat dense round") \
                        .style("color:#666;font-size:13px;min-width:28px;height:28px")

                with ui.element("div").style("padding:16px 18px;display:flex;flex-direction:column;gap:12px"):
                    ui.html('<div style="font-size:12px;color:#888">Set minimum and maximum values for this field.</div>')
                    with ui.row().style("gap:10px"):
                        min_inp = ui.input(value=str(current_min), label="Min") \
                            .props("outlined dense type=number") \
                            .style("flex:1;font-family:'Monaco','Menlo',monospace")
                        max_inp = ui.input(value=str(current_max), label="Max") \
                            .props("outlined dense type=number") \
                            .style("flex:1;font-family:'Monaco','Menlo',monospace")

                with ui.element("div").style("display:flex;justify-content:flex-end;gap:8px;padding:12px 18px 18px"):
                    ui.button("Cancel", on_click=dlg.close).props("flat no-caps") \
                        .style("color:#666;font-size:12px")

                    def save_range():
                        min_val = _parse_numeric_text(min_inp.value, current_min)
                        max_val = _parse_numeric_text(max_inp.value, current_max)
                        if min_val > max_val:
                            min_val, max_val = max_val, min_val
                        target = find_field(fid)
                        if not target:
                            dlg.close()
                            return
                        target["min"] = min_val
                        target["max"] = max_val
                        _auto_save()
                        render_schema_table.refresh()
                        dlg.close()

                    ui.button("Save", on_click=save_range).props("no-caps unelevated") \
                        .style("background:#2a2a2a;color:#fff;border-radius:6px;font-size:12px;padding:7px 18px;box-shadow:none")

        dlg.open()

    def _set_output_detail_line(line_no: int) -> None:
        if not output_detail_ref:
            return
        output_detail_ref[0].set_content(
            f'<div class="output-detail" id="output-detail-live">Line {line_no} of {output_meta["line_count"]} · Documents: {output_meta["documents"]}</div>'
        )

    def _render_output_page() -> None:
        if not output_lines_ref:
            return
        lines: list[str] = output_meta.get("lines", [])
        if not lines:
            output_lines_ref[0].set_content('<div id="output-lines-body"></div>')
            _set_output_detail_line(1)
            return

        page_size = output_meta["page_size"]
        page = output_meta["page"]
        total_pages = max(1, (len(lines) + page_size - 1) // page_size)
        page = max(0, min(page, total_pages - 1))
        output_meta["page"] = page

        start = page * page_size
        end = min(len(lines), start + page_size)
        page_lines = lines[start:end]

        lines_html = "".join(
            f'<div class="ov-line" data-line="{idx}"><span class="ov-ln">{idx}</span><span class="ov-code">{html.escape(line if line else " ")}</span></div>'
            for idx, line in enumerate(page_lines, start=start + 1)
        )
        output_lines_ref[0].set_content(f'<div id="output-lines-body">{lines_html}</div>')

        if output_page_ref:
            output_page_ref[0].set_content(
                f'<span style="font-size:11px;color:#666">Page {page + 1} / {total_pages} · Lines {start + 1}-{end}</span>'
            )

        _set_output_detail_line(start + 1)
        ui.run_javascript(
            (
                "(function(){"
                "const body=document.getElementById('output-lines-body');"
                "const detail=document.getElementById('output-detail-live');"
                f"const total={output_meta['line_count']};"
                f"const docs={output_meta['documents']};"
                "if(!body||!detail)return;"
                "body.onclick=(ev)=>{const row=ev.target.closest('.ov-line');"
                "if(!row)return;const ln=row.getAttribute('data-line')||'1';"
                "detail.textContent=`Line ${ln} of ${total} · Documents: ${docs}`;};"
                "})();"
            ),
            timeout=5,
        )

    def open_output_viewer_dialog():
        fname = OUTPUT_FILENAME.replace("{collection}", current_col)
        out_path = OUTPUT_DIR / fname
        if not out_path.exists() or not out_path.is_file():
            ui.notify(f"Output file not found: {out_path}", color="warning")
            return

        try:
            raw_text = out_path.read_text(encoding="utf-8")
        except Exception as exc:
            ui.notify(f"Unable to read output: {exc}", color="negative")
            return

        lines = raw_text.splitlines() or [""]
        output_meta["lines"] = lines
        output_meta["line_count"] = len(lines)
        output_meta["page"] = 0
        try:
            parsed = json.loads(raw_text)
            output_meta["documents"] = len(parsed) if isinstance(parsed, list) else (1 if isinstance(parsed, dict) else 0)
        except Exception:
            output_meta["documents"] = 0

        output_path_ref[0].set_content(html.escape(str(out_path)))
        _render_output_page()
        output_dialog_ref[0].open()

    def restart_app():
        ui.notify("Restarting app...", color="warning")

        def _do_restart():
            script_path = str(Path(__file__).resolve())
            os.execv(sys.executable, [sys.executable, script_path, *sys.argv[1:]])

        ui.timer(0.2, _do_restart, once=True)

    def open_output_viewer_page():
        ui.navigate.to(f"/output-viewer?collection={current_col}")

    def _auto_save():
        save_schema(current_col, schemas[current_col])
        if saved_label_ref:
            saved_label_ref[0].set_content('<div class="save-indicator saved">● saved</div>')

    def handle_preview_header_click(e):
        global preview_index
        args   = e.args or {}
        target = args.get("target", {}) if isinstance(args, dict) else {}
        el_id  = target.get("id", "")
        if el_id == "nav-prev":
            prev_sample()
        elif el_id == "nav-next":
            next_sample()
        elif el_id == "regen-btn":
            do_generate()
        elif el_id == "copy-btn" and preview_docs:
            doc = preview_docs[preview_index]
            js = json.dumps(json.dumps(doc, default=str))
            ui.run_javascript(f"navigator.clipboard.writeText({js}).catch(()=>{{}})", timeout=5)

    # ── Layout ────────────────────────────────────────────────────────────────

    with ui.element("div").classes("container"):
        with ui.element("div").classes("card"):

            # Title bar
            with ui.element("div").classes("title-bar"):
                ui.html('''
                    <div class="title-left">
                        <div class="app-icon">M</div>
                        <div class="app-title">Mongo document generator</div>
                    </div>
                ''')
                with ui.element("div").style("display:flex;gap:8px;margin-left:auto"):
                    ui.button("</> CLI", on_click=open_cli_modal) \
                        .props("no-caps unelevated") \
                        .style("background:#f9f7f5;color:#4a4a4a;border:1px solid #e0dcd8;border-radius:6px;font-size:12px;font-family:'Monaco','Menlo',monospace;padding:8px 14px;box-shadow:none")
                    ui.button("⇪ Data Load", on_click=do_data_load) \
                        .props("no-caps unelevated") \
                        .style("background:#f9f7f5;color:#4a4a4a;border:1px solid #e0dcd8;border-radius:6px;font-size:12px;font-family:'Monaco','Menlo',monospace;padding:8px 14px;box-shadow:none")
                    ui.button("↻ Restart", on_click=restart_app) \
                        .props("no-caps unelevated") \
                        .style("background:#f9f7f5;color:#4a4a4a;border:1px solid #e0dcd8;border-radius:6px;font-size:12px;font-family:'Monaco','Menlo',monospace;padding:8px 14px;box-shadow:none")
                    ui.button("▶ Generate", on_click=do_generate) \
                        .props("no-caps unelevated") \
                        .style("background:#2a2a2a;color:#fff;border-radius:6px;font-size:12px;font-weight:500;padding:8px 18px;box-shadow:none")

            # Collection tabs
            with ui.element("div").classes("collection-tabs"):
                render_tabs()

            # Body
            with ui.element("div").classes("body"):

                # Left column
                with ui.element("div").classes("left-column"):
                    with ui.element("div").classes("column-header"):
                        render_col_header()

                    with ui.element("div").classes("table-container"):
                        render_schema_table()

                    # Preset chips
                    with ui.element("div").classes("preset-row"):
                        ui.html('<div class="preset-row-label">Quick-add realistic fields</div>')
                        with ui.element("div").classes("preset-chips"):
                            for name, _ in QUICK_ADD_PRESETS:
                                ui.html(f'<span class="preset-chip">{name}</span>') \
                                    .on("click", lambda n=name: quick_add(n))

                # Right column
                with ui.element("div").classes("right-column"):
                    # Preview header
                    prev_hdr = ui.html('''
                    <div class="preview-header">
                        <div class="preview-title">JSON preview · editable</div>
                        <div class="preview-nav" id="prev-nav">
                            <button class="nav-arrow" id="nav-prev">◀</button>
                            <span id="sample-label">Sample 1 of 5</span>
                            <button class="nav-arrow" id="nav-next">▶</button>
                        </div>
                        <div class="preview-icons">
                            <button class="icon-btn" id="regen-btn" title="Regenerate">🔄</button>
                            <button class="icon-btn" id="copy-btn" title="Copy JSON">📋</button>
                            <button class="icon-btn check" title="Valid">✓</button>
                        </div>
                    </div>''')
                    prev_hdr.on("click", handle_preview_header_click)

                    render_preview()

            # Generation options
            with ui.element("div").classes("gen-options"):
                render_gen_options()

            # Action bar
            with ui.element("div").classes("action-bar"):
                render_action_bar()

            with ui.dialog().props("persistent") as output_dlg:
                output_dialog_ref.append(output_dlg)
                with ui.element("div").style(
                    "width:940px;max-width:96vw;background:#fff;border-radius:10px;"
                    "border:.5px solid #e0dcd8;box-shadow:0 12px 32px rgba(0,0,0,.18);"
                    "display:flex;flex-direction:column;overflow:hidden"
                ):
                    with ui.element("div").style(
                        "display:flex;justify-content:space-between;align-items:center;"
                        "padding:14px 18px;border-bottom:.5px solid #e0dcd8"
                    ):
                        with ui.element("div"):
                            ui.html('<div class="modal-title">Output viewer</div>')
                            output_path_ref.append(ui.html('<div class="modal-subtitle"></div>'))
                        ui.button("✕", on_click=output_dlg.close).props("flat dense round") \
                            .style("color:#666;font-size:13px;min-width:28px;height:28px")

                    with ui.element("div").style("padding:12px 18px 18px"):
                        output_detail_ref.append(ui.html('<div class="output-detail" id="output-detail-live">Line 1 of 1 · Documents: 0</div>'))
                        with ui.row().style("justify-content:space-between;align-items:center;margin-bottom:8px"):
                            with ui.row().style("gap:6px"):
                                ui.button("◀ Prev", on_click=lambda: [output_meta.update({"page": max(0, output_meta["page"] - 1)}), _render_output_page()]) \
                                    .props("flat dense no-caps") \
                                    .style("font-size:11px")
                                ui.button("Next ▶", on_click=lambda: [output_meta.update({"page": output_meta["page"] + 1}), _render_output_page()]) \
                                    .props("flat dense no-caps") \
                                    .style("font-size:11px")
                            output_page_ref.append(ui.html('<span style="font-size:11px;color:#666">Page 1 / 1</span>'))
                        output_lines_ref.append(ui.html('<div id="output-lines-body"></div>').classes("output-viewer"))



@ui.page("/output-viewer")
def output_viewer_page(collection: str = ""):
    selected_collection = collection or current_col
    fname = OUTPUT_FILENAME.replace("{collection}", selected_collection)
    out_path = OUTPUT_DIR / fname

    ui.add_head_html("""
    <style>
    .ov-page{padding:16px;max-width:1200px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
    .ov-top{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap}
    .ov-title{font-size:18px;font-weight:600;color:#2a2a2a}
    .ov-sub{font-size:12px;color:#888;font-family:'Monaco','Menlo',monospace}
    .ov-controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0}
    .ov-box{background:#f9f7f5;border:.5px solid #e0dcd8;border-radius:6px;max-height:68vh;overflow:auto}
    .ov-line{display:grid;grid-template-columns:56px 1fr;gap:10px;padding:2px 10px;cursor:pointer}
    .ov-line:hover{background:#eef2ff}
    .ov-ln{font-family:'Monaco','Menlo',monospace;font-size:11px;color:#9ca3af;text-align:right;user-select:none}
    .ov-code{font-family:'Monaco','Menlo',monospace;font-size:12px;color:#2a2a2a;white-space:pre}
    .ov-detail{font-family:'Monaco','Menlo',monospace;font-size:11px;color:#666;margin:6px 0 10px}
    </style>
    """)

    with ui.element("div").classes("ov-page"):
        if not out_path.exists() or not out_path.is_file():
            ui.label("Output file not found").style("font-size:14px;color:#b91c1c")
            ui.html(html.escape(str(out_path))).style("font-size:12px;color:#888;font-family:'Monaco','Menlo',monospace")
            ui.button("← Back", on_click=lambda: ui.navigate.to("/")).props("flat no-caps")
            return

        try:
            raw_text = out_path.read_text(encoding="utf-8")
        except Exception as exc:
            ui.label(f"Unable to read output: {exc}").style("font-size:14px;color:#b91c1c")
            ui.button("← Back", on_click=lambda: ui.navigate.to("/")).props("flat no-caps")
            return

        lines = raw_text.splitlines() or [""]
        line_count = len(lines)
        try:
            parsed = json.loads(raw_text)
            docs_count = len(parsed) if isinstance(parsed, list) else (1 if isinstance(parsed, dict) else 0)
        except Exception:
            docs_count = 0

        state = {
            "lines": lines,
            "filtered": list(range(len(lines))),
            "page": 0,
            "page_size": 500,
        }

        with ui.element("div").classes("ov-top"):
            with ui.element("div"):
                ui.html('<div class="ov-title">Output viewer</div>')
                ui.html(f'<div class="ov-sub">{html.escape(str(out_path))}</div>')
            with ui.row().style("gap:8px"):
                ui.button("Download", on_click=lambda: ui.download(str(out_path), filename=out_path.name, media_type="application/json")) \
                    .props("no-caps unelevated") \
                    .style("background:#f9f7f5;color:#4a4a4a;border:.5px solid #e0dcd8;border-radius:6px;font-size:12px")
                ui.button("← Back", on_click=lambda: ui.navigate.to("/")) \
                    .props("no-caps unelevated") \
                    .style("background:#2a2a2a;color:#fff;border-radius:6px;font-size:12px")

        detail = ui.html(f'<div class="ov-detail" id="ov-detail-line">Line 1 of {line_count} · Documents: {docs_count}</div>')

        with ui.element("div").classes("ov-controls"):
            search_inp = ui.input(placeholder="Search text...").props("outlined dense") \
                .style("min-width:220px;font-family:'Monaco','Menlo',monospace;font-size:12px")
            jump_inp = ui.input(placeholder="Jump to line").props("outlined dense type=number") \
                .style("width:140px;font-family:'Monaco','Menlo',monospace;font-size:12px")
            prev_btn = ui.button("◀ Prev", on_click=lambda: go_prev()).props("flat dense no-caps").style("font-size:11px")
            next_btn = ui.button("Next ▶", on_click=lambda: go_next()).props("flat dense no-caps").style("font-size:11px")
            page_lbl = ui.html('<span style="font-size:11px;color:#666">Page 1 / 1</span>')

        viewer = ui.html('<div id="ov-lines-body"></div>').classes("ov-box")

        def set_detail_line(line_no: int) -> None:
            detail.set_content(f'<div class="ov-detail" id="ov-detail-line">Line {line_no} of {line_count} · Documents: {docs_count}</div>')

        def render_page() -> None:
            filtered = state["filtered"]
            if not filtered:
                viewer.set_content('<div id="ov-lines-body" style="padding:12px;font-family:\'Monaco\',\'Menlo\',monospace;font-size:12px;color:#888">No matching lines</div>')
                page_lbl.set_content('<span style="font-size:11px;color:#666">Page 0 / 0</span>')
                set_detail_line(1)
                return

            page_size = state["page_size"]
            total_pages = max(1, (len(filtered) + page_size - 1) // page_size)
            state["page"] = max(0, min(state["page"], total_pages - 1))
            start = state["page"] * page_size
            end = min(len(filtered), start + page_size)
            segment = filtered[start:end]

            rows = "".join(
                f'<div class="ov-line" data-line="{ln + 1}"><span class="ov-ln">{ln + 1}</span><span class="ov-code">{html.escape(lines[ln] if lines[ln] else " ")}</span></div>'
                for ln in segment
            )
            viewer.set_content(f'<div id="ov-lines-body">{rows}</div>')
            page_lbl.set_content(f'<span style="font-size:11px;color:#666">Page {state["page"] + 1} / {total_pages} · Showing {start + 1}-{end} of {len(filtered)}</span>')
            set_detail_line(segment[0] + 1)
            ui.run_javascript(
                (
                    "(function(){"
                    "const body=document.getElementById('ov-lines-body');"
                    "const detail=document.getElementById('ov-detail-line');"
                    f"const total={line_count};"
                    f"const docs={docs_count};"
                    "if(!body||!detail)return;"
                    "body.onclick=(ev)=>{const row=ev.target.closest('.ov-line');"
                    "if(!row)return;const ln=row.getAttribute('data-line')||'1';"
                    "detail.textContent=`Line ${ln} of ${total} · Documents: ${docs}`;};"
                    "})();"
                ),
                timeout=5,
            )

        def apply_search() -> None:
            term = (search_inp.value or "").strip().lower()
            if not term:
                state["filtered"] = list(range(len(lines)))
            else:
                state["filtered"] = [i for i, ln in enumerate(lines) if term in ln.lower()]
            state["page"] = 0
            render_page()

        def go_prev() -> None:
            state["page"] = max(0, state["page"] - 1)
            render_page()

        def go_next() -> None:
            state["page"] = state["page"] + 1
            render_page()

        def jump_to_line() -> None:
            text = (jump_inp.value or "").strip()
            if not text:
                return
            try:
                target = int(float(text))
            except ValueError:
                ui.notify("Invalid line number", color="warning")
                return
            target = max(1, min(line_count, target))
            idx = target - 1
            filtered = state["filtered"]
            if idx not in filtered:
                state["filtered"] = list(range(len(lines)))
                search_inp.set_value("")
                filtered = state["filtered"]
            position = filtered.index(idx)
            state["page"] = position // state["page_size"]
            render_page()
            set_detail_line(target)

        search_inp.on("change", lambda _: apply_search())
        jump_inp.on("keydown.enter", lambda _: jump_to_line())

        render_page()


ui.run(title="Mongo document generator", port=find_open_port(8080), dark=False, reload=False)
