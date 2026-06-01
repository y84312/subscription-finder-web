"""
CSV parser for bank transaction files.
Supports common Estonian bank CSV export formats.
"""
import csv, io, re
from datetime import date
from typing import Optional
from src.models import Transaction

DATE_COLS = ["kuupäev","date","kuup","booking date","value date"]
AMOUNT_COLS = ["summa","amount","kogus","debit","credit","deebet","kreedit"]
MERCHANT_COLS = ["saaja","maksja","recipient","payer","creditor","debtor","nimi","name","partner"]
DESC_COLS = ["selgitus","description","viite","reference"]

def _find_col(headers, candidates):
    h = [c.strip().lower() for c in headers]
    for cand in candidates:
        for i, v in enumerate(h):
            if cand in v or v in cand:
                return i
    return None

def _parse_date(v):
    v = v.strip()
    for pat in [r"(\d{1,2})\.(\d{1,2})\.(\d{4})", r"(\d{4})-(\d{2})-(\d{2})", r"(\d{1,2})/(\d{1,2})/(\d{4})"]:
        m = re.match(pat, v)
        if m:
            a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
            # YYYY-MM-DD: first group is year
            if pat.startswith(r"(\d{4})"):
                try: return date(a, b, c)
                except ValueError: continue
            else:
                # DD.MM.YYYY or DD/MM/YYYY
                try: return date(c, b, a)
                except ValueError: continue
    return None

def _parse_amount(v):
    v = v.strip().replace(" ", "").replace(",", ".")
    if v.endswith("-"):
        v = "-" + v[:-1]
    try: return float(v)
    except (ValueError, TypeError): return None

def parse_csv(content: bytes) -> list:
    text = content.decode("utf-8-sig")
    first = text.split("\n")[0]
    delim = "," if first.count(",") > first.count(";") else ";"
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows: return []

    headers = rows[0]
    di = _find_col(headers, DATE_COLS)
    ai = _find_col(headers, AMOUNT_COLS)
    mi = _find_col(headers, MERCHANT_COLS)
    ci = _find_col(headers, DESC_COLS)

    if di is None or ai is None:
        if len(headers) >= 4:
            di, ai, mi, ci = di or 0, ai or 2, mi or 1, ci or 3
        else: return []

    transactions = []
    for idx, row in enumerate(rows[1:], 1):
        mx = max(filter(None, [di, ai, mi or 0, ci or 0]))
        if len(row) <= mx: continue

        tx_date = _parse_date(row[di])
        amount = _parse_amount(row[ai])
        if tx_date is None or amount is None: continue

        merchant = row[mi].strip() if mi is not None and mi < len(row) else ""
        desc = row[ci].strip() if ci is not None and ci < len(row) else ""
        if not merchant and desc: merchant = desc[:50]

        transactions.append(Transaction(
            id=f"tx-{idx:06d}",
            merchant_name=merchant,
            amount=abs(amount),
            currency="EUR",
            date=tx_date,
            description=desc,
            is_debit=amount < 0,
        ))
    return transactions
