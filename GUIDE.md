# lazy-hsa - Setup & Usage Guide

## Strategy

The Boglehead HSA optimization strategy:

1. **Pay out of pocket** for all medical expenses now
2. **Archive receipts** with bulletproof documentation
3. **Invest HSA funds** in low-cost index funds (FZROX, FSKAX, etc.)
4. **Reimburse decades later** when balance has compounded tax-free
5. **No time limit** on reimbursement (for expenses after HSA establishment)

> **Critical**: Only expenses incurred **after your HSA start date** are reimbursable.

---

## Data Sources

| Source | Examples |
|--------|----------|
| Provider portals | Sutter Health, Stanford, Kaiser, etc. |
| Insurance EOBs | Aetna, BCBS, Cigna, UnitedHealthcare |
| Pharmacy | CVS, Walgreens, Express Scripts |
| Email attachments | Bills, receipts, EOBs sent via email |
| Paper receipts | Scanned via phone or scanner |

---

## Google Drive Folder Structure

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
├── _Inbox/       # Drop files here
├── _Processing/
└── _Rejected/
```

---

## File Naming Convention

```
YYYY-MM-DD_Provider_ServiceType_$Amount.pdf
```

Examples:
- `2024-03-15_Stanford_Cardiology_$150.00.pdf`
- `2024-04-10_CVS_Prescription_$25.00.pdf`

For reimbursed files: append `.reimbursed`

---

## Processing Pipeline

```
Sources → Local LLM (Ollama) → Google Drive + Sheets
```

**Stack:**
- LLM: Mistral Small 3, LLaVA, or any vision-capable model
- Runtime: Ollama or vLLM
- Storage: Google Drive API
- Tracking: Google Sheets

---

## Scanner Setup (Optional)

If you have a network scanner:

1. Configure scan-to-email
2. Set destination to a dedicated receipts email
3. Configure Gmail label/filter to organize incoming scans

---

## Maintenance Schedule

**Weekly (15 min):**
- Check `_Inbox` for new items
- Run `lazy-hsa inbox`
- Review low-confidence extractions

**Monthly (30 min):**
- Download from provider portals
- Reconcile tracking sheet with EOBs

**Quarterly:**
- Backup Google Drive locally
- Verify HSA investment allocation

---

## HSA Eligibility Quick Reference

**Always Eligible:**
- Doctor visits, hospital, surgery, labs
- Prescription medications
- Dental (cleanings, fillings, crowns, orthodontia)
- Vision (exams, glasses, contacts, LASIK)
- OTC medications (post-CARES Act)
- Mental health services
- Physical therapy

**NOT Eligible:**
- Cosmetic surgery (unless medically necessary)
- Gym memberships
- Teeth whitening
- General wellness vitamins (unless prescribed)
- Insurance premiums (with some exceptions)

---

## Quick Start Commands

```bash
# Clone and install
git clone https://github.com/yourusername/lazy-hsa.git
cd lazy-hsa
uv sync  # or pip install -e .

# Configure
cp config/config.example.yaml config/config.yaml
# Edit config.yaml with your family members, HSA start date, etc.

# Initial setup (creates folders + spreadsheet)
lazy-hsa setup

# Process receipts
lazy-hsa inbox --dry-run    # Preview
lazy-hsa inbox              # Process all
lazy-hsa process --file /path/to/receipt.pdf

# View summary
lazy-hsa summary
```

---

## Troubleshooting

### "Ollama connection refused"
```bash
# Start Ollama
ollama serve

# Verify it's running
curl http://localhost:11434/api/tags
```

### "Google OAuth error"
```bash
# Delete tokens to re-authenticate
rm config/credentials/*_token.json
lazy-hsa setup
```

### Low confidence extractions
- Check the spreadsheet's "Confidence" column
- Values below 70% may need manual review
- Consider adding a provider skill for common formats
