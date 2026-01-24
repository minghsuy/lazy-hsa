# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-01-24

### Added
- **Open Source Release**: First public release as `lazy-hsa`
- **Multi-Claim EOB Extraction**: Extract multiple claims from single Aetna EOB
  - Different patients and service dates automatically split into separate records
  - HSA date filtering: claims before HSA start date are automatically skipped
- **EOB-Statement Linking**: Bidirectional links between EOB claims and provider statements
  - EOB marked as authoritative for reimbursement calculations
  - Avoids double-counting in summary totals
- **Content-Based Provider Detection**: Detect provider from PDF content, not just filename
- **Text-Only EOB Extraction**: Uses pdfplumber for faster, more reliable EOB parsing

### Changed
- **CLI renamed**: `hsa` → `lazy-hsa`
- **Package renamed**: `hsa-receipt-system` → `lazy-hsa`
- Family members now fully config-driven (no hardcoded names)
- Default LLM endpoint changed to `localhost:11434` for privacy
- Added 3 new spreadsheet columns: Original Provider, Linked Record ID, Is Authoritative

### Fixed
- ValueError when all eligible claims lack service_date (use `min(..., default=...)`)

## [0.3.0] - 2026-01-22

### Added
- **Multi-page PDF Support**: Extract text from all pages using pdfplumber
  - Key financial data often spans multiple pages (e.g., Stanford statements)
  - Falls back to image-only extraction if text extraction fails
- **Stanford Health Care Provider Skill**: Specialized extraction for Stanford hospital statements
  - Detects Patient Responsibility, Balance Due, Service Date
  - Handles multi-page statement format
- **CID Font Decoding**: Decode CID-encoded PDF fonts (e.g., `(cid:84)` → `T`)
- **Text Cleaning**: Remove QR code binary patterns and hex data from extracted text
- **Claude Code Review Workflow**: Automated PR code review via GitHub Actions

### Changed
- PDF image conversion now limits to first 5 pages (efficiency improvement)
- Extraction constants extracted: `MIN_PAGE_TEXT_LENGTH`, `MAX_FALLBACK_PAGES`, `MAX_PDF_PAGES`
- Improved exception handling in pdfplumber with specific error types

### Fixed
- CID decoder logic: check newline (cid=10) before printable ASCII range
- Misleading comment in image fallback ("Merge" → "Replace")
- Removed redundant `import re` statements inside methods

## [0.2.0] - 2026-01-04

### Added
- **Provider Skills System**: Specialized extraction rules for 8 providers
  - Costco: Detects "F" markers for FSA-eligible items
  - CVS, Walgreens: FSA/HSA eligible label detection
  - Amazon: Grand Total extraction from order summaries
  - Sutter, Kaiser: Healthcare EOB field extraction
  - Delta Dental, VSP: Dental/vision EOB support
- **HEIC/HEIF Support**: Process iPhone photos directly via pillow-heif
- **Dry-run Mode**: Preview extraction without committing (`hsa inbox --dry-run`)
- **Patient Detection**: Extract patient name from filenames (e.g., `cvs_ming_rx.pdf`)
- **Python Tax Calculation**: Calculate tax on eligible items using extracted rate
- **Duplicate Detection**: Prevent duplicate records in spreadsheet

### Changed
- Extraction schema uses `eligible_subtotal`, `receipt_tax`, `receipt_taxable_amount`
- Tax calculation moved from LLM to Python for accuracy
- Provider detection from image content (not just filename)

### Fixed
- Security: Use `tempfile` module instead of hardcoded `/tmp` paths
- All ruff lint issues resolved (import sorting, type hints)

### Removed
- Amazon HSA Store scraper (authentication too complex)

## [0.1.0] - 2026-01-02

### Added
- Initial release
- Vision LLM extraction with Mistral Small 3 on Ollama
- Google Drive folder structure and automatic upload
- Google Sheets master index tracking
- Gmail scanning for medical provider emails
- Drive `_Inbox` watcher for automatic processing
- CLI commands: `setup`, `process`, `inbox`, `email-scan`, `summary`
- Family member configuration via config file
- Category routing (Medical, Dental, Vision, Pharmacy, EOBs)
