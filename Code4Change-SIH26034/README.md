# Code4Change
## AI-Assisted Packaged Commodity Compliance System
**Smart India Hackathon 2026 – Problem Statement SIH26034**

> **Disclaimer:** All analysis results are AI-assisted preliminary checks only.  
> They do not constitute a legal compliance certificate under the Legal Metrology Act or any other regulation.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Technology Stack](#2-technology-stack)
3. [Project Structure](#3-project-structure)
4. [System Requirements](#4-system-requirements)
5. [Installation](#5-installation)
6. [Running the Application](#6-running-the-application)
7. [API Endpoint Reference](#7-api-endpoint-reference)
8. [Frontend–Backend Communication](#8-frontendbackend-communication)
9. [Testing Instructions](#9-testing-instructions)
10. [Sample Test Workflow](#10-sample-test-workflow)
11. [Development Roadmap](#11-development-roadmap)

---

## 1. Project Overview

Code4Change helps field inspectors verify that packaged commodities comply with mandatory labelling requirements (Legal Metrology Act, FSSAI, BIS, etc.).

**Core pipeline:**

```
Product Image → OpenCV Preprocessing → Tesseract OCR → Declaration Detection
    → Compliance Engine → Score + Violations → SQLite Database → PDF Report
```

---

## 2. Technology Stack

| Layer | Technology |
|---|---|
| Frontend | HTML5 + CSS3 + Vanilla JavaScript |
| Backend | Python 3.10+ / FastAPI |
| Image Processing | OpenCV (`opencv-python-headless`) |
| OCR | Tesseract OCR via `pytesseract` |
| Compliance Engine | Python + Regex |
| Database | SQLite (via stdlib `sqlite3`) |
| PDF Reports | fpdf2 |
| Server | Uvicorn (ASGI) |

---

## 3. Project Structure

```
Code4Change-SIH26034/
├── frontend/
│   ├── index.html
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── app.js
│       ├── api.js
│       ├── state.js
│       ├── ui.js
│       ├── pages.js
│       └── mobile-menu.js
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── api/
│   │   │   ├── inspection.py
│   │   │   └── history.py
│   │   ├── services/
│   │   │   ├── image_processor.py
│   │   │   ├── ocr_service.py
│   │   │   ├── compliance_engine.py
│   │   │   └── report_generator.py
│   │   └── models/
│   │       └── inspection.py
│   ├── uploads/
│   ├── reports/
│   ├── requirements.txt
│   └── run.py
│
├── database/
│   └── inspections.db
├── sample_images/
├── .gitignore
└── README.md

---

## 4. System Requirements

- **OS:** Windows 10/11, macOS, or Linux
- **RAM:** 4 GB minimum (8 GB recommended)
- **Python:** 3.10 or higher
- **Tesseract OCR:** Must be installed separately (see below)

---

## 5. Installation

### Step 1 – Install Tesseract OCR (system dependency)

**Windows:**
1. Download the installer from: https://github.com/UB-Mannheim/tesseract/wiki
2. Run the installer (default path: `C:\Program Files\Tesseract-OCR\tesseract.exe`)
3. Add the Tesseract folder to your system PATH, **or** set the environment variable:
   ```
   set TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
   ```

**macOS (Homebrew):**
```bash
brew install tesseract
```

**Ubuntu / Debian:**
```bash
sudo apt-get install tesseract-ocr
```

---

### Step 2 – Create a Python virtual environment

```bash
cd Code4Change-SIH26034/backend
python -m venv venv
```

Activate it:

- **Windows PowerShell:** `.\venv\Scripts\Activate.ps1`
- **Windows CMD:** `venv\Scripts\activate.bat`
- **macOS / Linux:** `source venv/bin/activate`

---

### Step 3 – Install Python dependencies

```bash
pip install -r requirements.txt
```

---

## 6. Running the Application

### Start the backend server

```bash
cd Code4Change-SIH26034/backend
python run.py
```

The server starts at: **http://127.0.0.1:8000**

Interactive API docs: **http://127.0.0.1:8000/docs**

### Open the frontend

Open `frontend/index.html` directly in your browser, **or** serve it with
Python's built-in HTTP server to avoid any `file://` CORS issues:

```bash
cd Code4Change-SIH26034/frontend
python -m http.server 5500
```

Then visit: **http://localhost:5500**

---

## 7. API Endpoint Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | API root / alive check |
| `GET` | `/health` | Health probe (returns `{"status": "ok"}`) |
| `POST` | `/api/inspect` | Upload image and run compliance analysis |
| `GET` | `/api/inspection/{id}` | Get full details of one inspection |
| `GET` | `/api/history` | Paginated list of past inspections |
| `GET` | `/api/report/{id}` | Download PDF report for an inspection |

### POST /api/inspect

**Request:** `multipart/form-data` with field `file` (image).

**Response (201):**
```json
{
  "inspection_id": 1,
  "timestamp": "2026-08-26T10:30:00Z",
  "extracted_text": "MRP Rs. 50 Net Wt. 100g ...",
  "detected_declarations": {
    "mrp": "Rs. 50",
    "net_quantity": "100g",
    "manufacturer": null,
    "address": null,
    "manufacturing_date": null,
    "consumer_care": null
  },
  "compliance_score": 33.33,
  "status": "NON_COMPLIANT",
  "violations": [
    "Manufacturer / Packer Name not detected",
    "Manufacturer / Packer Address not detected",
    "Manufacturing / Packing Date not detected",
    "Consumer Care Information not detected"
  ],
  "image_filename": "a1b2c3d4.jpg",
  "report_path": null
}
```

### GET /api/history

**Query params:** `page` (default 1), `page_size` (default 20, max 100)

**Response (200):**
```json
{
  "total": 42,
  "inspections": [
    {
      "inspection_id": 42,
      "timestamp": "2026-08-26T10:30:00Z",
      "compliance_score": 83.33,
      "status": "NON_COMPLIANT",
      "image_filename": "a1b2c3d4.jpg"
    }
  ]
}
```

---

## 8. Frontend–Backend Communication

The frontend (`js/app.js`) communicates with FastAPI exclusively through
`fetch()` calls:

```
User selects image
  → JavaScript reads file via FileReader (preview)
  → On "Analyze Product" click:
      fetch("http://127.0.0.1:8000/api/inspect", {
          method: "POST",
          body: FormData  ← contains the image file
      })
  → FastAPI processes image → returns JSON
  → JavaScript parses JSON → updates UI sections:
      - extracted text panel
      - declarations table
      - compliance score + status badge
      - violations list
  → "Generate Report" click:
      fetch("http://127.0.0.1:8000/api/report/{id}")
      → browser downloads PDF
```

No page reload is required. All state is managed in JavaScript.

---

## 9. Testing Instructions

### Test the API directly (curl)

```bash
curl -X POST http://127.0.0.1:8000/api/inspect \
  -F "file=@sample_images/test_label.jpg"
```

### Test with the interactive docs

1. Open http://127.0.0.1:8000/docs
2. Click `POST /api/inspect → Try it out`
3. Upload any product image
4. Click `Execute` and inspect the JSON response

### Test the health endpoint

```bash
curl http://127.0.0.1:8000/health
# Expected: {"status":"ok","service":"Code4Change Backend"}
```

---

## 10. Sample Test Workflow

1. Place a product image in `sample_images/` (e.g., a biscuit packet photo).
2. Start the backend: `python run.py`
3. Open the frontend in a browser.
4. Click **Choose File** and select the sample image.
5. Click **Analyze Product**.
6. Observe:
   - The OCR extracted text panel (Phase 5: will show real text)
   - The declarations table showing found/missing fields
   - The compliance score (0–100%)
   - The violations list
7. Click **View History** to see past inspections.
8. Click **Generate Report** to download the PDF (Phase 10).

---

## 11. Development Roadmap

| Phase | Status | Description |
|---|---|---|
| 1 | ✅ Complete | Project structure + FastAPI server |
| 2 | Pending | Frontend upload interface |
| 3 | Pending | Frontend ↔ FastAPI integration |
| 4 | Pending | OpenCV image preprocessing |
| 5 | Pending | Tesseract OCR integration |
| 6 | Pending | Regex declaration extraction |
| 7 | Pending | Compliance rules + scoring |
| 8 | Pending | SQLite persistence |
| 9 | Pending | Inspection history UI |
| 10 | Pending | PDF report generation |
| 11 | Pending | UI polish + error handling |
| 12 | Pending | Demo preparation |
