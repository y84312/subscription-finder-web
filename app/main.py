"""Subscription Finder Web — CSV upload → subscription detection."""
import os, sys, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.detector import SubscriptionDetector
from src.csv_parser import parse_csv

app = FastAPI(title="Subscription Finder")

BASE_DIR = Path(__file__).parent.parent
templates_dir = BASE_DIR / "app" / "templates"

UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


HTML_HEADER = """<!DOCTYPE html><html lang="et"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tellimuste leidja</title>
<script src="https://cdn.tailwindcss.com"></script>
</head><body class="bg-gray-50 min-h-screen">
<div class="max-w-2xl mx-auto px-4 py-12">"""

HTML_FOOTER = """
<div class="mt-8 text-center text-sm text-gray-400">
Andmed ei salvestu serverisse. CSV: kuupäev · saaja · summa · selgitus
</div></div></body></html>"""


def render_index():
    upload = templates_dir / "index.html"
    return HTMLResponse(upload.read_text(encoding="utf-8"))


def _fmt_eur(v):
    return f"{v:.2f}"


def render_results(tx_count, subscriptions, file_name="", error=None):
    lines = [HTML_HEADER]

    lines.append('<a href="/" class="text-blue-600 hover:underline text-sm">← Tagasi</a>')

    if error:
        lines.append(f'''
        <div class="mt-6 bg-red-50 border border-red-200 rounded-xl p-6 text-center">
            <div class="text-4xl mb-3">⚠️</div>
            <p class="text-red-700 font-medium">{error}</p>
        </div>''')

    if subscriptions:
        active = [s for s in subscriptions if s.is_active]
        inactive = [s for s in subscriptions if not s.is_active]
        total_monthly = sum(s.monthly_equivalent for s in active)
        total_yearly = sum(s.estimated_yearly_cost for s in active)

        lines.append(f'''
        <div class="mt-6 bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
            <h2 class="text-xl font-bold text-gray-900 mb-1">📊 {file_name}</h2>
            <p class="text-gray-500 text-sm">{tx_count} tehingut analüüsitud</p>
            <div class="mt-6 grid grid-cols-2 gap-4">
                <div class="bg-blue-50 rounded-xl p-4 text-center">
                    <div class="text-2xl font-bold text-blue-700">{len(active)}</div>
                    <div class="text-xs text-blue-500 mt-1">aktiivset tellimust</div>
                </div>
                <div class="bg-green-50 rounded-xl p-4 text-center">
                    <div class="text-2xl font-bold text-green-700">{_fmt_eur(total_monthly)} €</div>
                    <div class="text-xs text-green-500 mt-1">kuus kokku</div>
                </div>
                <div class="bg-purple-50 rounded-xl p-4 text-center col-span-2">
                    <div class="text-3xl font-bold text-purple-700">{_fmt_eur(total_yearly)} €</div>
                    <div class="text-xs text-purple-500 mt-1">hinnanguline aastakulu</div>
                </div>
            </div>
        </div>''')

        # Active subs
        if active:
            lines.append('<h3 class="mt-8 mb-4 text-lg font-semibold text-gray-800">Aktiivsed tellimused</h3>')
            lines.append('<div class="space-y-3">')
            for sub in active:
                ce = "bg-green-400" if sub.confidence > 0.7 else "bg-yellow-400" if sub.confidence > 0.4 else "bg-red-400"
                freq = {"monthly":"/kuu","weekly":"/nädal","bi-weekly":"/2 nädalat","quarterly":"/kvartal","yearly":"/aasta"}.get(sub.frequency,"")
                lines.append(f'''
                <div class="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                    <div class="flex justify-between items-start">
                        <div>
                            <div class="flex items-center gap-2">
                                <span class="w-3 h-3 rounded-full {ce}"></span>
                                <span class="font-semibold text-gray-900">{sub.merchant_name}</span>
                            </div>
                            <div class="mt-2 text-sm text-gray-600">
                                <span class="font-medium">{_fmt_eur(sub.amount)} EUR</span>{freq}
                            </div>
                            <div class="mt-1 text-xs text-gray-400">
                                Kinnitus: {int(sub.confidence*100)}% · {sub.occurrence} korda
                            </div>
                        </div>
                        <div class="text-right">
                            <div class="text-lg font-bold text-gray-800">{_fmt_eur(sub.monthly_equivalent)} €</div>
                            <div class="text-xs text-gray-400">kuus</div>
                        </div>
                    </div>
                </div>''')
            lines.append('</div>')

        # Inactive
        if inactive:
            lines.append('<h3 class="mt-8 mb-4 text-lg font-semibold text-gray-500">Viimati mitte-täidetud</h3>')
            for sub in inactive:
                lines.append(f'<div class="bg-gray-50 rounded-lg p-3 text-sm text-gray-600">{sub.merchant_name} — {_fmt_eur(sub.amount)} EUR</div>')

    elif not error:
        lines.append('<div class="mt-6 text-center text-gray-500"><p>Ei leidnud tellimuste musterit.</p></div>')

    lines.append(HTML_FOOTER)
    return HTMLResponse("\n".join(lines))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return render_index()


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".csv"):
        return render_results(0, [], error="Ainult CSV faile toetatud.")

    content = await file.read()

    transactions = parse_csv(content)
    if not transactions:
        return render_results(0, [], error="Ei suutnud CSV parsimisel ühtegi tehingut leida. Kontrolli formaati.")

    detector = SubscriptionDetector()
    subscriptions = detector.detect(transactions)

    return render_results(len(transactions), subscriptions, file_name=file.filename)


@app.get("/health")
async def health():
    return {"status": "ok"}
