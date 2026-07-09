import random
from faker import Faker

_fake = Faker()

FAKER_TYPES = [
    "firstName", "lastName", "fullName", "email", "phone", "username", "password",
    "jobTitle", "street", "city", "state", "country", "zipCode", "latitude", "longitude",
    "companyName", "productName", "price", "date", "uuid", "number", "boolean",
    "accountNumber",
    "word", "sentence", "paragraph", "color", "url", "ipAddress", "userAgent",
]

_MAP: dict = {
    "firstName":   lambda: _fake.first_name(),
    "lastName":    lambda: _fake.last_name(),
    "fullName":    lambda: _fake.name(),
    "email":       lambda: _fake.email(),
    "phone":       lambda: _fake.phone_number(),
    "username":    lambda: _fake.user_name(),
    "password":    lambda: _fake.password(),
    "jobTitle":    lambda: _fake.job(),
    "street":      lambda: _fake.street_address(),
    "city":        lambda: _fake.city(),
    "state":       lambda: _fake.state(),
    "country":     lambda: _fake.country(),
    "zipCode":     lambda: _fake.postcode(),
    "latitude":    lambda: float(_fake.latitude()),
    "longitude":   lambda: float(_fake.longitude()),
    "companyName": lambda: _fake.company(),
    "productName": lambda: _fake.catch_phrase(),
    "price":       lambda: round(float(_fake.pricetag().replace("$", "").replace(",", "")), 2),
    "date":        lambda: _fake.date_time_this_decade().isoformat(),
    "uuid":        lambda: _fake.uuid4(),
    "number":      lambda: _fake.random_int(min=1, max=1000),
    "boolean":     lambda: _fake.boolean(),
    "accountNumber": lambda: _fake.numerify(text="############"),
    "word":        lambda: _fake.word(),
    "sentence":    lambda: _fake.sentence(),
    "paragraph":   lambda: _fake.paragraph(),
    "color":       lambda: _fake.color_name(),
    "url":         lambda: _fake.url(),
    "ipAddress":   lambda: _fake.ipv4(),
    "userAgent":   lambda: _fake.user_agent(),
}


def _coerce_seed_value(value, element_type: str):
    text = str(value).strip()
    if element_type in ("Int32", "Int64", "Timestamp"):
        try:
            return int(float(text))
        except ValueError:
            return 0
    if element_type in ("Double", "Decimal128"):
        try:
            return float(text)
        except ValueError:
            return 0.0
    if element_type == "Boolean":
        return text.lower() in ("1", "true", "t", "yes", "y", "on")
    if element_type == "Null":
        return None
    return text


def _gen_value(field: dict):
    t = field.get("type", "String")

    # ── MongoDB native types ──────────────────────────────────────────────────
    if t == "ObjectId":
        return f"ObjectId('{_fake.hexify('^^^^^^^^^^^^^^^^^^^^^^^^')}')"
    if t == "String":
        return _MAP.get(field.get("faker", "word"), _MAP["word"])()
    if t == "Int32":
        return random.randint(int(field.get("min", 0)), int(field.get("max", 2147483647)))
    if t == "Int64":
        return random.randint(int(field.get("min", 0)), int(field.get("max", 9007199254740991)))
    if t == "Double":
        lo, hi = float(field.get("min", 0.0)), float(field.get("max", 1000.0))
        return round(random.uniform(lo, hi), 4)
    if t == "Decimal128":
        lo, hi = float(field.get("min", 0.0)), float(field.get("max", 9999.99))
        prec = int(field.get("precision", 2))
        return round(random.uniform(lo, hi), prec)
    if t == "Boolean":
        return _fake.boolean()
    if t == "Date":
        return _fake.date_time_this_decade().isoformat()
    if t == "Timestamp":
        import time as _time
        return int(_time.time()) + random.randint(-31536000, 31536000)
    if t == "UUID":
        return _fake.uuid4()
    if t == "Binary":
        return _fake.hexify("^" * 32)
    if t == "Null":
        return None

    # ── Generator helpers ─────────────────────────────────────────────────────
    if t == "Range":
        return random.randint(int(field.get("min", 0)), int(field.get("max", 100)))
    if t == "Enum":
        vals = field.get("values", ["value"])
        wts  = field.get("weights")
        if wts and len(wts) == len(vals):
            return random.choices(vals, weights=wts, k=1)[0]
        return random.choice(vals)
    if t == "Array":
        # New schema model: element_type + size
        if "size" in field:
            try:
                n = max(0, int(field.get("size", 1)))
            except (TypeError, ValueError):
                n = 1
        else:
            # Backward compatibility with older min/max model.
            n = random.randint(int(field.get("min_items", 1)), int(field.get("max_items", 3)))

        element_type = field.get("element_type")
        if isinstance(element_type, str):
            safe_type = element_type if element_type not in ("Array", "Object") else "String"

            seed_values = field.get("seed_values")
            if isinstance(seed_values, str):
                seed_values = [v.strip() for v in seed_values.split(",") if v.strip()]
            if isinstance(seed_values, list) and seed_values:
                coerced = [_coerce_seed_value(v, safe_type) for v in seed_values]
                if coerced:
                    if bool(field.get("seed_randomize", False)):
                        return [random.choice(coerced) for _ in range(n)]
                    return [coerced[i % len(coerced)] for i in range(n)]

            return [_gen_value({"type": safe_type, "faker": "word"}) for _ in range(n)]

        # Legacy fallback path.
        fn = _MAP.get(field.get("element_faker", "word"), _MAP["word"])
        return [fn() for _ in range(n)]
    if t == "Object":
        return {f["name"]: _gen_value(f) for f in field.get("fields", [])}

    return None


def generate_documents(fields: list, count: int, seed: int | None = None) -> list[dict]:
    if seed is not None:
        random.seed(seed)
        Faker.seed(seed)
    return [{f["name"]: _gen_value(f) for f in fields} for _ in range(count)]
