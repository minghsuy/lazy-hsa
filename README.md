# HSA Receipt Organization System

A comprehensive, automated system for organizing HSA-eligible medical receipts for the Weng family.

## Overview

This system helps you:
- **Collect** receipts from Gmail, iCloud, provider portals, and paper scans
- **Process** using local OCR (PaddleOCR) and LLM extraction on your DGX Spark
- **Organize** into Google Drive with standardized naming
- **Track** everything in a master spreadsheet for future reimbursement

## Strategy

The HSA reimbursement strategy:
1. Pay all medical expenses **out of pocket** now
2. Invest HSA funds in index funds (FZROX/FSKAX)
3. Archive receipts with bulletproof documentation
4. Reimburse **decades later** when the balance has compounded tax-free

**Important**: Only expenses from **January 1, 2026 onwards** are eligible (HSA start date).

## Quick Start

### 1. Install Dependencies

```bash
cd hsa-receipt-system

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# For DGX Spark GPU support
pip install paddlepaddle-gpu
```

### 2. Set Up Google API Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable APIs:
   - Google Drive API
   - Google Sheets API
   - Gmail API
4. Create OAuth 2.0 credentials (Desktop app)
5. Download and save as `config/credentials/gdrive_credentials.json`

### 3. Configure

```bash
# Copy example config
cp config/config.example.yaml config/config.yaml

# Edit with your settings
nano config/config.yaml
```

Update:
- Email addresses for you and your wife
- Family member names
- LLM model settings (if different from default)

### 4. Initial Setup

```bash
# Set up folder structure and authenticate
python src/pipeline.py setup --family "Ming" "WifeName" "SonName"
```

This will:
- Prompt for Google OAuth (first time only)
- Create the full folder structure in Google Drive
- Create the tracking spreadsheet

### 5. Start Local LLM Server (on DGX Spark)

```bash
# Using vLLM for efficient inference
python -m vllm.entrypoints.openai.api_server \
    --model meta-llama/Llama-3.3-70B-Instruct \
    --port 8000 \
    --tensor-parallel-size 2  # Adjust based on your GPU setup
```

## Usage

### Process a Single Receipt

```bash
# Dry run (see what would happen)
python src/pipeline.py dry-run --file /path/to/receipt.pdf

# Actually process
python src/pipeline.py process --file /path/to/receipt.pdf

# With patient hint
python src/pipeline.py process --file /path/to/receipt.pdf --patient "Ming"
```

### Process a Directory

```bash
# Process all PDFs and images in a directory
python src/pipeline.py process --dir /path/to/inbox/

# Dry run first
python src/pipeline.py dry-run --dir /path/to/inbox/
```

### View Summary

```bash
python src/pipeline.py summary
```

Output:
```
📊 HSA Expense Summary
==================================================

2026:
  Receipts: 15
  Billed: $3,450.00
  Insurance: $2,760.00
  Your cost: $690.00
  Reimbursed: $0.00

💰 Total Unreimbursed: $690.00
```

## Folder Structure (Google Drive)

```
HSA_Receipts/
├── 2026/
│   ├── Medical/
│   │   ├── Ming/
│   │   ├── WifeName/
│   │   └── SonName/
│   ├── Dental/
│   │   └── [same structure]
│   ├── Vision/
│   │   └── [same structure]
│   ├── Pharmacy/
│   │   └── [same structure]
│   └── EOBs/
│       ├── Medical/
│       ├── Dental/
│       └── Vision/
├── _Inbox/         # Drop new files here
├── _Processing/    # Currently being processed
└── _Rejected/      # Non-HSA-eligible items
```

## File Naming Convention

```
YYYY-MM-DD_Provider_ServiceType_$Amount.pdf
```

Examples:
- `2026-01-15_Stanford_Cardiology_$150.00.pdf`
- `2026-02-10_CVS_Zepbound_$25.00.pdf`

For reimbursed files, append `.reimbursed`:
- `2026-01-15_Stanford_Cardiology_$150.00.reimbursed.pdf`

## Components

| Component | Purpose |
|-----------|---------|
| `src/pipeline.py` | Main orchestration |
| `src/processors/ocr_processor.py` | PaddleOCR / docTR wrapper |
| `src/processors/llm_extractor.py` | Local LLM structured extraction |
| `src/extractors/gmail_extractor.py` | Gmail API receipt extraction |
| `src/storage/gdrive_client.py` | Google Drive file management |
| `src/storage/sheet_client.py` | Google Sheets tracking |

## Brother Scanner Setup

Configure your Brother HL-3290CDW for Scan to Email:

1. Access printer web interface: `http://<printer-ip>`
2. Navigate to **Scan** → **Scan to E-mail**
3. Configure SMTP for Gmail:
   - Server: `smtp.gmail.com`
   - Port: `587`
   - Security: `STARTTLS`
4. Set destination email: `receipts.weng@gmail.com`

Scanned receipts will arrive in Gmail, ready to be processed.

## Development

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run tests
pytest tests/
```

### Mock Mode (No LLM Server)

For development without running the local LLM:

```yaml
# In config.yaml
llm:
  use_mock: true
```

### Adding New Provider Patterns

Edit `src/extractors/gmail_extractor.py`:

```python
MEDICAL_QUERIES = [
    # Add new provider query
    'from:(newprovider) subject:(statement OR bill)',
    ...
]
```

## Troubleshooting

### "PaddleOCR not found"
```bash
pip install paddlepaddle-gpu paddleocr
```

### "CUDA out of memory"
Reduce LLM tensor parallel size or use a smaller model.

### "Google OAuth error"
Delete `config/credentials/*_token.json` and re-authenticate.

### Low confidence extractions
Check `_Processing` folder for manual review items.

## License

Private - Weng Family Use Only
