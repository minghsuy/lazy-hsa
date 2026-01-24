# lazy-hsa

A privacy-first, local AI-powered HSA receipt organization system. Your medical data never leaves your machine.

## The Strategy

**Why "lazy"?** Because the best HSA strategy requires almost no active management:

1. **Pay all medical expenses out of pocket** - Don't touch your HSA funds
2. **Invest HSA funds in index funds** - Let compound growth work for decades
3. **Archive receipts with bulletproof documentation** - This tool handles it
4. **Reimburse yourself in 25+ years** - When your balance has grown 5-10x tax-free

This is the [Boglehead HSA strategy](https://www.bogleheads.org/wiki/Health_savings_account) - treat your HSA as a stealth retirement account. The IRS has no time limit on reimbursements, so a $1,000 medical bill today could become a $5,000+ tax-free withdrawal in retirement.

**lazy-hsa** automates the tedious part: organizing receipts so they're audit-proof decades from now.

## Features

- **Local AI extraction** - Uses Ollama/vLLM with vision models (Mistral Small 3, LLaVA, etc.)
- **Privacy-first** - All processing happens on your machine. Medical data never hits the cloud.
- **Multi-claim EOB support** - Extracts multiple claims from insurance EOBs automatically
- **Provider skills** - Specialized extraction for CVS, Costco, Stanford, Aetna, and more
- **Google Drive organization** - Automatic folder structure by year/category/patient
- **Master spreadsheet** - Track everything in Google Sheets for easy reimbursement
- **Duplicate detection** - Links EOBs to provider statements, avoids double-counting

## Quick Start

### 1. Install

```bash
git clone https://github.com/yourusername/lazy-hsa.git
cd lazy-hsa

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

### 2. Set Up Ollama

```bash
# Install Ollama (https://ollama.ai)
ollama pull mistral-small3  # or any vision-capable model
ollama serve
```

### 3. Set Up Google APIs

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable: Google Drive API, Google Sheets API, Gmail API
3. Create OAuth 2.0 credentials (Desktop app)
4. Download as `config/credentials/gdrive_credentials.json`

### 4. Configure

```bash
cp config/config.example.yaml config/config.yaml
# Edit config.yaml with your family members, HSA start date, etc.
```

### 5. Initialize

```bash
lazy-hsa setup
```

## Usage

### Process receipts from Google Drive _Inbox

Drop files into the `_Inbox` folder in Google Drive, then:

```bash
# Preview what would happen
lazy-hsa inbox --dry-run

# Process all files
lazy-hsa inbox

# Continuous watch mode
lazy-hsa inbox --watch
```

### Process a single file

```bash
lazy-hsa process --file /path/to/receipt.pdf
lazy-hsa process --file /path/to/receipt.pdf --patient Alice
```

### View summary

```bash
lazy-hsa summary
```

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
| **Aetna** | "aetna" in content | Multi-claim EOB extraction |
| **Delta Dental** | "delta dental" | Dental EOB format |
| **VSP** | "vsp" | Vision EOB format |

### Adding New Providers

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for how to add provider skills.

## Supported Formats

- PDF (single and multi-page)
- PNG, JPEG, TIFF, BMP, WebP, GIF
- HEIC/HEIF (iPhone photos)

## Privacy & Security

- **All AI processing is local** - Ollama runs on your machine
- **Medical data stays on your machine** - Only file organization goes to Google Drive
- **OAuth tokens are local** - Stored in `config/credentials/` (gitignored)
- **No cloud AI services** - No OpenAI, Anthropic, or other cloud APIs for extraction

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
