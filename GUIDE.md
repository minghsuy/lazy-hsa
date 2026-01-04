# HSA Receipt Organization System - Comprehensive Guide

**Last Updated:** January 3, 2026  
**HSA Start Date:** January 1, 2026  
**Provider:** Fidelity HSA

---

## Strategy

- **Pay out of pocket** for all medical expenses now
- **Archive receipts** with bulletproof documentation
- **Invest HSA funds** in FZROX/FSKAX index funds
- **Reimburse decades later** when balance has compounded tax-free
- **No time limit** on reimbursement (post-HSA establishment)

> **Critical**: Only expenses incurred **on or after January 1, 2026** are reimbursable.

---

## Data Sources

| Source | Email | Providers |
|--------|-------|-----------|
| Ming Gmail | [your@gmail.com] | Sutter Health, CVS, Express Scripts |
| Ming iCloud | [your@icloud.com] | Stanford Health |
| Wife Gmail | [wife@gmail.com] | Sutter Health, CVS |
| Wife iCloud | [wife@icloud.com] | Stanford Health |

---

## Google Drive Folder Structure

```
HSA_Receipts/
├── 2026/
│   ├── Medical/
│   │   ├── Ming/
│   │   ├── [Wife]/
│   │   └── [Son]/
│   ├── Dental/
│   ├── Vision/
│   ├── Pharmacy/
│   └── EOBs/
├── _Inbox/
├── _Processing/
└── _Rejected/
```

---

## File Naming Convention

```
YYYY-MM-DD_Provider_ServiceType_$Amount.pdf
```

Examples:
- `2026-01-15_Stanford_Cardiology_$150.00.pdf`
- `2026-02-10_CVS_Zepbound_$25.00.pdf`

For reimbursed: append `.reimbursed`

---

## Processing Pipeline (on DGX Spark)

```
Sources → PaddleOCR (GPU) → Local LLM → Google Drive + Sheet
```

**Stack:**
- OCR: PaddleOCR 3.0 (GPU)
- LLM: Llama 3.3 70B or Qwen2.5-VL 72B via vLLM
- Storage: Google Drive API
- Tracking: Google Sheets

---

## Brother Scanner Setup (HL-3290CDW)

1. Access `http://<printer-ip>`
2. **Scan** → **Scan to E-mail**
3. SMTP: `smtp.gmail.com:587` + STARTTLS
4. Destination: `receipts.weng@gmail.com`

---

## Maintenance Schedule

**Weekly (15 min):**
- Check `_Inbox` for new items
- Run processing pipeline
- Review low-confidence extractions

**Monthly (30 min):**
- Download from all provider portals
- Reconcile tracking sheet with EOBs

**Quarterly:**
- Backup Google Drive locally
- Verify HSA investment allocation

---

## HSA Eligibility Quick Reference

**✅ Always Eligible:**
- Doctor visits, hospital, surgery, labs
- Prescription medications
- Dental (cleanings, fillings, crowns, ortho)
- Vision (exams, glasses, contacts, LASIK)
- OTC medications (post-CARES Act)

**❌ NOT Eligible:**
- Cosmetic surgery (unless medically necessary)
- Gym memberships
- Teeth whitening
- General wellness vitamins

---

## Quick Start Commands

```bash
cd ~/Documents/Github/hsa-receipt-system

# Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp config/config.example.yaml config/config.yaml
# Edit with your details

# Initial setup (creates folders + spreadsheet)
python src/pipeline.py setup --family "Ming" "WifeName" "SonName"

# Process receipts
python src/pipeline.py dry-run --file /path/to/receipt.pdf
python src/pipeline.py process --dir /path/to/inbox/

# View summary
python src/pipeline.py summary
```

---

## TODO: Fill In

1. Wife's name
2. Son's name
3. Gmail addresses (both)
4. iCloud addresses (both)
5. Brother printer IP
