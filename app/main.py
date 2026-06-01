"""Subscription Finder Web — CSV upload → subscription detection."""
import html, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse
from starlette.middleware.sessions import SessionMiddleware

from src.detector import SubscriptionDetector
from src.csv_parser import parse_csv

app = FastAPI(title="Subscription Finder")

BASE_DIR = Path(__file__).parent.parent
templates_dir = BASE_DIR / "app" / "templates"

# Security: load session secret from env or use fixed fallback
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "subscription-finder-secret-2026-06"),
)

MAX_CSV_BYTES = 2 * 1024 * 1024  # 2 MB upload limit


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' https://cdn.tailwindcss.com 'unsafe-inline'; "
        "style-src 'self' https://cdn.tailwindcss.com 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


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


def _esc(s):
    """HTML-escape user-controlled strings before rendering."""
    return html.escape(str(s), quote=True)


def _gap_trend(dates):
    """Calculate average gap and trend from dates."""
    if len(dates) < 2:
        return None, None
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    avg_gap = sum(gaps) / len(gaps)
    # Trend: compare last gap to average
    if len(gaps) >= 2:
        last_gap = gaps[-1]
        if last_gap < avg_gap * 0.85:
            return avg_gap, "tugevam"
        elif last_gap > avg_gap * 1.15:
            return avg_gap, "nõrgem"
    return avg_gap, None


def _sparkline_bars(amounts):
    """Generate ASCII-like bar heights for trend visualization."""
    if not amounts or len(amounts) < 2:
        return []
    mn, mx = min(amounts), max(amounts)
    rng = mx - mn if mx > mn else 1
    bars = []
    for a in amounts:
        height = round((a - mn) / rng * 4) + 1  # 1-5
        bars.append(height)
    return bars


def _month_name(dt):
    """Estonian month abbreviation."""
    months = ["","jaan","veebr","märts","apr","mai","juuni","juuli","aug","sept","okt","nov","dets"]
    return months[dt.month] if 1 <= dt.month <= 12 else str(dt.month)


def render_results(tx_count, subscriptions, file_name="", error=None):
    lines = [HTML_HEADER]

    lines.append('<a href="/" class="text-blue-600 hover:underline text-sm">← Tagasi</a>')

    if error:
        lines.append(f'''
        <div class="mt-6 bg-red-50 border border-red-200 rounded-xl p-6 text-center">
            <div class="text-4xl mb-3">⚠️</div>
            <p class="text-red-700 font-medium">{_esc(error)}</p>
        </div>''')

    if subscriptions:
        active = [s for s in subscriptions if s.is_active]
        inactive = [s for s in subscriptions if not s.is_active]
        total_monthly = sum(s.monthly_equivalent for s in active)
        total_yearly = sum(s.estimated_yearly_cost for s in active)

        # ── Summary cards ──
        lines.append(f'''
        <div class="mt-6 bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
            <h2 class="text-xl font-bold text-gray-900 mb-1">📊 {_esc(file_name)}</h2>
            <p class="text-gray-500 text-sm">{tx_count} tehingut analüüsitud · {len(subscriptions)} tellimust leitud</p>
            <div class="mt-6 grid grid-cols-3 gap-3">
                <div class="bg-blue-50 rounded-xl p-4 text-center">
                    <div class="text-2xl font-bold text-blue-700">{len(active)}</div>
                    <div class="text-xs text-blue-500 mt-1">aktiivset</div>
                </div>
                <div class="bg-green-50 rounded-xl p-4 text-center">
                    <div class="text-2xl font-bold text-green-700">{_fmt_eur(total_monthly)} €</div>
                    <div class="text-xs text-green-500 mt-1">kuus</div>
                </div>
                <div class="bg-purple-50 rounded-xl p-4 text-center">
                    <div class="text-2xl font-bold text-purple-700">{_fmt_eur(total_yearly)} €</div>
                    <div class="text-xs text-purple-500 mt-1">aastas ~</div>
                </div>
            </div>
        </div>''')

        # ── Detailed table ──
        if active:
            lines.append('<h3 class="mt-8 mb-4 text-lg font-semibold text-gray-800">Tellimuste ülevaade</h3>')
            lines.append('''
            <div class="overflow-x-auto -mx-4 px-4">
            <table class="w-full text-sm border-collapse">
                <thead>
                    <tr class="text-left text-gray-500 border-b border-gray-200">
                        <th class="py-2 pr-4 font-medium">Tellimus</th>
                        <th class="py-2 pr-4 font-medium">Summa</th>
                        <th class="py-2 pr-4 font-medium">Sagedus</th>
                        <th class="py-2 pr-4 font-medium">Vahe</th>
                        <th class="py-2 pr-4 font-medium">Kinnitus</th>
                        <th class="py-2 pr-4 font-medium text-right">Kuu €</th>
                        <th class="py-2 pl-4 font-medium text-right">Aasta €</th>
                    </tr>
                </thead>
                <tbody>''')

            for sub in active:
                ce_color = "text-green-500" if sub.confidence > 0.7 else "text-yellow-500" if sub.confidence > 0.4 else "text-red-500"
                freq_map = {"monthly":"kuu","weekly":"nädal","bi-weekly":"2 nädalat","quarterly":"kvartal","yearly":"aasta"}
                freq_label = freq_map.get(sub.frequency, sub.frequency)
                avg_gap, trend = _gap_trend(sub.dates)
                gap_text = f"{int(avg_gap)} päeva" if avg_gap else "?"
                trend_icon = "" if not trend else ("↓" if trend == "tugevam" else "↑")

                # Amount variation
                unique_amounts = sorted(set(sub.amounts))
                amount_text = f"{_fmt_eur(unique_amounts[0])}"
                if len(unique_amounts) > 1:
                    amount_text = f"{_fmt_eur(min(unique_amounts))}–{_fmt_eur(max(unique_amounts))}"

                lines.append(f'''
                    <tr class="border-b border-gray-100 hover:bg-gray-50">
                        <td class="py-3 pr-4">
                            <div class="font-medium text-gray-900">{_esc(sub.merchant_name)}</div>
                            <div class="text-xs text-gray-400">{sub.occurrences} tehingut · alates {sub.first_seen.day}.{sub.first_seen.month}</div>
                        </td>
                        <td class="py-3 pr-4 text-gray-700 whitespace-nowrap">{amount_text} €</td>
                        <td class="py-3 pr-4 text-gray-600">{freq_label}</td>
                        <td class="py-3 pr-4 text-gray-600 whitespace-nowrap">{gap_text} {trend_icon}</td>
                        <td class="py-3 pr-4"><span class="{ce_color} font-medium">{int(sub.confidence*100)}%</span></td>
                        <td class="py-3 pr-4 text-right font-medium text-gray-800">{_fmt_eur(sub.monthly_equivalent)}</td>
                        <td class="py-3 pl-4 text-right font-medium text-gray-800">{_fmt_eur(sub.estimated_yearly_cost)}</td>
                    </tr>''')

            # Table totals row
            lines.append(f'''
                    <tr class="font-semibold text-gray-900 border-t-2 border-gray-300">
                        <td class="py-3 pr-4" colspan="5">KOKKU</td>
                        <td class="py-3 pr-4 text-right">{_fmt_eur(total_monthly)} €</td>
                        <td class="py-3 pl-4 text-right">{_fmt_eur(total_yearly)} €</td>
                    </tr>
                </tbody>
            </table>
            </div>''')

            # ── Per-subscription detail cards with transaction history ──
            lines.append('<h3 class="mt-10 mb-4 text-lg font-semibold text-gray-800">Tehingute ajalugu</h3>')
            lines.append('<div class="space-y-4">')

            for sub in active:
                ce = "bg-green-400" if sub.confidence > 0.7 else "bg-yellow-400" if sub.confidence > 0.4 else "bg-red-400"
                bars = _sparkline_bars(sub.amounts)

                lines.append(f'''
                <div class="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
                    <div class="px-5 py-4 border-b border-gray-100 flex justify-between items-center">
                        <div class="flex items-center gap-2">
                            <span class="w-3 h-3 rounded-full {ce}"></span>
                            <span class="font-semibold text-gray-900">{_esc(sub.merchant_name)}</span>
                        </div>
                        <div class="text-sm text-gray-500">{sub.occurrences} tehingut</div>
                    </div>
                    <div class="overflow-x-auto">
                    <table class="w-full text-xs">
                        <thead class="bg-gray-50 text-gray-500">
                            <tr>
                                <th class="py-2 px-4 text-left font-medium">#</th>
                                <th class="py-2 px-4 text-left font-medium">Kuupäev</th>
                                <th class="py-2 px-4 text-left font-medium">Kuu</th>
                                <th class="py-2 px-4 text-right font-medium">Summa</th>
                                <th class="py-2 px-4 text-right font-medium">Vahe</th>
                                <th class="py-2 px-4 text-left font-medium pl-4">Trend</th>
                            </tr>
                        </thead>
                        <tbody>''')

                for i, (dt, amt) in enumerate(zip(sub.dates, sub.amounts)):
                    gap_str = ""
                    if i > 0:
                        gap = (dt - sub.dates[i - 1]).days
                        gap_str = f"{gap} p"
                    # Mini bar for trend visualization
                    bar_h = bars[i] if i < len(bars) else 3
                    bar_colors = ["bg-blue-200","bg-blue-300","bg-blue-400","bg-blue-500","bg-blue-600"]
                    bar_color = bar_colors[min(bar_h - 1, 4)]

                    lines.append(f'''
                            <tr class="border-t border-gray-50 hover:bg-blue-50/50">
                                <td class="py-2 px-4 text-gray-400">{i+1}</td>
                                <td class="py-2 px-4 text-gray-700">{dt.day}.{dt.month}.{dt.year}</td>
                                <td class="py-2 px-4 text-gray-500">{_month_name(dt)}</td>
                                <td class="py-2 px-4 text-right font-medium text-gray-800">{_fmt_eur(amt)} €</td>
                                <td class="py-2 px-4 text-right text-gray-500">{gap_str}</td>
                                <td class="py-2 px-4 pl-4"><span class="inline-block w-2 h-{bar_h} {bar_color} rounded-sm" style="height:{bar_h*4+4}px; width:8px;"></span></td>
                            </tr>''')

                # Sub-total row
                lines.append(f'''
                        </tbody>
                        <tfoot class="bg-gray-50 font-medium text-gray-700">
                            <tr class="border-t-2 border-gray-200">
                                <td class="py-2 px-4" colspan="3">Kulu perioodil</td>
                                <td class="py-2 px-4 text-right">{_fmt_eur(sub.total_spent)} €</td>
                                <td class="py-2 px-4" colspan="2">~{_fmt_eur(sub.monthly_equivalent)} €/kuu</td>
                            </tr>
                        </tfoot>
                    </table>
                    </div>
                </div>''')

            lines.append('</div>')

        # ── Inactive ──
        if inactive:
            lines.append('<h3 class="mt-8 mb-4 text-lg font-semibold text-gray-500">Viimati mitte-täidetud</h3>')
            for sub in inactive:
                lines.append(f'<div class="bg-gray-50 rounded-lg p-3 text-sm text-gray-600">{_esc(sub.merchant_name)} — {_fmt_eur(sub.amount)} EUR · viimati {sub.last_seen.day}.{sub.last_seen.month}.{sub.last_seen.year}</div>')

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

    # Security: enforce upload size limit
    if len(content) > MAX_CSV_BYTES:
        return render_results(0, [], error="Fail on liiga suur. Max 2 MB.")

    transactions = parse_csv(content)
    if not transactions:
        return render_results(0, [], error="Ei suutnud CSV parsimisel ühtegi tehingut leida. Kontrolli formaati.")

    detector = SubscriptionDetector()
    subscriptions = detector.detect(transactions)

    return render_results(len(transactions), subscriptions, file_name=file.filename)


@app.get("/health")
async def health():
    return {"status": "ok"}
