# Lab report extraction

This project extracts lab results from PDFs and images with the Gemini API and compares saved JSON results against the labelled reports.

## Requirements

- Python 3.10 or newer
- Poppler, including `pdftoppm`, for PDF input
- The Python package listed in `requirements.txt`
- A Gemini API key for extraction

The evaluator and unit tests do not make API calls. The four reports without gold labels are not included in `evaluate.py` comparisons.

## Install Poppler

Install Poppler and make sure `pdftoppm` is available on `PATH`.

- **Windows (WinGet):** `winget install --id oschwartz10612.Poppler --exact`. If necessary, open a new terminal after installation. [Windows package](https://github.com/oschwartz10612/poppler-windows)
- **macOS (Homebrew):** `brew install poppler`
- **Ubuntu/Debian:** `sudo apt-get update`, then `sudo apt-get install poppler-utils`

Check the installation with:

```text
pdftoppm -v
```

## Create a Python environment

Run these commands from the project root.

### Windows PowerShell

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell activation is restricted, use the virtual environment's interpreter directly:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Linux and macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Configure Gemini access

Create a `.env` file in the project root:

```text
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-3.8-flash
```

`GEMINI_MODEL` is optional; `gemini-3.8-flash` is the default. Keep `.env` private and do not commit it. The repository's `.gitignore` excludes it. You can create a key in [Google AI Studio](https://aistudio.google.com/apikey); API access and quotas depend on your project.

## Extract a report

From the project root, run:

```bash
python extract.py reports/report_01.pdf
```

The command prints JSON to stdout and makes one Gemini API request. It accepts PDF, JPEG, and PNG inputs. For PDFs, all pages are rendered and sent together. API requests may incur charges; check [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) and your project's [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).

To save a UTF-8 JSON result for evaluation, use this command and change the report number and input extension as needed:

```bash
python -c 'import json; from pathlib import Path; import extract; report=Path("reports/report_01.pdf"); output=Path("extracted/report_01.json"); output.parent.mkdir(exist_ok=True); output.write_text(json.dumps(extract.extract(report), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")'
```

Create matching `report_XX.json` files for the eight labelled reports: `01`, `02`, `03`, `05`, `06`, `08`, `09`, and `11`. Each extraction makes an API request and may be subject to your project's rate limits.

## Evaluate saved results

After the extraction JSON files are saved in `extracted/`, run:

```bash
python evaluate.py extracted
```

The evaluator compares available JSON files against `gold/report_*.json` and reports missing extraction files and row-level differences. It does not make API calls. Reports `04`, `07`, `10`, and `12` have no gold labels and are excluded.

## Run unit tests

```bash
python -m unittest discover -v
```

The tests use mocked API responses and do not make live requests.