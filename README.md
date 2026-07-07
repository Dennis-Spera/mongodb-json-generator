# MongoDB JSON Generator 😎

Generate realistic MongoDB-like JSON documents from a schema builder UI.  
Fast setup, editable preview, and easy export. 🚀

Made for quick local data generation when you need sample docs now, not later :) 

## What this does ✨

- Build collection schemas visually in the NiceGUI app
- Use Mongo-friendly types like ObjectId, Date, UUID, Int32, Int64, Array, Object, Enum, Range
- Generate many fake documents with Faker fields
- Preview JSON before generating final output
- Save schemas in local files
- Save generated docs to output JSON files and local TinyDB files

## Tech stack 🧰

- Python 3.11+
- NiceGUI
- Faker
- TinyDB

## Quick start ⚡

### 1) Install dependencies

Using uv:

```bash
uv sync
```

Or with pip:

```bash
pip install -e .
```

### 2) Run the app

```bash
python main.py
```

The app runs on:

- http://localhost:8080 ٩(ˊᗜˋ*)و

## Project structure 📁

- main.py: NiceGUI app and UI logic
- faker_fields.py: fake value generation rules
- db_store.py: TinyDB storage helpers
- schema_store.py: schema file load/save/delete
- schemas/: saved schema definitions
- db/: TinyDB collection files
- output/: generated JSON output files
- upload_to_github.sh: helper script for commit and push

## Upload helper script ☁️

Use the helper to commit and push to GitHub:

```bash
bash upload_to_github.sh "your commit message"
```

Optional args:

```bash
bash upload_to_github.sh "message" master origin
```

Temp files are excluded (for example *.tmp.*), so accidental editor temp uploads are blocked 👍

## Notes 📝

- If your UI looks blank, confirm port 8080 is free
- If generation feels slow, reduce count and test with a smaller seed run first
- Schemas and db folders are local and intended for development use

## License

Private/internal project for now ¯\\_(ツ)_/¯
