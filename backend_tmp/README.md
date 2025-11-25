
# zpay-upload

Clean, modular FastAPI upload package for robust CSV/Excel/PDF ingestion.

## Structure

```
zpay_upload/
├─ app/
│  ├─ __init__.py
│  ├─ main.py
│  ├─ routers/
│  │  ├─ __init__.py
│  │  └─ upload.py
│  └─ services/
│     ├─ __init__.py
│     ├─ cleaning.py
│     ├─ readers.py
│     └─ pdf_reader.py
├─ pyproject.toml
└─ README.md
```

## Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Then POST to `http://localhost:8000/upload` with a file form field named `file`.
