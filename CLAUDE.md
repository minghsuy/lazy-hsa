# HSA Receipt System - Claude Code Context

## Project Overview
Automated HSA (Health Savings Account) receipt organization system. Strategy: pay medical expenses out-of-pocket now, archive receipts with bulletproof documentation, invest HSA funds tax-free, reimburse decades later when balance has compounded.

## Family
- **Ming** (primary account holder)
- **Vanessa** (spouse)
- **Maxwell** (dependent, age 8)

HSA effective date: 2026-01-01

## Architecture

### Vision LLM Extraction
- Uses Mistral Small 3 (14B) via Ollama on DGX Spark at `100.117.74.20:11434`
- Direct image-to-JSON extraction (no separate OCR step)
- Prompt constrains patient_name to exactly one of: Ming, Vanessa, Maxwell

### Google APIs
- **Drive**: Stores receipts in `HSA_Receipts/{year}/{category}/{patient}/`
- **Sheets**: Master index spreadsheet `HSA_Master_Index` tracks all records
- **Gmail**: Scans for medical provider emails with attachments

### Folder Structure
```
HSA_Receipts/
├── 2026/
│   ├── Medical/
│   │   ├── Ming/
│   │   ├── Vanessa/
│   │   └── Maxwell/
│   ├── Dental/
│   ├── Vision/
│   ├── Pharmacy/
│   └── EOBs/
│       ├── Medical/
│       ├── Dental/
│       └── Vision/
├── _Inbox/      # Drop files here for auto-processing
├── _Processing/ # (future) Files being processed
└── _Rejected/   # (future) Files that failed processing
```

## CLI Commands
```bash
# Initial setup
hsa setup

# Process single file or directory
hsa process --file receipt.pdf
hsa process --dir ./receipts/ --patient Vanessa
hsa process --file costco_receipt.png --dry-run  # Preview without committing

# Process files from Google Drive _Inbox
hsa inbox              # One-time check
hsa inbox --watch      # Continuous polling
hsa inbox --dry-run    # Preview extraction without modifying Drive/Sheets

# Scan Gmail for medical emails
hsa email-scan --since 2026-01-01

# View summary
hsa summary
```

## Key Files
- `src/pipeline.py` - Main orchestration, CLI commands
- `src/processors/llm_extractor.py` - Vision LLM extraction with family-constrained prompt
- `src/storage/gdrive_client.py` - Google Drive operations
- `src/storage/sheet_client.py` - Google Sheets tracking with duplicate detection
- `src/watchers/inbox_watcher.py` - Drive _Inbox folder watcher
- `src/extractors/gmail_extractor.py` - Gmail medical email extraction
- `config/config.yaml` - All configuration (LLM endpoint, family members, etc.)

## What's Complete
- [x] Vision LLM extraction with Mistral Small 3
- [x] Google Drive folder structure and upload
- [x] Google Sheets master index tracking
- [x] Gmail scanning for medical provider emails
- [x] Drive _Inbox watcher (drop files → auto-process → delete from inbox)
- [x] Patient name detection from filenames (e.g., "CVS Vanessa prescription.pdf")
- [x] LLM prompt constrains patient to family member names only
- [x] Duplicate detection (same provider + date + amount)
- [x] Dry-run mode for inbox and process commands
- [x] Provider-specific extraction skills (see below)

## What's Left (Phase 4: Validation & Robustness)

### High Priority
- [ ] **EOB folder support**: Route EOBs to `EOBs/{category}/` instead of regular category folders
- [ ] **Improved duplicate handling**: When EOB + bill detected, link them and use EOB's patient_responsibility as authoritative amount
- [ ] **Error recovery**: Move failed files to `_Rejected/` with error notes
- [ ] **Multi-page PDF handling**: Currently only processes first page, may miss data on subsequent pages

### Medium Priority
- [ ] **Reimbursement tracking CLI**: `hsa reimburse --id 5 --amount 100.00 --date 2026-12-01`
- [ ] **Annual summary export**: Generate PDF/Excel report for tax records
- [ ] **Provider name normalization**: "Sutter Health" vs "SUTTER HEALTH SACRAMENTO" should match
- [ ] **Service date validation**: Warn if service_date is in the future or before HSA start

### Low Priority / Future
- [ ] **iOS Shortcuts integration**: Via Tailscale to home server
- [ ] **Scheduled Gmail scanning**: Cron job or systemd timer
- [ ] **OCR fallback**: For when vision LLM fails (very low confidence)
- [ ] **Receipt image enhancement**: Deskew, contrast adjustment before LLM

## Provider Skills System

Provider-specific extraction prompts activate automatically based on filename patterns. Defined in `src/processors/llm_extractor.py`:

| Provider | Triggers | Special Handling |
|----------|----------|------------------|
| **Costco** | "costco", "store 423" | Looks for "F" column marker, sums only F-marked items |
| **CVS** | "cvs" | FSA/HSA labels, Rx numbers for prescriptions |
| **Walgreens** | "walgreens" | FSA/HSA markers, copay extraction |
| **Amazon** | "amazon" | Extracts Grand Total directly (includes tax) |
| **Express Scripts** | "express scripts", "esrx" | Mail-order pharmacy, medication name extraction |
| **Sutter** | "sutter", "pamf" | Hospital/clinic bills, Patient Responsibility field |
| **Aetna** | "aetna" | Medical EOB, Member Responsibility, Plan Paid fields |
| **Delta Dental** | "delta dental" | Dental EOB, Patient Pays field |
| **VSP** | "vsp" | Vision EOB format |
| **Stanford** | "stanford", "stanford health" | Hospital statements, Patient Responsibility, Service Date |

### Tax Calculation (Retail Receipts)
For retail receipts (Costco, CVS, etc.), the system:
1. LLM extracts: `eligible_subtotal`, `receipt_tax`, `receipt_taxable_amount`
2. Python calculates: `tax_rate = receipt_tax / receipt_taxable_amount`
3. Python calculates: `tax_on_eligible = eligible_subtotal * tax_rate`
4. Final amount: `patient_responsibility = eligible_subtotal + tax_on_eligible`

IRS allows HSA reimbursement of sales tax on eligible items.

### Supported Image Formats
- PDF, PNG, JPG, JPEG, GIF, WEBP, TIFF, BMP
- **HEIC/HEIF** (iPhone photos) - converted to PNG before processing

### Adding New Provider Skills
1. Add skill to `PROVIDER_SKILLS` dict in `llm_extractor.py`
2. Add pattern to `provider_patterns` in `detect_provider_skill()`
3. Test with `hsa inbox --dry-run` before committing

## Removed Features
- **Amazon HSA scraper**: Removed because Amazon's 2FA/CAPTCHA/passkey requirements make automation impractical. Manual invoice download is simpler.

## Development Notes

### Running with Poppler (for PDF processing)
```bash
PATH="/opt/homebrew/opt/poppler/bin:$PATH" uv run hsa inbox
```

### Re-authenticating Google APIs
Delete the token file to force re-auth:
```bash
rm config/credentials/gdrive_token.json
rm config/credentials/gmail_token.json
rm config/credentials/gsheets_token.json
```

### Testing extraction
```bash
uv run python src/processors/llm_extractor.py test_receipts/receipt.pdf
```

## Config Location
- Credentials: `config/credentials/` (gitignored)
- Config: `config/config.yaml`
