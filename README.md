# HSA Receipt Organization System

A comprehensive, automated system for organizing HSA-eligible medical receipts for the Weng family.

## Overview

This system helps you:
- **Collect** receipts from Gmail, Google Drive _Inbox, provider portals, and paper scans
- **Process** using Vision LLM extraction (Mistral Small 3 via Ollama)
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

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
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
- Family member names (Ming, Vanessa, Maxwell)
- LLM endpoint settings (default: Ollama at 100.117.74.20:11434)

### 4. Initial Setup

```bash
# Set up folder structure and authenticate
hsa setup
```

This will:
- Prompt for Google OAuth (first time only)
- Create the full folder structure in Google Drive
- Create the tracking spreadsheet

### 5. Start Ollama Server (on DGX Spark)

```bash
# Using Ollama with Mistral Small 3
ollama serve
ollama run mistral-small3.1
```

## Usage

### Process Files from Google Drive _Inbox

Drop files into the `_Inbox` folder in Google Drive, then:

```bash
# Preview what would happen (dry-run)
hsa inbox --dry-run

# Process all files in _Inbox
hsa inbox

# Continuous watch mode
hsa inbox --watch
```

### Process a Single Receipt

```bash
# With dry-run to preview
hsa process --file /path/to/receipt.pdf --dry-run

# Actually process
hsa process --file /path/to/receipt.pdf

# With patient hint
hsa process --file /path/to/receipt.pdf --patient Ming
```

### Process a Directory

```bash
# Process all supported files in a directory
hsa process --dir /path/to/inbox/
```

### View Summary

```bash
hsa summary
```

Output:
```
HSA Expense Summary
==================================================

2026:
  Receipts: 15
  Billed: $3,450.00
  Insurance: $2,760.00
  Your cost: $690.00
  Reimbursed: $0.00

Total Unreimbursed: $690.00
```

### Scan Gmail for Medical Receipts

```bash
hsa email-scan --since 2026-01-01
```

## Supported File Formats

- PDF (single and multi-page)
- PNG, JPEG, TIFF, BMP, WebP, GIF
- **HEIC/HEIF** (iPhone photos) - auto-converted to PNG

## Provider Skills System

The system includes specialized extraction rules for common providers:

| Provider | Auto-Detection | Special Handling |
|----------|---------------|------------------|
| **Costco** | "costco" in filename/content | FSA star (*) or "F" markers, calculates tax on eligible items |
| **CVS** | "cvs" in filename | FSA/HSA eligibility labels, Rx numbers |
| **Walgreens** | "walgreens" in filename | FSA/HSA markers, copay extraction |
| **Amazon** | "amazon" in filename | Ship-to address for patient, Grand Total extraction |
| **Express Scripts** | "express scripts" or "esrx" | Mail-order pharmacy prescriptions |
| **Sutter/PAMF** | "sutter" or "pamf" | Hospital/clinic bills, Patient Responsibility field |
| **Aetna** | "aetna" in filename | Medical EOB, Member Responsibility field |
| **Delta Dental** | "delta dental" in filename | Dental EOB, Patient Pays field |
| **VSP** | "vsp" in filename | Vision EOB format |

### Tax Calculation

For retail receipts with mixed HSA-eligible and non-eligible items, the system:
1. Extracts `eligible_subtotal` (sum of FSA/HSA-marked items)
2. Extracts `receipt_tax` and `receipt_taxable_amount` from receipt
3. Calculates tax rate: `tax_rate = receipt_tax / receipt_taxable_amount`
4. Applies proportional tax: `tax_on_eligible = eligible_subtotal * tax_rate`

This ensures accurate HSA reimbursement including sales tax on eligible items.

## Folder Structure (Google Drive)

```
HSA_Receipts/
├── 2026/
│   ├── Medical/
│   │   ├── Ming/
│   │   ├── Vanessa/
│   │   └── Maxwell/
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
├── _Inbox/         # Drop new files here for auto-processing
├── _Processing/    # (future) Currently being processed
└── _Rejected/      # (future) Non-HSA-eligible items
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
| `src/pipeline.py` | Main orchestration and CLI |
| `src/processors/llm_extractor.py` | Vision LLM extraction with provider skills |
| `src/extractors/gmail_extractor.py` | Gmail API receipt extraction |
| `src/watchers/inbox_watcher.py` | Google Drive _Inbox folder watcher |
| `src/storage/gdrive_client.py` | Google Drive file management |
| `src/storage/sheet_client.py` | Google Sheets tracking with duplicate detection |

## Development

### Running with Poppler (for PDF processing)

```bash
# macOS
brew install poppler
PATH="/opt/homebrew/opt/poppler/bin:$PATH" uv run hsa inbox
```

### Running Tests

```bash
uv run pytest tests/
```

### Re-authenticating Google APIs

Delete the token file to force re-auth:
```bash
rm config/credentials/gdrive_token.json
rm config/credentials/gmail_token.json
rm config/credentials/gsheets_token.json
```

### Testing Extraction Directly

```bash
uv run python src/processors/llm_extractor.py test_receipts/receipt.pdf
```

## Troubleshooting

### "Ollama connection refused"
Ensure Ollama is running on the configured host:
```bash
curl http://100.117.74.20:11434/api/tags
```

### "Google OAuth error"
Delete `config/credentials/*_token.json` and re-authenticate.

### Low confidence extractions
Check the `confidence` column in the spreadsheet. Values below 70% may need manual review.

### HEIC files not processing
Ensure pillow-heif is installed:
```bash
uv add pillow-heif
```

## License

Private - Weng Family Use Only
