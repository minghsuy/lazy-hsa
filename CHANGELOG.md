# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Family member configuration (Ming, Vanessa, Maxwell)
- Category routing (Medical, Dental, Vision, Pharmacy, EOBs)
