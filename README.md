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

## Full installation guide 🛠️

### 1. Install Git

Check if Git is already installed:

```bash
git --version
```

If not installed, download and install Git from:

- https://git-scm.com/downloads

### 2. Install Python 3.11+

Check your Python version:

```bash
python --version
```

If needed, install Python 3.11 or newer from:

- https://www.python.org/downloads/

### 3. Clone this repository

```bash
git clone https://github.com/Dennis-Spera/mongodb-json-generator.git
cd mongodb-json-generator
```

### 4. Install uv (recommended)

Windows PowerShell:

```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

macOS and Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify uv install:

```bash
uv --version
```

### 5. Install project dependencies

Using uv (recommended):


```bash
uv sync
```

Fallback with pip if you do not want uv:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS and Linux:

```bash
source .venv/bin/activate
```

Then install modules:

```bash
pip install -e .
```

### 6. Run the app

```bash
python main.py
```

The app runs on:

- http://localhost:8080 ٩(ˊᗜˋ*)و

Optional script entrypoint:

```bash
start
```

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
- If start is not recognized, run python main.py instead

## License

Private/internal project for now ¯\\_(ツ)_/¯
