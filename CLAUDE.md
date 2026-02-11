# lazy-hsa - Claude Code Context

## Project Overview
Local AI-powered HSA receipt organization system. Strategy: pay medical expenses out-of-pocket, archive receipts, invest HSA funds tax-free, reimburse decades later when balance has compounded.

## Family Configuration
Family members are configured in `config/config.yaml`:
```yaml
family:
  - name: "Alice"    # Primary account holder
    role: "primary"
  - name: "Bob"      # Spouse
    role: "spouse"
  - name: "Charlie"  # Dependent
    role: "dependent"
```

Default fallback (if not configured): `["Alice", "Bob", "Charlie"]`

## Architecture

### Vision LLM Extraction
- Uses local Ollama/vLLM with vision models (Mistral Small 3, LLaVA, etc.)
- Default endpoint: `http://localhost:11434/v1`
- Direct image-to-JSON extraction (no separate OCR step)
- Prompt constrains patient_name to configured family members

### Text-Only EOB Extraction
- Uses text extraction via pdfplumber for EOBs (faster, more reliable)
- Supports multi-claim extraction (multiple patients/dates per EOB)
- HSA date filtering: skips claims with service_date before HSA start

### Google APIs
- **Drive**: Stores receipts in `HSA_Receipts/{year}/{category}/{patient}/`
- **Sheets**: Master index spreadsheet `HSA_Master_Index` tracks all records
- **Gmail**: Scans for medical provider emails with attachments

### Folder Structure
```
HSA_Receipts/
├── 2024/
│   ├── Medical/
│   │   ├── Alice/
│   │   ├── Bob/
│   │   └── Charlie/
│   ├── Dental/
│   ├── Vision/
│   ├── Pharmacy/
│   └── EOBs/
│       ├── Medical/
│       ├── Dental/
│       └── Vision/
├── _Inbox/      # Drop files here for auto-processing
├── _Processing/ # Files being processed
└── _Rejected/   # Files that failed processing
```

## CLI Commands
```bash
# Initial setup
lazy-hsa setup

# Process single file or directory
lazy-hsa process --file receipt.pdf
lazy-hsa process --dir ./receipts/ --patient Alice
lazy-hsa process --file costco_receipt.png --dry-run

# Process files from Google Drive _Inbox
lazy-hsa inbox              # One-time check
lazy-hsa inbox --watch      # Continuous polling
lazy-hsa inbox --dry-run    # Preview extraction

# Scan Gmail for medical emails
lazy-hsa email-scan --since 2024-01-01

# View summary
lazy-hsa summary

# Reconcile EOBs and statements
lazy-hsa reconcile              # Current year
lazy-hsa reconcile --year 2024  # Specific year
lazy-hsa reconcile --push       # Push summary to Google Sheets
```

## Key Files
- `src/pipeline.py` - Main orchestration, CLI commands
- `src/processors/llm_extractor.py` - Vision LLM extraction, multi-claim EOB extraction, provider skills
- `src/storage/gdrive_client.py` - Google Drive operations
- `src/storage/sheet_client.py` - Google Sheets tracking, duplicate detection, EOB-statement linking
- `src/watchers/inbox_watcher.py` - Drive _Inbox folder watcher
- `src/extractors/gmail_extractor.py` - Gmail medical email extraction
- `config/config.yaml` - All configuration (LLM endpoint, family members, etc.)

## Provider Skills System

Provider-specific extraction prompts activate automatically based on filename/content patterns. Defined in `src/processors/llm_extractor.py`:

| Provider | Triggers | Special Handling |
|----------|----------|------------------|
| **Costco** | "costco", "store 423" | Looks for "F" column marker, sums only F-marked items |
| **CVS** | "cvs" | Prescription vs OTC: copay (AMOUNT DUE) for Rx, FSA markers for OTC, 2-digit year handling |
| **Walgreens** | "walgreens" | FSA/HSA markers, copay extraction |
| **Amazon** | "amazon" | Extracts Grand Total directly (includes tax) |
| **Express Scripts** | "express scripts", "esrx" | Mail-order pharmacy, **multi-claim extraction**, medication name extraction |
| **Sutter** | "sutter", "pamf" | Hospital/clinic bills, **multi-claim extraction**, guarantor vs patient distinction |
| **Aetna** | "aetna" (filename or content) | Medical EOB, **multi-claim extraction**, text-only via pdfplumber |
| **Delta Dental** | "delta dental" | Dental EOB, Patient Pays field |
| **VSP** | "vsp" | Vision EOB format |
| **Stanford** | "stanford" (content) | Hospital statements, Patient Responsibility field |

### Tax Calculation (Retail Receipts)
For retail receipts (Costco, CVS, etc.), the system:
1. LLM extracts: `eligible_subtotal`, `receipt_tax`, `receipt_taxable_amount`
2. Python calculates: `tax_rate = receipt_tax / receipt_taxable_amount`
3. Python calculates: `tax_on_eligible = eligible_subtotal * tax_rate`
4. Final amount: `patient_responsibility = eligible_subtotal + tax_on_eligible`

IRS allows HSA reimbursement of sales tax on eligible items.

### Adding New Provider Skills
1. Add skill to `PROVIDER_SKILLS` dict in `llm_extractor.py`
2. Add pattern to `provider_patterns` in `detect_provider_skill()`
3. Test with `lazy-hsa inbox --dry-run` before committing

## Record Authority & Summary Filtering

The `Is Authoritative` column in the master spreadsheet controls which records count in totals:

| Value | Meaning | Counted in summary? |
|-------|---------|---------------------|
| `"Yes"` | EOB or authoritative record | Yes |
| `"No"` | Linked subordinate (statement/duplicate) | **No** |
| `""` (empty) | Standalone record, no link | Yes |

**Key rule**: `_is_countable_record()` in `sheet_client.py` excludes any record with `Is Authoritative = "No"`, regardless of whether `Linked Record ID` is set. This prevents double-counting orphaned non-authoritative records.

**Ingestion behavior** (`pipeline.py` + `sheet_client.py:add_record()`):
- EOBs always get `is_authoritative=True` → writes `"Yes"`
- Linked subordinate records get `is_authoritative=False` with a `linked_record_id` → writes `"No"`
- Standalone receipts/statements get `is_authoritative=False` with no link → writes `""`

## Development Notes

### Running with Poppler (for PDF processing)
```bash
# macOS
brew install poppler
PATH="/opt/homebrew/opt/poppler/bin:$PATH" uv run lazy-hsa inbox
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
- Config: `config/config.yaml` (gitignored, copy from config.example.yaml)

## Backlog

No outstanding items — all reconciliation features shipped.
