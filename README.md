# lazy-hsa

[![License](https://img.shields.io/github/license/minghsuy/lazy-hsa)](LICENSE)

A local AI-powered HSA receipt organization system. Document reading runs on a local model, so no cloud AI service sees your documents. Your files and records are stored in your own Google Drive and Google Sheet (see [Privacy & Security](#privacy--security)).

## The Strategy

**Why "lazy"?** Because the best HSA strategy requires almost no active management:

1. **Pay all medical expenses out of pocket** - Don't touch your HSA funds
2. **Invest HSA funds in index funds** - Let compound growth work for decades
3. **Archive receipts with bulletproof documentation** - This tool handles it
4. **Reimburse yourself in 25+ years** - When your balance has grown 5-10x tax-free

This is the [Boglehead HSA strategy](https://www.bogleheads.org/wiki/Health_savings_account) - treat your HSA as a stealth retirement account. The IRS has no time limit on reimbursements, so a $1,000 medical bill today could become a $5,000+ tax-free withdrawal in retirement.

**lazy-hsa** automates the tedious part: organizing receipts so they're audit-proof decades from now.

## Features

- **Local AI extraction** - Uses Ollama/vLLM with vision models (Mistral Small 3, gpt-oss:20b, LLaVA, etc.)
- **Local AI, Google storage** - AI extraction runs on your machine. Processed files go to your Google Drive and records go to your Google Sheet.
- **Multi-page PDF support** - Uses pdfplumber to extract text from all pages, not just the first
- **Multi-claim EOB support** - Extracts multiple claims from insurance EOBs automatically
- **Provider skills** - Specialized extraction for CVS, Costco, Stanford, Aetna, and more
- **Google Drive organization** - Automatic folder structure by year/category/patient
- **Master spreadsheet** - Track everything in Google Sheets for easy reimbursement
- **Duplicate detection** - Links EOBs to provider statements, avoids double-counting

## Quick Start

### 1. Install

```bash
git clone https://github.com/minghsuy/lazy-hsa.git
cd lazy-hsa
RELEASE_TAG="$(git describe --tags --abbrev=0)"
git checkout --detach "$RELEASE_TAG"
uv sync --frozen
uv run lazy-hsa --help
```

Releases are currently source-only. PyPI and unsigned binary distributions are
not supported. The commands above select the most recent release tag reachable
from the cloned default branch and install the dependency versions committed in
that tag's lockfile.

### 2. Set Up Ollama

```bash
# Install Ollama (https://ollama.ai)
ollama pull mistral-small3  # or any vision-capable model
ollama serve
```

**Recommended models:**
| Model | Size | Notes |
|-------|------|-------|
| `mistral-small3` | 14B | Good balance of speed and accuracy |
| `gpt-oss:20b` | 20B | Better JSON output for complex EOBs |
| `gpt-oss:120b` | 120B | Highest accuracy (requires significant VRAM) |

**Hardware options:**
- **CPU/Consumer GPU**: Ollama with mistral-small3 works fine, just slower
- **NVIDIA DGX Spark**: Ideal for running larger models (20B-120B) with fast inference
- **Any vLLM-compatible server**: Point `api_base` to your inference endpoint

### 3. Set Up Google APIs

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable: Google Drive API, Google Sheets API, Gmail API
3. Create OAuth 2.0 credentials (Desktop app)
4. Download as `config/credentials/gdrive_credentials.json`

This lets the tool read and write files in your Google Drive (full Drive scope, needed to move files out of `_Inbox`) and your tracking Sheet. If you use `email-scan`, it also gets read-only access to Gmail.

### 4. Configure

```bash
cp config/config.example.yaml config/config.yaml
# Edit config.yaml with your family members, HSA start date, etc.
```

### 5. Initialize

```bash
uv run lazy-hsa setup
```

## Usage

### Process receipts from Google Drive _Inbox

Drop files into the `_Inbox` folder in Google Drive, then:

```bash
# Preview what would happen
uv run lazy-hsa inbox --dry-run

# Process all files
uv run lazy-hsa inbox

# Continuous watch mode
uv run lazy-hsa inbox --watch
```

### Process a single file

```bash
uv run lazy-hsa process --file /path/to/receipt.pdf
uv run lazy-hsa process --file /path/to/receipt.pdf --patient Alice
```

### Review and confirm

Every extracted record lands as `Pending` and does not count in totals until you confirm it. Check it against the document, then:

```bash
uv run lazy-hsa confirm 41 42
```

You can also type `Confirmed` into the record's `Review Status` cell in the sheet.

An existing master sheet needs the `Review Status` column once. `inbox` refuses to run until it exists:

```bash
uv run lazy-hsa migrate-sheet          # dry run: shows what it would change
uv run lazy-hsa migrate-sheet --apply
```

### View summary

```bash
uv run lazy-hsa summary
```

Totals exclude records awaiting review. The summary lists those records separately, with the amount that confirming them would add.

Output:
```
HSA Expense Summary
==================================================

2024:
  Receipts: 15
  Billed: $3,450.00
  Insurance: $2,760.00
  Your cost: $690.00
  Reimbursed: $0.00

Total Unreimbursed: $690.00
```

## Folder Structure

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
├── _Inbox/         # Drop files here
├── _Processing/
└── _Rejected/
```

## Provider Skills

Built-in extraction rules for common providers:

| Provider | Detection | Special Handling |
|----------|-----------|------------------|
| **Costco** | "costco" in filename | FSA star markers, tax calculation |
| **CVS** | "cvs" in filename | FSA/HSA labels, Rx numbers |
| **Walgreens** | "walgreens" in filename | FSA/HSA markers |
| **Amazon** | "amazon" in filename | Grand Total extraction |
| **Express Scripts** | "express scripts" | Mail-order pharmacy |
| **Sutter/PAMF** | "sutter" or "pamf" | Patient Responsibility field |
| **Stanford** | "stanford" in content | Hospital statements |
| **Aetna** | "aetna" in content | Deterministic multi-claim EOB parser (no LLM needed) |
| **Delta Dental** | "delta dental" | Dental EOB format |
| **VSP** | "vsp" | Vision EOB format |

### Adding New Providers

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for how to add provider skills.

## How EOBs and Medical Bills Work Together

Medical expenses typically generate two documents:

1. **Provider Statement/Bill** - From the hospital, clinic, or pharmacy (e.g., Stanford Health, CVS)
2. **EOB (Explanation of Benefits)** - From your insurance company (e.g., Aetna, Delta Dental)

### The Problem

These documents often have different amounts:
- Provider bill shows what they charged
- EOB shows what insurance actually paid and what you owe

For HSA reimbursement, **the EOB is authoritative** - it shows your true out-of-pocket cost.

### How lazy-hsa Handles This

```
You receive:                    lazy-hsa does:
─────────────────────────────────────────────────────────────
Stanford bill ($250)      →     Stores in Medical/Alice/
                                Records: billed=$250, your_cost=$250

Aetna EOB arrives         →     Extracts multiple claims from EOB
(shows Stanford visit)          Stores EOB in EOBs/Medical/
                                Links EOB to Stanford bill
                                Updates: your_cost=$45 (from EOB)
                                Marks EOB as authoritative
```

### Multi-Claim EOB Extraction

A single Aetna EOB often contains multiple claims:
- Different dates of service
- Different family members
- Different providers

lazy-hsa extracts each claim separately:

```
One Aetna EOB PDF containing:
├── Dec 15: Alice - Stanford Urgent Care - $45 owed
├── Dec 18: Bob - Quest Diagnostics - $0 owed
├── Dec 20: Alice - Stanford Lab - $12 owed
└── Jan 05: Charlie - Pediatrics - $25 owed

Creates separate spreadsheet entries for each claim.
```

### HSA Date Filtering

Claims with service dates **before your HSA start date** are automatically skipped:

```yaml
# config.yaml
hsa:
  start_date: "2024-01-01"
```

If an EOB contains claims from December 2023 and January 2024, only the January claims are processed.

### Folder Structure

```
HSA_Receipts/2024/
├── Medical/
│   └── Alice/
│       └── 2024-01-15_Stanford_Urgent_Care_$45.00.pdf  ← Provider bill
└── EOBs/
    └── Medical/
        └── 2024-01-20_Aetna_Medical_EOB.pdf  ← Insurance EOB
```

EOBs go to `EOBs/{category}/` to keep them separate from provider receipts.

### Spreadsheet Linking

The master spreadsheet tracks both documents and links them:

| Date | Provider | Patient | Billed | Insurance Paid | Your Cost | Linked Record | Is Authoritative |
|------|----------|---------|--------|----------------|-----------|---------------|------------------|
| 2024-01-15 | Stanford | Alice | $250 | $205 | $45 | Row 15 | No |
| 2024-01-20 | Aetna EOB | Alice | $250 | $205 | $45 | Row 14 | Yes |
| 2024-02-10 | CVS | Bob | $70 | $0 | $70 | - | *(empty)* |

The `Is Authoritative` column uses three values:
- **Yes** — EOBs and authoritative records (always counted in totals)
- **No** — Linked subordinate records like provider statements (always excluded from totals)
- *(empty)* — Standalone records with no linked counterpart (always counted in totals)

## Supported Formats

- PDF (single and multi-page)
- PNG, JPEG, TIFF, BMP, WebP, GIF
- HEIC/HEIF (iPhone photos)

## Privacy & Security

Document reading is local. Storage is not: today, files and records are kept in Google.

### What goes where

| Data | Today | After the planned migration |
|------|-------|-----------------------------|
| Document files (receipts, EOBs) | Uploaded to your Google Drive by the pipeline | Kept on a self-hosted box you run. An encrypted off-site replica is the backup. A browseable Drive copy is optional and undecided. |
| Extracted records (provider, dates, patient name, amounts, notes) | Written to your Google Sheet | Kept in a self-hosted SQLite store. The Sheet becomes an archive. |
| Email | `email-scan` reads Gmail with a read-only scope | No change planned |
| AI extraction | Local Ollama/vLLM model. Nothing is sent to a cloud AI API. | No change planned |
| Credentials | OAuth token files in `config/credentials/` (gitignored) on the machine that runs the CLI | Google tokens are still needed only while Google is used |

The optional phone capture service sends files over Tailscale to a self-hosted box (tailnet only, never Funnel). Files are stored there by content hash. Its encrypted local backup stays on the same host.

If you point `api_base` at a remote inference server, your documents go to that server. Keep it local to keep documents on your machine during extraction.

The migration plan is in [docs/ROADMAP.md](docs/ROADMAP.md). It is not done. The encrypted off-site replica and a tested restore from it must exist before the cutover.

## Requirements

- Python 3.12+
- Ollama with a vision-capable model
- Google Cloud project with Drive/Sheets/Gmail APIs enabled
- GPU recommended for faster extraction (but CPU works)

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Lint
uv run ruff check src/
```

## License

MIT License - See [LICENSE](LICENSE)

## Acknowledgments

Inspired by the [Bogleheads community](https://www.bogleheads.org/) and the FIRE movement's approach to HSA optimization.
