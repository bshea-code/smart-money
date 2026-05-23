#!/usr/bin/env python3
"""
Smart Money Overlap
====================
Finds stocks held at meaningful weight across respected active managers.
Holdings come from SEC EDGAR (free, no key).
Performance/category screening uses yfinance (free, no key).

Run:  python overlap.py
"""

import csv
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timedelta

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Configuration ─────────────────────────────────────────────────────────────

EDGAR_UA = "SmartMoneyOverlap brianrshea@gmail.com"

# Pinned funds always included regardless of auto-discovery
PINNED_FUNDS = {
    "FDGRX (Wymer)": {
        "type": "nport", "cik": "707823",
        "series_name": "Fidelity Growth Company Fund",
        "category": "Large Cap Growth", "fund_ticker": "FDGRX",
    },
    "FBGRX (Kalra)": {
        "type": "nport", "cik": "754510",
        "series_name": "Fidelity Blue Chip Growth Fund",
        "category": "Large Cap Growth", "fund_ticker": "FBGRX",
    },
    "FOCPX (Lee)": {
        "type": "nport", "cik": "754510",
        "series_name": "Fidelity OTC Portfolio",
        "category": "Large Cap Growth", "fund_ticker": "FOCPX",
    },
    "Atreides (Baker)": {
        "type": "13f", "cik": "1777813",
        "category": "Large Cap Growth",
    },
    "PRWCX / Capital Appreciation": {
        "type": "nport", "cik": "793347",
        "series_name": "T. Rowe Price Capital Appreciation Fund",
        "category": "Large Cap Blend", "fund_ticker": "PRWCX",
    },
    # ── Hedge funds ───────────────────────────────────────────────────────────
    "Durable Capital (Ellenbogen)": {
        "type": "13f", "cik": "1798849",
        "category": "Large Cap Growth",
    },
    "Tiger Global (Coleman)": {
        "type": "13f", "cik": "1167483",
        "category": "Large Cap Growth",
    },
    "Lone Pine (Mandel)": {
        "type": "13f", "cik": "1061165",
        "category": "Large Cap Growth",
    },
    "TCI Fund (Hohn)": {
        "type": "13f", "cik": "1647251",
        "category": "Large Cap Growth",
    },
    "AltaRock Partners": {
        "type": "13f", "cik": "1631014",
        "category": "Large Cap Growth",
    },
    "Akre Capital (Akre)": {
        "type": "13f", "cik": "1112520",
        "category": "Large Cap Blend",
    },
    "Pershing Square (Ackman)": {
        "type": "13f", "cik": "1336528",
        "category": "Large Cap Blend",
    },
    "Fundsmith (T. Smith)": {
        "type": "13f", "cik": "1569205",
        "category": "Global / International",
    },
    # ── Additional top hedge funds (EDGAR-verified CIKs) ─────────────────────
    "Coatue (Laffont)": {
        "type": "13f", "cik": "1135730",
        "category": "Large Cap Growth",
    },
    "Viking Global (Halvorsen)": {
        "type": "13f", "cik": "1103804",
        "category": "Large Cap Growth",
    },
    "D1 Capital (Sundheim)": {
        "type": "13f", "cik": "1747057",
        "category": "Large Cap Growth",
    },
    "Whale Rock (Grayson)": {
        "type": "13f", "cik": "1387322",
        "category": "Large Cap Growth",
    },
    "Dragoneer (McCarthy)": {
        "type": "13f", "cik": "1602189",
        "category": "Large Cap Growth",
    },
    "Maverick Capital (Ainslie)": {
        "type": "13f", "cik": "934639",
        "category": "Large Cap Growth",
    },
    "Third Point (Loeb)": {
        "type": "13f", "cik": "1040273",
        "category": "Large Cap Blend",
    },
    "Greenoaks Capital": {
        "type": "13f", "cik": "1840735",
        "category": "Large Cap Growth",
    },
    "Senator Investment": {
        "type": "13f", "cik": "1443689",
        "category": "Large Cap Blend",
    },
    "Citadel (Griffin)": {
        "type": "13f", "cik": "1423053",
        "category": "Large Cap Blend",
    },
    "Point72 (Cohen)": {
        "type": "13f", "cik": "1603466",
        "category": "Large Cap Blend",
    },
    "Baillie Gifford": {
        "type": "13f", "cik": "1088875",
        "category": "Global / International",
    },
}

# Auto-discovery settings
AUTO_DISCOVER      = True   # Set False to use only PINNED_FUNDS
TOP_N_PER_CATEGORY = 3      # Top funds to add per category (beyond pinned)
MIN_FUND_AUM       = 1e9    # $1B minimum AUM

# Display order for category buckets
CATEGORIES = [
    "Large Cap Growth",
    "Large Cap Blend",
    "Small / Mid Cap",
    "Global / International",
]

# Seed universe: ticker → category bucket (yfinance no longer exposes category)
SEED_FUND_META: dict[str, str] = {
    # Large Cap Growth
    "FDGRX": "Large Cap Growth",
    "FBGRX": "Large Cap Growth",
    "FOCPX": "Large Cap Growth",
    "FMAGX": "Large Cap Growth",   # Fidelity Magellan
    "TRBCX": "Large Cap Growth",   # T. Rowe Price Blue Chip Growth
    "PRGFX": "Large Cap Growth",   # T. Rowe Price Growth Stock
    "AGTHX": "Large Cap Growth",   # American Funds Growth Fund of America
    "AMCPX": "Large Cap Growth",   # American Funds AMCAP
    "POAGX": "Large Cap Growth",   # Primecap Odyssey Aggressive Growth
    "PRIMX": "Large Cap Growth",   # Primecap Odyssey Growth
    "VPMCX": "Large Cap Growth",   # Vanguard Primecap (active)
    "VWUAX": "Large Cap Growth",   # Vanguard U.S. Growth
    "HACAX": "Large Cap Growth",   # Harbor Capital Appreciation
    # Large Cap Blend
    "PRWCX": "Large Cap Blend",    # T. Rowe Price Capital Appreciation (pinned)
    "ANCFX": "Large Cap Blend",    # American Funds Fundamental Investors
    "AIVSX": "Large Cap Blend",    # American Funds Investment Co. of America
    "VPMAX": "Large Cap Blend",    # Vanguard Primecap Core
    "DODGX": "Large Cap Blend",    # Dodge & Cox Stock
    "OAKMX": "Large Cap Blend",    # Oakmark Fund
    "SEQUX": "Large Cap Blend",    # Sequoia Fund
    # Small / Mid Cap
    "PRNHX": "Small / Mid Cap",    # T. Rowe Price New Horizons
    "TRMCX": "Small / Mid Cap",    # T. Rowe Price Mid-Cap Growth
    "BGRFX": "Small / Mid Cap",    # Baron Growth
    "BALPX": "Small / Mid Cap",    # Baron Asset
    "WAAEX": "Small / Mid Cap",    # Wasatch Small Cap Growth
    "FSCRX": "Small / Mid Cap",    # Fidelity Small Cap Growth
    # Global / International
    "ARTGX": "Global / International",  # Artisan Global Opportunities
    "ARTZX": "Global / International",  # Artisan International
    "DODFX": "Global / International",  # Dodge & Cox International Stock
    "DODWX": "Global / International",  # Dodge & Cox Worldwide
    "OAKIX": "Global / International",  # Oakmark International
}

# Position filters
MIN_WEIGHT_PCT = 0.25   # % of portfolio to count as meaningful
MIN_FUND_COUNT = 2      # minimum funds that must hold a stock

OUTPUT_CSV   = "overlap.csv"
OUTPUT_HTML  = "overlap.html"
CACHE_FILE   = "fund_cache.json"
CACHE_TTL    = 7        # days before refreshing yfinance / EDGAR data

OPENFIGI_URL   = "https://api.openfigi.com/v3/mapping"
OPENFIGI_BATCH = 10
OPENFIGI_DELAY = 3.0    # 25 req/min free tier; 3s gives headroom

REQUEST_DELAY = 0.12    # SEC rate limit

EXCLUDE_CUSIPS         = {"31635A303"}
EXCLUDE_NAME_FRAGMENTS = ["POWERSHARES QQQ", "INVESCO QQQ", "SPDR S&P",
                           "ISHARES", "VANGUARD ETF"]

# ── Cache helpers ─────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)




# ── HTTP / EDGAR helpers ───────────────────────────────────────────────────────

_sub_cache: dict = {}


def fetch(url: str) -> str:
    time.sleep(REQUEST_DELAY)
    req = urllib.request.Request(url, headers={"User-Agent": EDGAR_UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def get_submissions(cik: str) -> dict:
    if cik not in _sub_cache:
        padded = str(cik).zfill(10)
        _sub_cache[cik] = json.loads(
            fetch(f"https://data.sec.gov/submissions/CIK{padded}.json")
        )
    return _sub_cache[cik]


# ── yfinance fund screening ────────────────────────────────────────────────────

def screen_seed_funds(cache: dict) -> list[dict]:
    """
    Screen SEED_FUND_META via yfinance: AUM filter, compute annualized returns
    from price history, rank by 5Y return within each category bucket.
    yfinance no longer exposes 'category' or pre-computed multi-year returns for
    mutual funds, so we use our hardcoded SEED_FUND_META for categories and
    derive returns from NAV history ourselves.
    """
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        print("  [warn] yfinance / pandas not installed — skipping auto-discovery",
              file=sys.stderr)
        return []

    seed_tickers = list(SEED_FUND_META.keys())
    print(f"  Screening {len(seed_tickers)} seed funds via yfinance ...")

    # --- Step 1: info (AUM, name) for any not freshly cached ---
    stale = [t for t in seed_tickers if not _cache_fresh(cache.get(t, {}))]
    if stale:
        for ticker in stale:
            try:
                raw = yf.Ticker(ticker).info
                entry = cache.get(ticker, {})
                entry.update({
                    "ticker":      ticker,
                    "longName":    raw.get("longName") or raw.get("shortName", ticker),
                    "fundFamily":  raw.get("fundFamily", ""),
                    "totalAssets": raw.get("totalAssets") or raw.get("netAssets") or 0,
                    "msRating":    raw.get("morningStarOverallRating"),
                    "category":    SEED_FUND_META[ticker],
                    "_ts":         datetime.now().isoformat(),
                })
                cache[ticker] = entry
            except Exception as exc:
                print(f"    [{ticker}] yfinance info error: {exc}", file=sys.stderr)

    # --- Step 2: batch-download 10Y price history, compute annualized returns ---
    returns_stale = [t for t in seed_tickers if "return_5y" not in cache.get(t, {})]
    if returns_stale:
        print(f"  Downloading price history for {len(returns_stale)} funds ...")
        try:
            hist_all = yf.download(
                returns_stale, period="10y", progress=False, auto_adjust=True
            )["Close"]
            # yf.download returns a single Series (not DataFrame) for one ticker
            if isinstance(hist_all, pd.Series):
                hist_all = hist_all.to_frame(returns_stale[0])
            for ticker in returns_stale:
                if ticker not in hist_all.columns:
                    continue
                s = hist_all[ticker].dropna()
                if s.empty:
                    continue
                current, idx = float(s.iloc[-1]), s.index
                def _ann(years):
                    cutoff = idx[-1] - pd.DateOffset(years=years)
                    sub = s[s.index >= cutoff]
                    if len(sub) < 30:
                        return None
                    return float((current / float(sub.iloc[0])) ** (1 / years) - 1)
                entry = cache.get(ticker, {})
                entry["return_3y"]  = _ann(3)
                entry["return_5y"]  = _ann(5)
                entry["return_10y"] = _ann(10)
                cache[ticker] = entry
        except Exception as exc:
            print(f"  [warn] price history download failed: {exc}", file=sys.stderr)

    # --- Step 3: filter and rank ---
    results = []
    for ticker in seed_tickers:
        info = cache.get(ticker, {})
        if not info.get("longName"):
            continue
        if (info.get("totalAssets") or 0) < MIN_FUND_AUM:
            continue
        results.append({**info, "bucket": SEED_FUND_META[ticker]})

    results.sort(key=lambda x: (x["bucket"], -(x.get("return_5y") or -99)))
    return results


# ── EDGAR CIK auto-discovery ──────────────────────────────────────────────────

def _name_score(edgar_series: str, long_name: str) -> float:
    """Rough word-overlap score between an EDGAR series name and a yfinance long name."""
    stop = {"fund", "the", "inc", "llc", "class", "institutional", "investor",
            "retail", "a", "b", "c", "i", "n", "r", "t", "lp"}
    def words(s):
        return {w for w in re.split(r'\W+', s.lower()) if w and w not in stop}
    ew, nw = words(edgar_series), words(long_name)
    if not nw:
        return 0.0
    return len(ew & nw) / len(nw)


def find_edgar_fund(ticker: str, long_name: str, cache: dict) -> tuple[str, str] | tuple[None, None]:
    """
    Search EDGAR for the trust CIK and series_name corresponding to a fund ticker.
    Returns (cik, series_name) or (None, None).
    Checks cache first; writes successful results back.
    """
    entry = cache.get(ticker, {})
    if entry.get("cik") and entry.get("series_name"):
        return entry["cik"], entry["series_name"]

    # Build a short search term from the fund name
    name_clean = re.sub(r'\b(fund|class|institutional|investor|retail|inc|llc)\b', '',
                        long_name, flags=re.I).strip()
    # Keep first ~4 meaningful words
    words = name_clean.split()[:4]
    search_term = " ".join(words)

    url = (
        "https://www.sec.gov/cgi-bin/browse-edgar"
        f"?company={urllib.parse.quote(search_term)}"
        "&CIK=&type=NPORT-P&dateb=&owner=include&count=40&search_text=&action=getcompany"
    )
    try:
        html = fetch(url)
    except Exception:
        return None, None

    cik_matches = re.findall(
        r'action=getcompany&amp;CIK=(\d+).*?</a>\s*\n?\s*<td[^>]*>\s*([^<]+)</td>',
        html
    )
    if not cik_matches:
        cik_matches = [(m, "") for m in re.findall(r'CIK=(\d+)', html)]

    best_cik, best_series, best_score = None, None, 0.3  # minimum threshold

    for cik, _edgar_name in cik_matches[:8]:
        try:
            sub = get_submissions(cik)
        except Exception:
            continue
        recent = sub["filings"]["recent"]
        nport_accs = [
            a for f, a in zip(recent["form"], recent["accessionNumber"])
            if f == "NPORT-P"
        ]
        if not nport_accs:
            continue

        # Sample first few filings to see all series (trusts file one series per accession)
        for acc in nport_accs[:6]:
            acc_nd = acc.replace("-", "")
            try:
                xml_text = fetch(
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/primary_doc.xml"
                )
            except Exception:
                continue
            for sn in re.findall(r"<seriesName>([^<]+)</seriesName>", xml_text):
                score = _name_score(sn, long_name)
                if score > best_score:
                    best_score, best_cik, best_series = score, cik, sn.strip()

    if best_cik and best_series:
        cache.setdefault(ticker, {}).update({"cik": best_cik, "series_name": best_series})
        return best_cik, best_series

    return None, None


# ── Build the active FUNDS dict ────────────────────────────────────────────────

def build_fund_list(cache: dict) -> dict:
    """
    Start with PINNED_FUNDS, then add auto-discovered top performers per category.
    Returns a FUNDS-style dict with type/cik/series_name/category/return_5y.
    """
    funds: dict = {}

    for label, cfg in PINNED_FUNDS.items():
        funds[label] = dict(cfg)

    if not AUTO_DISCOVER:
        return funds

    screened = screen_seed_funds(cache)

    # Count how many per bucket we've already pinned
    pinned_per_bucket: dict = defaultdict(int)
    for cfg in PINNED_FUNDS.values():
        if cat := cfg.get("category"):
            pinned_per_bucket[cat] += 1

    added_per_bucket: dict = defaultdict(int)
    already_series = {cfg.get("series_name") for cfg in PINNED_FUNDS.values()}

    for info in screened:
        bucket = info["bucket"]
        ticker = info["ticker"]

        if added_per_bucket[bucket] >= TOP_N_PER_CATEGORY:
            continue

        # Skip if already pinned (match by ticker at start of label)
        if any(lbl.startswith(ticker) for lbl in PINNED_FUNDS):
            continue

        long_name = info.get("longName", ticker)
        print(f"    [{ticker}] {long_name[:50]}  5Y={info.get('return_5y', '?')}  [{bucket}]")

        cik, series_name = find_edgar_fund(ticker, long_name, cache)
        if not cik or series_name in already_series:
            print(f"      → EDGAR not found, skipping")
            continue

        ret5 = info.get("return_5y")
        ret3 = info.get("return_3y")
        # Derive a short label: "FCNTX / Contrafund"
        long = info.get("longName", ticker)
        short = re.sub(r'\b(fund|investor|institutional|class|advisor|inc|llc)\b', '',
                       long, flags=re.I).strip().rstrip(",. ")
        label = f"{ticker} / {short[:28].strip()}"

        funds[label] = {
            "type":        "nport",
            "cik":         cik,
            "series_name": series_name,
            "category":    bucket,
            "return_5y":   ret5,
            "return_3y":   ret3,
            "long_name":   long_name,
        }
        already_series.add(series_name)
        added_per_bucket[bucket] += 1
        print(f"      → CIK {cik}  series='{series_name}'")

    return funds


# ── NPORT-P loader ────────────────────────────────────────────────────────────

def load_nport(label: str, cik: str, series_name: str) -> dict:
    print(f"  [{label}] scanning for '{series_name}' ...")

    sub = get_submissions(cik)
    recent = sub["filings"]["recent"]
    nport_pairs = [
        (dt, acc)
        for f, dt, acc in zip(
            recent["form"], recent["filingDate"], recent["accessionNumber"]
        )
        if f == "NPORT-P"
    ]
    batch_dates = sorted({dt for dt, _ in nport_pairs}, reverse=True)

    for batch_date in batch_dates[:6]:
        batch = [a for dt, a in nport_pairs if dt == batch_date]
        for acc in batch:
            acc_nd = acc.replace("-", "")
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/primary_doc.xml"
            )
            try:
                xml_text = fetch(url)
            except Exception:
                continue

            m = re.search(r"<seriesName>([^<]+)</seriesName>", xml_text)
            if not (m and m.group(1).strip() == series_name):
                continue

            period_m = re.search(r"<repPdDate>([^<]+)</repPdDate>", xml_text)
            period = period_m.group(1) if period_m else "?"
            holdings, net_assets = _parse_nport_xml(xml_text)
            size_str = (
                f"${net_assets/1e9:.1f}B" if net_assets >= 1e9
                else f"${net_assets/1e6:.0f}M"
            )
            print(f"    ✓ period={period}  size={size_str}  positions={len(holdings)}")
            return {
                "type": "nport", "holdings": holdings,
                "period": period, "net_assets": net_assets,
            }

    raise ValueError(f"Series '{series_name}' not found for CIK {cik}")


def _parse_nport_xml(xml_text: str) -> tuple:
    root = ET.fromstring(xml_text)
    ns = {"n": "http://www.sec.gov/edgar/nport"}

    net_assets_el = root.find(".//n:netAssets", ns)
    net_assets = float(net_assets_el.text) if net_assets_el is not None else 0.0

    raw: dict = defaultdict(lambda: {"name": "", "val": 0.0, "pct": 0.0, "shares": 0.0})
    for sec in root.findall(".//n:invstOrSec", ns):
        cusip_el = sec.find("n:cusip", ns)
        if cusip_el is None or not (cusip_el.text or "").strip():
            continue
        cusip = cusip_el.text.strip()

        val_el = sec.find("n:valUSD", ns)
        val = float(val_el.text) if (val_el is not None and val_el.text) else 0.0
        pct_el = sec.find("n:pctVal", ns)
        pct = float(pct_el.text) if (pct_el is not None and pct_el.text) else 0.0
        if val <= 0:
            continue

        # <balance> = number of shares (when <units> = NS)
        bal_el  = sec.find("n:balance", ns)
        unit_el = sec.find("n:units", ns)
        shares  = 0.0
        if bal_el is not None and bal_el.text and (unit_el is None or unit_el.text == "NS"):
            try:
                shares = float(bal_el.text)
            except ValueError:
                pass

        name = sec.findtext("n:name", namespaces=ns) or ""
        raw[cusip]["name"]   = raw[cusip]["name"] or name
        raw[cusip]["val"]   += val
        raw[cusip]["pct"]   += pct
        raw[cusip]["shares"] += shares

    holdings = {
        cusip: {"name": h["name"], "pct": h["pct"], "val": h["val"], "shares": h["shares"]}
        for cusip, h in raw.items()
    }
    return holdings, net_assets


# ── 13F loader ────────────────────────────────────────────────────────────────

def load_13f(label: str, cik: str) -> dict:
    print(f"  [{label}] fetching 13F-HR ...")

    sub = get_submissions(cik)
    recent = sub["filings"]["recent"]

    acc = filing_date = None
    for f, dt, a in zip(recent["form"], recent["filingDate"], recent["accessionNumber"]):
        if f == "13F-HR":
            acc, filing_date = a, dt
            break

    if not acc:
        raise ValueError(f"No 13F-HR found for CIK {cik}")

    acc_nd = acc.replace("-", "")
    idx_html = fetch(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/")
    xml_names = re.findall(
        rf"/Archives/edgar/data/{cik}/{acc_nd}/([^\"/]+\.[xX][mM][lL])", idx_html
    )
    info_url = next(
        (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/{n}"
            for n in xml_names
            if "primary_doc" not in n.lower()
        ),
        None,
    )
    if not info_url:
        raise ValueError(f"Info-table XML not found in 13F for CIK {cik}")

    holdings, total_val = _parse_13f_xml(fetch(info_url))
    print(f"    ✓ filed={filing_date}  positions={len(holdings)}")
    return {
        "type": "13f", "holdings": holdings,
        "period": filing_date, "net_assets": total_val,
    }


def _parse_13f_xml(xml_text: str) -> tuple:
    root = ET.fromstring(xml_text)
    ns = {"t": "http://www.sec.gov/edgar/document/thirteenf/informationtable"}

    raw: dict = defaultdict(lambda: {"name": "", "val": 0, "shares": 0})
    for info in root.findall("t:infoTable", ns):
        cusip = (info.findtext("t:cusip", namespaces=ns) or "").strip()
        if not cusip:
            continue
        type_el = info.find("t:shrsOrPrnAmt/t:sshPrnamtType", ns)
        if type_el is not None and type_el.text != "SH":
            continue
        name  = info.findtext("t:nameOfIssuer", namespaces=ns) or ""
        val   = int(info.findtext("t:value", namespaces=ns) or 0)
        shares_el = info.find("t:shrsOrPrnAmt/t:sshPrnamt", ns)
        shares = int(shares_el.text) if shares_el is not None else 0
        raw[cusip]["name"]   = raw[cusip]["name"] or name
        raw[cusip]["val"]   += val
        raw[cusip]["shares"] += shares

    total_val = sum(h["val"] for h in raw.values())
    holdings = {
        cusip: {"name": h["name"], "pct": h["val"] / total_val * 100, "val": h["val"]}
        for cusip, h in raw.items()
        if h["val"] > 0 and total_val > 0
    }
    return holdings, total_val


# ── Overlap analysis ──────────────────────────────────────────────────────────

def find_overlap(fund_data: dict, company_metrics: dict, tickers: dict) -> tuple:
    fund_names = list(fund_data.keys())
    per_cusip: dict = defaultdict(dict)

    for fund, info in fund_data.items():
        for cusip, h in info["holdings"].items():
            if h["pct"] >= MIN_WEIGHT_PCT:
                per_cusip[cusip][fund] = h["pct"]
                per_cusip[cusip].setdefault("_name", h["name"])
                # ownership % = shares held by this fund / total shares outstanding
                ticker = tickers.get(cusip)
                if ticker and h.get("shares", 0) > 0:
                    so = (company_metrics.get(ticker) or {}).get("shares_outstanding")
                    if so and so > 0:
                        own_key = f"_own_{fund}"
                        per_cusip[cusip][own_key] = h["shares"] / so * 100

    def _is_excluded(cusip: str, data: dict) -> bool:
        if cusip in EXCLUDE_CUSIPS:
            return True
        name_upper = (data.get("_name") or "").upper()
        return any(frag in name_upper for frag in EXCLUDE_NAME_FRAGMENTS)

    overlap = [
        (cusip, data)
        for cusip, data in per_cusip.items()
        if sum(1 for k in data if not k.startswith("_")) >= MIN_FUND_COUNT
        and not _is_excluded(cusip, data)
    ]
    overlap.sort(
        key=lambda x: (
            -sum(1 for k in x[1] if not k.startswith("_")),
            -sum(v for k, v in x[1].items() if not k.startswith("_")),
        )
    )
    return overlap, fund_names


# ── Ticker resolution ─────────────────────────────────────────────────────────

def resolve_tickers(cusips: list, cache: dict) -> dict:
    """
    Resolve CUSIPs to tickers via OpenFIGI.  Caches results permanently in
    cache["_tickers"] so repeat runs only query unknown CUSIPs.
    """
    ticker_cache = cache.setdefault("_tickers", {})
    tickers = {c: ticker_cache[c] for c in cusips if c in ticker_cache}

    unknown = [c for c in cusips if c not in ticker_cache]
    if unknown:
        print(f"  Resolving {len(unknown)} new tickers via OpenFIGI "
              f"({len(tickers)} already cached) ...")
        for i in range(0, len(unknown), OPENFIGI_BATCH):
            batch = unknown[i : i + OPENFIGI_BATCH]
            payload = [{"idType": "ID_CUSIP", "idValue": c, "marketSecDes": "Equity"}
                       for c in batch]
            req = urllib.request.Request(
                OPENFIGI_URL,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                time.sleep(OPENFIGI_DELAY)
                with urllib.request.urlopen(req, timeout=30) as r:
                    results = json.loads(r.read().decode())
            except Exception as exc:
                print(f"  [OpenFIGI] batch {i // OPENFIGI_BATCH + 1} failed: {exc}",
                      file=sys.stderr)
                continue

            for cusip, result in zip(batch, results):
                if "error" in result or not result.get("data"):
                    continue
                data_list = result["data"]
                us = [d for d in data_list if d.get("exchCode") in ("US", "UW", "UN", "UP", "UA")]
                pick = us[0] if us else data_list[0]
                ticker = pick.get("ticker", "").strip()
                if ticker:
                    tickers[cusip] = ticker
                    ticker_cache[cusip] = ticker
    else:
        print(f"  All {len(tickers)} tickers resolved from cache.")

    # Normalize tickers that break yfinance (slash → hyphen for BRK/B, BRK/A etc.)
    _slash_fix = {c: t.replace("/", "-") for c, t in tickers.items() if "/" in t}
    for cusip, fixed in _slash_fix.items():
        tickers[cusip] = fixed
        ticker_cache[cusip] = fixed

    print(f"  Resolved {len(tickers)}/{len(cusips)} tickers.")
    return tickers


# ── Company metrics ──────────────────────────────────────────────────────────

def get_company_metrics(ticker_list: list, cache: dict) -> dict:
    """
    For each stock ticker return market cap, shares outstanding, and
    1M / 3M / 1Y price returns.  Uses yfinance batch download for speed.
    Results are cached per ticker with a 1-day TTL.
    """
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        return {}

    ONE_DAY = 1
    stale = [t for t in ticker_list
             if not _cache_fresh(cache.get(f"_co_{t}", {}), ttl_days=ONE_DAY)]

    metrics: dict = {}

    # ── info (market cap, shares outstanding) ────────────────────────────────
    if stale:
        print(f"  Fetching company info for {len(stale)} stocks ...")
        for t in stale:
            try:
                raw = yf.Ticker(t).fast_info
                entry = {
                    "market_cap":         getattr(raw, "market_cap", None),
                    "shares_outstanding": getattr(raw, "shares", None),
                    "_ts": datetime.now().isoformat(),
                }
                cache[f"_co_{t}"] = entry
            except Exception:
                pass

    for t in ticker_list:
        e = cache.get(f"_co_{t}", {})
        metrics[t] = {
            "market_cap":         e.get("market_cap"),
            "shares_outstanding": e.get("shares_outstanding"),
        }

    # ── price history (1M / 3M / 1Y / 3Y / 5Y returns) ─────────────────────
    hist_stale = [t for t in ticker_list
                  if "return_1m" not in cache.get(f"_co_{t}", {})
                  or "return_3y" not in cache.get(f"_co_{t}", {})
                  or "return_5y" not in cache.get(f"_co_{t}", {})]
    if hist_stale:
        print(f"  Downloading 6Y price history for {len(hist_stale)} stocks ...")
        try:
            hist = yf.download(hist_stale, period="6y", progress=False,
                               auto_adjust=True)["Close"]
            if isinstance(hist, pd.Series):
                hist = hist.to_frame(hist_stale[0])
            for t in hist_stale:
                if t not in hist.columns:
                    continue
                s = hist[t].dropna()
                if s.empty:
                    continue
                cur = float(s.iloc[-1])
                def _ret(days, _s=s, _cur=cur):
                    cutoff = _s.index[-1] - pd.DateOffset(days=days)
                    past = _s[_s.index <= cutoff]
                    return float(_cur / float(past.iloc[-1]) - 1) if not past.empty else None
                entry = cache.get(f"_co_{t}", {})
                entry.update({
                    "return_1m":  _ret(30),
                    "return_3m":  _ret(90),
                    "return_1y":  _ret(365),
                    "return_3y":  _ret(365 * 3),
                    "return_5y":  _ret(365 * 5),
                    "_ts": datetime.now().isoformat(),
                })
                cache[f"_co_{t}"] = entry
        except Exception as exc:
            print(f"  [warn] stock history download failed: {exc}", file=sys.stderr)

    for t in ticker_list:
        e = cache.get(f"_co_{t}", {})
        metrics[t].update({
            "return_1m": e.get("return_1m"),
            "return_3m": e.get("return_3m"),
            "return_1y": e.get("return_1y"),
            "return_3y": e.get("return_3y"),
            "return_5y": e.get("return_5y"),
        })

    return metrics


def _cache_fresh(entry: dict, ttl_days: int = CACHE_TTL) -> bool:
    ts = entry.get("_ts")
    if not ts:
        return False
    return (datetime.now() - datetime.fromisoformat(ts)).days < ttl_days


# ── Company details (description + valuation) ─────────────────────────────────

def get_company_details(ticker_list: list, cache: dict) -> dict:
    """Fetch longBusinessSummary, sector, industry, and valuation ratios."""
    try:
        import yfinance as yf
    except ImportError:
        return {}

    stale = [t for t in ticker_list
             if not _cache_fresh(cache.get(f"_det_{t}", {}), ttl_days=1)]
    if stale:
        print(f"  Fetching company details for {len(stale)} stocks ...")
        for t in stale:
            try:
                info = yf.Ticker(t).info
                cache[f"_det_{t}"] = {
                    "description": info.get("longBusinessSummary", ""),
                    "sector":      info.get("sector", ""),
                    "industry":    info.get("industry", ""),
                    "trailing_pe": _safe_float(info.get("trailingPE")),
                    "forward_pe":  _safe_float(info.get("forwardPE")),
                    "ps_ratio":    _safe_float(info.get("priceToSalesTrailing12Months")),
                    "pb_ratio":    _safe_float(info.get("priceToBook")),
                    "ev_ebitda":   _safe_float(info.get("enterpriseToEbitda")),
                    "52w_high":    _safe_float(info.get("fiftyTwoWeekHigh")),
                    "52w_low":     _safe_float(info.get("fiftyTwoWeekLow")),
                    "website":     info.get("website", ""),
                    "_ts":         datetime.now().isoformat(),
                }
            except Exception as exc:
                print(f"    [{t}] detail error: {exc}", file=sys.stderr)

    results = {}
    for t in ticker_list:
        e = cache.get(f"_det_{t}", {})
        results[t] = {k: v for k, v in e.items() if not k.startswith("_")}
    return results


def _safe_float(v):
    """Return float or None; suppress NaN."""
    try:
        f = float(v)
        return None if f != f else f  # f != f is True for NaN
    except (TypeError, ValueError):
        return None


# ── Annual financials (for valuation change computation) ─────────────────────

def get_annual_financials(ticker_list: list, cache: dict) -> dict:
    """
    Fetch the two most recent annual income statements per ticker.
    Stores yr0 (most recent fiscal year) and yr1 (prior year) revenue and net income.
    Used to compute YoY change in P/E and P/S without requiring cached snapshots.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {}

    stale = [t for t in ticker_list
             if not _cache_fresh(cache.get(f"_fin_{t}", {}), ttl_days=7)]
    if stale:
        print(f"  Fetching annual financials for {len(stale)} stocks ...")
        for t in stale:
            try:
                stmt = yf.Ticker(t).income_stmt
                if stmt is None or stmt.empty:
                    continue
                cols = [c for c in stmt.columns]  # newest first

                def _val(col, *keys):
                    for k in keys:
                        try:
                            v = stmt.loc[k, col]
                            if v is not None and v == v:  # not NaN
                                return float(v)
                        except (KeyError, TypeError):
                            pass
                    return None

                entry = {"_ts": datetime.now().isoformat()}
                for i, col in enumerate(cols[:2]):
                    yr = f"yr{i}"
                    entry[f"{yr}_revenue"]    = _val(col, "Total Revenue", "Revenue",
                                                      "Operating Revenue")
                    entry[f"{yr}_net_income"] = _val(col, "Net Income",
                                                      "Net Income From Continuing Operations",
                                                      "Net Income Common Stockholders")
                    entry[f"{yr}_date"] = str(col)[:10]
                cache[f"_fin_{t}"] = entry
            except Exception as exc:
                print(f"    [{t}] financials error: {exc}", file=sys.stderr)

    return {t: cache.get(f"_fin_{t}", {}) for t in ticker_list}


# ── ETF exposure ──────────────────────────────────────────────────────────────

_DERIVATIVE_ETF_WORDS = {
    "daily", "2x", "3x", "bull", "bear", "inverse", "short",
    "weeklypay", "weekly pay", "monthlypay", "monthly pay",
    "covered call", "premium income", "income advantage",
    "leveraged", "ultra", "hedge",
}


def _fetch_etf_exposure(ticker: str) -> list:
    """Scrape etfdb.com for the top ETFs (by weight) that hold this stock."""
    import html as html_mod
    url = f"https://etfdb.com/stock/{ticker.upper()}/"
    req = urllib.request.Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            page = r.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    # Parse <td data-th="Column">value</td> rows
    etfs = []
    for row in re.findall(r'<tr[^>]*>.*?</tr>', page, re.DOTALL):
        cells = re.findall(r'data-th="([^"]+)"[^>]*>(.*?)</td>', row, re.DOTALL)
        if not cells:
            continue
        row_dict = {k: html_mod.unescape(re.sub(r'<[^>]+>', '', v).strip())
                    for k, v in cells}

        etf_ticker = row_dict.get("Ticker", "").strip()
        etf_name   = row_dict.get("ETF", "").strip()
        weight_str = row_dict.get("Weighting", "").replace("%", "").strip()
        weight     = _safe_float(weight_str) or 0.0

        if not etf_ticker or weight < 0.5:
            continue

        # Filter single-name derivatives and leveraged products
        name_lower = etf_name.lower()
        if any(w in name_lower for w in _DERIVATIVE_ETF_WORDS):
            continue
        # Also skip if the stock ticker appears in the ETF name
        if ticker.upper() in etf_name.upper().split():
            continue

        etfs.append({
            "ticker": etf_ticker,
            "name":   etf_name,
            "weight": weight,
            "category": row_dict.get("ETF Database Category", ""),
            "expense_ratio": row_dict.get("Expense Ratio", ""),
        })

    etfs.sort(key=lambda x: -x["weight"])
    return etfs[:25]


def get_etf_exposure_batch(ticker_list: list, cache: dict) -> dict:
    """Fetch ETF exposure for each ticker (7-day cache).
    Skips re-fetching in CI environments where etfdb.com blocks cloud IPs."""
    import os
    in_ci = os.environ.get("CI") == "true"
    results = {}
    if in_ci:
        print("  ETF fetch skipped in CI (etfdb.com blocks cloud IPs); using cached data.")
        stale = []
    else:
        stale = [t for t in ticker_list
                 if not _cache_fresh(cache.get(f"_etf_{t}", {}), ttl_days=7)]
    if stale:
        print(f"  Fetching ETF exposure for {len(stale)} stocks ...")
        for i, t in enumerate(stale):
            etfs = _fetch_etf_exposure(t)
            cache[f"_etf_{t}"] = {"etfs": etfs, "_ts": datetime.now().isoformat()}
            if (i + 1) % 10 == 0:
                print(f"    ... {i+1}/{len(stale)}")
            time.sleep(0.4)
    for t in ticker_list:
        results[t] = cache.get(f"_etf_{t}", {}).get("etfs", [])
    return results


# ── S&P 500 membership ────────────────────────────────────────────────────────

def get_sp500_members(cache: dict) -> set:
    """
    Fetch current S&P 500 constituents from Wikipedia.
    Cached for 7 days.
    """
    cached = cache.get("_sp500", {})
    if _cache_fresh(cached, ttl_days=7) and cached.get("tickers"):
        return set(cached["tickers"])
    try:
        req = urllib.request.Request(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": EDGAR_UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8")
        tickers = re.findall(r'<td><a[^>]+>([A-Z]{1,5})</a>\n</td>', html)
        if len(tickers) > 400:
            cache["_sp500"] = {"tickers": tickers, "_ts": datetime.now().isoformat()}
            print(f"  S&P 500: {len(tickers)} members fetched.")
            return set(tickers)
    except Exception as exc:
        print(f"  [warn] S&P 500 fetch failed: {exc}", file=sys.stderr)
    return set(cached.get("tickers", []))


# ── Fund performance (3Y / 5Y) for NPORT funds with public tickers ───────────

def fetch_fund_returns(all_cfg: dict, cache: dict) -> None:
    """Populate return_3y / return_5y on fund configs that have a fund_ticker.
    First pulls from the yfinance cache (populated by screen_seed_funds); downloads
    any that are still missing."""
    import pandas as pd

    # Pass 1: read from cache (screen_seed_funds already stored these)
    for fn, cfg in all_cfg.items():
        ticker = cfg.get("fund_ticker")
        if not ticker:
            continue
        entry = cache.get(ticker, {})
        if "return_3y" not in cfg and entry.get("return_3y") is not None:
            cfg["return_3y"] = entry["return_3y"]
        if "return_5y" not in cfg and entry.get("return_5y") is not None:
            cfg["return_5y"] = entry["return_5y"]

    # Pass 2: download any still missing
    need = {fn: cfg["fund_ticker"] for fn, cfg in all_cfg.items()
            if cfg.get("fund_ticker")
            and ("return_3y" not in cfg or "return_5y" not in cfg)}
    if not need:
        return
    tickers = list(need.values())
    print(f"  Downloading fund history for: {', '.join(tickers)}")
    try:
        raw = yf.download(tickers, period="6y", progress=False, auto_adjust=True)
        close = raw["Close"] if "Close" in raw.columns or hasattr(raw["Close"], "columns") else raw
        # Handle single-ticker edge case
        if isinstance(close, pd.Series):
            close = close.to_frame(tickers[0])
        for fn, ticker in need.items():
            col = [c for c in close.columns if (c == ticker or (hasattr(c, "__iter__") and ticker in c))]
            if not col:
                continue
            s = close[col[0]].dropna()
            if s.empty:
                continue
            cur = float(s.iloc[-1])
            def _ret(days, _s=s, _cur=cur):
                cutoff = _s.index[-1] - pd.DateOffset(days=days)
                past = _s[_s.index <= cutoff]
                return float(_cur / float(past.iloc[-1]) - 1) if not past.empty else None
            r3 = _ret(365 * 3); r5 = _ret(365 * 5)
            if r3 is not None:
                all_cfg[fn]["return_3y"] = r3
                cache.setdefault(ticker, {})["return_3y"] = r3
            if r5 is not None:
                all_cfg[fn]["return_5y"] = r5
                cache.setdefault(ticker, {})["return_5y"] = r5
    except Exception as exc:
        print(f"  [warn] fund return fetch failed: {exc}", file=sys.stderr)


# ── Historical filing helpers ─────────────────────────────────────────────────

def _fetch_13f_quarters(cik: str, n_q: int) -> list:
    """Return up to n_q most-recent 13F-HR filings as [{"period", "holdings"}]."""
    sub = get_submissions(cik)
    recent = sub["filings"]["recent"]
    acc_pairs = [
        (dt, a)
        for f, dt, a in zip(recent["form"], recent["filingDate"], recent["accessionNumber"])
        if f == "13F-HR"
    ]
    results = []
    for filing_date, acc in acc_pairs[:n_q]:
        acc_nd = acc.replace("-", "")
        try:
            idx_html = fetch(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/")
            xml_names = re.findall(
                rf"/Archives/edgar/data/{cik}/{acc_nd}/([^\"/]+\.[xX][mM][lL])", idx_html)
            info_url = next(
                (f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/{nm}"
                 for nm in xml_names if "primary_doc" not in nm.lower()),
                None)
            if not info_url:
                continue
            holdings, _ = _parse_13f_xml(fetch(info_url))
            results.append({
                "period": filing_date,
                "holdings": {c: {"pct": h["pct"], "val": h["val"]} for c, h in holdings.items()},
            })
        except Exception:
            continue
    return results


def _fetch_nport_quarters(cik: str, series_name: str, n_q: int) -> list:
    """Return up to n_q most-recent NPORT-P periods for the given series."""
    sub = get_submissions(cik)
    recent = sub["filings"]["recent"]
    nport_pairs = [
        (dt, acc)
        for f, dt, acc in zip(recent["form"], recent["filingDate"], recent["accessionNumber"])
        if f == "NPORT-P"
    ]
    batch_dates = sorted({dt for dt, _ in nport_pairs}, reverse=True)
    results = []
    for batch_date in batch_dates:
        if len(results) >= n_q:
            break
        for acc in [a for dt, a in nport_pairs if dt == batch_date]:
            acc_nd = acc.replace("-", "")
            try:
                xml_text = fetch(
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/primary_doc.xml")
            except Exception:
                continue
            m = re.search(r"<seriesName>([^<]+)</seriesName>", xml_text)
            if not (m and m.group(1).strip() == series_name):
                continue
            period_m = re.search(r"<repPdDate>([^<]+)</repPdDate>", xml_text)
            period = period_m.group(1) if period_m else batch_date
            holdings, _ = _parse_nport_xml(xml_text)
            results.append({
                "period": period,
                "holdings": {c: {"pct": h["pct"], "val": h["val"]} for c, h in holdings.items()},
            })
            break  # found the right series for this batch date
    return results


def fetch_multi_quarter_holdings(fn: str, cfg: dict, cache: dict, n_q: int = 6) -> list:
    """Fetch up to n_q quarters of historical holdings for a fund. Cached 7 days."""
    safe_key = re.sub(r"[^a-z0-9]", "_", fn.lower())
    cache_key = f"_mhist_{safe_key}"
    cached = cache.get(cache_key, {})
    if _cache_fresh(cached, ttl_days=7) and cached.get("quarters"):
        return cached["quarters"]
    cik = cfg.get("cik", "")
    quarters: list = []
    if cik:
        try:
            if cfg.get("type") == "13f":
                quarters = _fetch_13f_quarters(cik, n_q)
            elif cfg.get("series_name"):
                quarters = _fetch_nport_quarters(cik, cfg["series_name"], n_q)
        except Exception as exc:
            print(f"  [mhist] {fn}: {exc}", file=sys.stderr)
    cache[cache_key] = {"quarters": quarters, "_ts": datetime.now().isoformat()}
    if quarters:
        print(f"  [{fn[:30]}] {len(quarters)} quarters of history fetched")
    return quarters


def _pick_quarter(quarters: list, target: date):
    """Return the quarter entry with period closest to (but not after) target date."""
    best = None
    best_dist = None
    for q in quarters:
        try:
            q_date = datetime.strptime(q["period"][:10], "%Y-%m-%d").date()
        except Exception:
            continue
        if q_date > target:
            continue
        dist = (target - q_date).days
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best = q
    return best


def compute_aggregate_changes(overlap: list, fund_data: dict, all_cfg: dict,
                               cache: dict) -> dict:
    """
    Returns {cusip: {"ytd_delta": float|None, "y1_delta": float|None}}.
    Values are % change in aggregate portfolio weight (sum of % across all funds).
    +50 = funds collectively increased their weight in this stock by 50%.
    New positions (prior weight = 0) return 999 as a sentinel.
    """
    print("Computing aggregate ownership changes ...")
    today = datetime.now().date()
    ytd_target = date(today.year, 1, 1)
    y1_target  = today - timedelta(days=365)

    fund_quarters: dict = {}
    for fn, info in fund_data.items():
        cfg = all_cfg.get(fn, {})
        fund_quarters[fn] = fetch_multi_quarter_holdings(fn, cfg, cache)

    def _pct_chg(current, prior):
        if prior > 0:
            return (current - prior) / prior * 100
        return 999.0 if current > 0 else 0.0

    results = {}
    for cusip, data in overlap:
        current_agg = sum(v for k, v in data.items() if not k.startswith("_"))
        ytd_agg = 0.0; ytd_found = False
        y1_agg  = 0.0; y1_found  = False
        for fn, quarters in fund_quarters.items():
            q_ytd = _pick_quarter(quarters, ytd_target)
            if q_ytd is not None:
                ytd_agg += q_ytd["holdings"].get(cusip, {}).get("pct", 0.0)
                ytd_found = True
            q_y1 = _pick_quarter(quarters, y1_target)
            if q_y1 is not None:
                y1_agg += q_y1["holdings"].get(cusip, {}).get("pct", 0.0)
                y1_found = True
        results[cusip] = {
            "ytd_delta": _pct_chg(current_agg, ytd_agg) if ytd_found else None,
            "y1_delta":  _pct_chg(current_agg, y1_agg)  if y1_found  else None,
        }
    return results


# ── Smart valuation ───────────────────────────────────────────────────────────

def pick_smart_valuation(ticker: str, details: dict) -> tuple:
    """
    Choose the most informative valuation metric based on sector/profitability.
    Returns (metric_label, value_or_None).
    - Financials: P/B
    - Energy/Utilities: EV/EBITDA
    - Unprofitable/high-growth tech: P/S
    - Default: trailing P/E
    """
    sector   = (details.get("sector")   or "").lower()
    industry = (details.get("industry") or "").lower()
    pe  = details.get("trailing_pe")
    ps  = details.get("ps_ratio")
    pb  = details.get("pb_ratio")
    ev  = details.get("ev_ebitda")

    def ok(v):
        return v is not None and 0 < v < 1000

    if any(w in sector + " " + industry for w in ("financial", "bank", "insurance")):
        if ok(pb):  return "P/B", pb
    if sector in ("energy", "utilities"):
        if ok(ev):  return "EV/EBITDA", ev
    if not ok(pe) or pe > 80:
        if ok(ps):  return "P/S", ps
        if ok(ev):  return "EV/EBITDA", ev
    if ok(pe):      return "P/E", pe
    if ok(ps):      return "P/S", ps
    if ok(ev):      return "EV/EBITDA", ev
    if ok(pb):      return "P/B", pb
    return "—", None


def compute_valuation_changes(ticker_list: list, details: dict, metrics: dict,
                               financials: dict, cache: dict) -> dict:
    """
    Pick the smart valuation metric for each ticker and compute YoY change using
    annual income statement data (revenue / net income growth ratios).

    Math: multiple_change = (price_ratio / fundamental_ratio - 1) * 100
      where price_ratio = 1 + return_1y
            fundamental_ratio = yr0_metric / yr1_metric (revenue or net income)

    If price grew faster than the fundamental, the multiple expanded (positive).
    If fundamentals grew faster than price, the multiple contracted (negative).

    Returns {ticker: {"metric": str, "value": float|None, "change_1y": float|None}}.
    """
    results: dict = {}

    for ticker in ticker_list:
        det = details.get(ticker, {})
        met = metrics.get(ticker, {})
        fin = financials.get(ticker, {})
        metric_name, metric_val = pick_smart_valuation(ticker, det)

        change_1y = None
        r1y = met.get("return_1y")

        if metric_val is not None and r1y is not None:
            price_ratio = 1 + r1y  # current price / 1Y-ago price

            yr0_rev = fin.get("yr0_revenue")
            yr1_rev = fin.get("yr1_revenue")
            yr0_ni  = fin.get("yr0_net_income")
            yr1_ni  = fin.get("yr1_net_income")

            if metric_name == "P/S" and yr0_rev and yr1_rev and yr1_rev > 0:
                # Revenue growth: yr0 is most recent FY, yr1 is prior FY
                rev_ratio = yr0_rev / yr1_rev
                if rev_ratio > 0:
                    change_1y = (price_ratio / rev_ratio - 1) * 100

            elif metric_name == "P/E" and yr0_ni and yr1_ni and yr1_ni > 0:
                ni_ratio = yr0_ni / yr1_ni
                if ni_ratio > 0:
                    change_1y = (price_ratio / ni_ratio - 1) * 100

            elif metric_name == "P/B":
                # Book value grows slowly; use price return as crude approximation
                # (positive = price rose faster than book = multiple expanded)
                change_1y = r1y * 100

        results[ticker] = {"metric": metric_name, "value": metric_val, "change_1y": change_1y}
    return results


# ── Position trend tracking ───────────────────────────────────────────────────

def _prior_shares_13f(cik: str) -> dict:
    """Return {cusip: shares} from the second-most-recent 13F for this filer."""
    sub = get_submissions(cik)
    recent = sub["filings"]["recent"]
    accs = [a for f, a in zip(recent["form"], recent["accessionNumber"]) if f == "13F-HR"]
    if len(accs) < 2:
        return {}
    acc_nd = accs[1].replace("-", "")
    idx_html = fetch(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/")
    xml_names = re.findall(
        rf"/Archives/edgar/data/{cik}/{acc_nd}/([^\"/]+\.[xX][mM][lL])", idx_html)
    info_url = next(
        (f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/{n}"
         for n in xml_names if "primary_doc" not in n.lower()),
        None)
    if not info_url:
        return {}
    holdings, _ = _parse_13f_xml(fetch(info_url))
    return {c: int(h.get("shares", 0) or 0) for c, h in holdings.items()}


def _prior_shares_nport(cik: str, series_name: str, current_period: str) -> dict:
    """Return {cusip: shares} from the NPORT-P for this series one period back."""
    sub = get_submissions(cik)
    recent = sub["filings"]["recent"]
    nport_pairs = [
        (dt, acc)
        for f, dt, acc in zip(
            recent["form"], recent["filingDate"], recent["accessionNumber"])
        if f == "NPORT-P"
    ]
    for _, acc in nport_pairs:
        acc_nd = acc.replace("-", "")
        try:
            xml_text = fetch(
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}/primary_doc.xml")
        except Exception:
            continue
        m = re.search(r"<seriesName>([^<]+)</seriesName>", xml_text)
        if not (m and m.group(1).strip() == series_name):
            continue
        period_m = re.search(r"<repPdDate>([^<]+)</repPdDate>", xml_text)
        period = period_m.group(1) if period_m else ""
        if period == current_period:
            continue  # this is the current period — keep scanning
        holdings, _ = _parse_nport_xml(xml_text)
        return {c: float(h.get("shares", 0) or 0) for c, h in holdings.items()}
    return {}


def get_fund_trends(fund_data: dict, all_cfg: dict, cache: dict) -> dict:
    """
    Compare current vs prior quarter share counts per CUSIP per fund.
    Returns {fn: {cusip: 'up'|'down'|'flat'|'new'}}.
    Prior shares are cached under _hist_{key} with the standard TTL.
    """
    trends: dict = {}
    print("Computing position trends ...")
    for fn, info in fund_data.items():
        cfg = all_cfg.get(fn, {})
        cik = cfg.get("cik", "")
        if not cik:
            continue
        safe_key = re.sub(r"[^a-z0-9]", "_", fn.lower())
        cache_key = f"_hist_{safe_key}"
        cached = cache.get(cache_key, {})

        if _cache_fresh(cached):
            prior_shares = cached.get("shares", {})
        else:
            prior_shares = {}
            try:
                if info["type"] == "13f":
                    prior_shares = _prior_shares_13f(cik)
                else:
                    prior_shares = _prior_shares_nport(
                        cik, cfg.get("series_name", ""), info.get("period", ""))
            except Exception as exc:
                print(f"  [trend] {fn}: {exc}", file=sys.stderr)
            cache[cache_key] = {
                "shares": prior_shares, "_ts": datetime.now().isoformat()}
            print(f"  [{fn[:30]}] prior quarter: {len(prior_shares)} positions")

        if not prior_shares:
            continue

        fund_trends: dict = {}
        for cusip, h in info["holdings"].items():
            cur = float(h.get("shares", 0) or 0)
            pri = float(prior_shares.get(cusip, 0))
            if pri == 0 and cur > 0:
                fund_trends[cusip] = "new"
            elif cur > pri * 1.02:
                fund_trends[cusip] = "up"
            elif cur < pri * 0.98:
                fund_trends[cusip] = "down"
            else:
                fund_trends[cusip] = "flat"
        trends[fn] = fund_trends

    return trends


# ── Output helpers ─────────────────────────────────────────────────────────────

def _fmt_size(info: dict) -> str:
    na = info.get("net_assets", 0)
    if info.get("type") == "13f":
        return "(13F)"
    return f"${na/1e9:.1f}B" if na >= 1e9 else f"${na/1e6:.0f}M"


def _fmt_return(r) -> str:
    return f"{r*100:+.1f}%" if r is not None else "—"


def _pct_color(pct: float) -> str:
    t = min(pct / 16.0, 1.0)
    r = int(255 - t * 235)
    g = int(255 - t * 155)
    b = int(255 - t * 215)
    fg = "#000" if t < 0.55 else "#fff"
    return f"background:rgb({r},{g},{b});color:{fg}"


def _chg_color(v) -> str:
    """Green for positive change, red for negative."""
    if v is None:
        return "color:#aaa"
    if v > 0:
        return "color:#1a7a3a;font-weight:600"
    if v < 0:
        return "color:#b83232;font-weight:600"
    return "color:#445"


# ── Console report ────────────────────────────────────────────────────────────

def print_report(overlap, fund_names, fund_data, all_cfg, tickers, company_metrics):
    col_w   = max(len(fn) for fn in fund_names) + 2
    ticker_w = 8
    name_w   = 38
    row_prefix_len = 2 + ticker_w + 2 + name_w
    divider_w = row_prefix_len + col_w * len(fund_names)
    bar = "=" * divider_w

    print()
    print(bar)
    print("  SMART MONEY OVERLAP")
    print(f"  {date.today()}")
    print()
    for fn, info in fund_data.items():
        cfg = all_cfg.get(fn, {})
        r5 = _fmt_return(cfg.get("return_5y"))
        bucket = cfg.get("category", "")
        print(f"  {fn:<28}  [{bucket:<22}]  5Y={r5:>7}  {_fmt_size(info)}  {len(info['holdings'])} pos")
    print()
    print(f"  Filters: position >= {MIN_WEIGHT_PCT}%  |  held by >= {MIN_FUND_COUNT} funds")
    print(bar)

    header = f"  {'Ticker':<{ticker_w}}  {'Company':<{name_w}}"
    for fn in fund_names:
        header += f"  {fn:>{col_w-2}}"
    print()
    print(header)
    print("  " + "-" * (divider_w - 2))

    cur_count = None
    for cusip, data in overlap:
        fund_count = sum(1 for k in data if not k.startswith("_"))
        if fund_count != cur_count:
            cur_count = fund_count
            s = "s" if fund_count > 1 else ""
            print(f"\n  -- Held by {fund_count} fund{s} " + "-" * (divider_w - 20))

        ticker = tickers.get(cusip, cusip)
        name   = (data.get("_name") or "")[:name_w]
        row    = f"  {ticker:<{ticker_w}}  {name:<{name_w}}"
        for fn in fund_names:
            pct = data.get(fn)
            row += f"  {pct:>{col_w-3}.2f}%" if pct is not None else " " * col_w
        print(row)

    print(f"\n  {len(overlap)} positions shown.")
    print()


# ── CSV ───────────────────────────────────────────────────────────────────────

def save_csv(overlap, fund_names, tickers, company_metrics):
    with open(OUTPUT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Ticker", "CUSIP", "Company", "# Funds", "Mkt Cap", "1M", "3M", "1Y", "3Y", "5Y"] + fund_names)
        for cusip, data in overlap:
            ticker = tickers.get(cusip, "")
            fund_count = sum(1 for k in data if not k.startswith("_"))
            cm = company_metrics.get(ticker, {})
            mc = cm.get("market_cap")
            mc_str = f"${mc/1e9:.1f}B" if mc and mc >= 1e9 else (f"${mc/1e6:.0f}M" if mc else "")
            row = [ticker, cusip, data.get("_name", ""), fund_count, mc_str,
                   _fmt_return(cm.get("return_1m")), _fmt_return(cm.get("return_3m")),
                   _fmt_return(cm.get("return_1y")), _fmt_return(cm.get("return_3y")),
                   _fmt_return(cm.get("return_5y"))]
            row += [f"{data[fn]:.2f}%" if fn in data else "" for fn in fund_names]
            w.writerow(row)
    print(f"  Saved → {OUTPUT_CSV}")


# ── HTML ──────────────────────────────────────────────────────────────────────

def _ret_color(r) -> str:
    """Green for positive, red for negative, grey for missing."""
    if r is None:
        return "color:#aaa"
    return "color:#1a7a3a;font-weight:600" if r >= 0 else "color:#b83232;font-weight:600"


def _fmt_mcap(mc) -> str:
    if not mc:
        return "—"
    if mc >= 1e12:
        return f"${mc/1e12:.1f}T"
    if mc >= 1e9:
        return f"${mc/1e9:.1f}B"
    return f"${mc/1e6:.0f}M"


def save_html(overlap, fund_names, fund_data, all_cfg, tickers, company_metrics,
              company_details=None, etf_exposure=None, trends=None, sp500=None,
              ownership_changes=None, valuation_changes=None):
    now     = datetime.now().strftime("%B %d, %Y  %H:%M")
    n_funds = len(fund_names)

    # Group fund names by category for column headers
    buckets_order = CATEGORIES
    fund_buckets  = {fn: all_cfg.get(fn, {}).get("category", "Other") for fn in fund_names}

    # Build category spans for the column-group header row
    # Each span: (category_label, list_of_fund_names_in_that_category)
    category_cols: list = []
    for bucket in buckets_order:
        cols = [fn for fn in fund_names if fund_buckets.get(fn) == bucket]
        if cols:
            category_cols.append((bucket, cols))
    # Catch any "Other" funds
    other_cols = [fn for fn in fund_names if fund_buckets.get(fn) not in CATEGORIES]
    if other_cols:
        category_cols.append(("Other", other_cols))

    # Compact fund summary grid — collapsed by default (hover headers instead)
    cards_html = '<div class="funds-grid collapsed">'
    for bucket, cols in category_cols:
        cards_html += f'<div class="fg-bucket">{bucket}</div>'
        for fn in cols:
            info = fund_data[fn]
            cfg  = all_cfg.get(fn, {})
            r5   = _fmt_return(cfg.get("return_5y"))
            size = _fmt_size(info)
            period = info.get("period", "")[:7]  # "2025-12"
            cards_html += (
                f'<div class="fg-row">'
                f'<span class="fg-name">{fn}</span>'
                f'<span class="fg-meta">{period}</span>'
                f'<span class="fg-meta">{size}</span>'
                f'<span class="fg-ret">{r5}</span>'
                f'</div>'
            )
    cards_html += '</div>'

    # Fixed left columns: # Funds, Ticker, Company, Mkt Cap, 1M, 3M, 1Y, 3Y, 5Y,
    #                     Val, Val Δ1Y, Agg ΔYTD, Agg Δ1Y  (13 cols)
    N_FIXED = 13
    cat_th_html = f'<th class="cat-fixed" colspan="{N_FIXED}"></th>'
    for bucket, cols in category_cols:
        cat_th_html += f'<th colspan="{len(cols)}" class="cat-header">{bucket}</th>'

    # Fund column headers (rotated), offset by N_FIXED; data-fund for hover tooltip
    th_funds = "".join(
        f'<th class="fund-col" onclick="sortTable({i + N_FIXED})" data-fund="{fn}">'
        f'<span class="th-label">{fn} <span class="sort-icon">&#8597;</span></span></th>'
        for i, fn in enumerate(fund_names)
    )

    # Column filter row (3rd thead row)
    _fc_phs = ["≥", "tkr", "name", "cap", "1M", "3M", "1Y", "3Y", "5Y",
               "val", "Δval", "ΔYTD", "Δ1Y"]
    _filter_fixed = "".join(
        f'<th class="fc{i}"><input type="text" data-col="{i}" oninput="filterTable()" '
        f'placeholder="{ph}" class="col-filter"></th>'
        for i, ph in enumerate(_fc_phs)
    )
    _filter_funds = "".join(
        f'<th style="min-width:62px;max-width:62px"><input type="text" '
        f'data-col="{i + N_FIXED}" oninput="filterTable()" placeholder="" '
        f'class="col-filter fund-col-filter"></th>'
        for i in range(len(fund_names))
    )
    filter_row_html = f'<tr class="filter-row">{_filter_fixed}{_filter_funds}</tr>'

    # Table rows — no more group-header rows; # Funds is a data column
    rows_html = ""
    for cusip, data in overlap:
        fund_count = sum(1 for k in data if not k.startswith("_"))
        ticker = tickers.get(cusip, cusip)
        name   = (data.get("_name") or "").title()
        cm     = company_metrics.get(ticker, {})
        mc     = _fmt_mcap(cm.get("market_cap"))
        r1m    = cm.get("return_1m"); r3m = cm.get("return_3m"); r1y = cm.get("return_1y")
        r3y    = cm.get("return_3y"); r5y = cm.get("return_5y")

        # max ownership % across all funds for this stock
        own_vals = [v for k, v in data.items() if k.startswith("_own_")]
        max_own  = max(own_vals) if own_vals else None
        own_tip  = f" (max {max_own:.1f}% of co.)" if max_own else ""

        safe_name = name.replace("'", "\\'")
        rows_html += f'\n  <tr>'
        rows_html += f'<td class="n-funds fc0">{fund_count}</td>'
        rows_html += (
            f'<td class="ticker ticker-link fc1" title="{ticker}{own_tip}" '
            f'onclick="openModal(\'{ticker}\',\'{safe_name}\')">{ticker}'
        )
        if max_own and max_own >= 1.0:
            rows_html += f'<span class="own-badge">{max_own:.1f}%★</span>'
        rows_html += '</td>'
        not_sp500 = sp500 and ticker and len(ticker) <= 5 and ticker not in sp500
        sp_badge = ' <span class="sp-badge" title="Not in S&amp;P 500">non-SP</span>' if not_sp500 else ""
        rows_html += f'<td class="company fc2">{name}{sp_badge}</td>'
        rows_html += f'<td class="mcap fc3">{mc}</td>'
        rows_html += f'<td class="fc4" style="{_ret_color(r1m)}">{_fmt_return(r1m)}</td>'
        rows_html += f'<td class="fc5" style="{_ret_color(r3m)}">{_fmt_return(r3m)}</td>'
        rows_html += f'<td class="fc6" style="{_ret_color(r1y)}">{_fmt_return(r1y)}</td>'
        rows_html += f'<td class="fc7" style="{_ret_color(r3y)}">{_fmt_return(r3y)}</td>'
        rows_html += f'<td class="fc8" style="{_ret_color(r5y)}">{_fmt_return(r5y)}</td>'
        # fc9: sector-appropriate valuation metric
        val_data   = (valuation_changes  or {}).get(ticker, {})
        own_data   = (ownership_changes  or {}).get(cusip,  {})
        val_metric = val_data.get("metric", "—")
        val_value  = val_data.get("value")
        val_chg    = val_data.get("change_1y")
        val_disp   = f'{val_value:.1f}' if val_value is not None else "—"
        val_label  = f'<span style="font-size:.6rem;color:#88a;margin-left:2px">{val_metric}</span>' if val_metric != "—" else ""
        rows_html += (f'<td class="fc9" title="{val_metric}" style="font-size:.78rem">'
                      f'{val_disp}{val_label}</td>')
        # fc10: YoY change in valuation metric
        if val_chg is not None:
            rows_html += f'<td class="fc10" style="{_chg_color(val_chg)}">{val_chg:+.1f}%</td>'
        else:
            rows_html += '<td class="fc10" style="color:#aaa">—</td>'
        # fc11: aggregate ownership change YTD (%)
        ytd_d = own_data.get("ytd_delta")
        if ytd_d is not None:
            ytd_disp = "NEW" if ytd_d >= 900 else f"{ytd_d:+.0f}%"
            rows_html += f'<td class="fc11" style="{_chg_color(ytd_d)}">{ytd_disp}</td>'
        else:
            rows_html += '<td class="fc11" style="color:#aaa">—</td>'
        # fc12: aggregate ownership change 1Y (%)
        y1_d = own_data.get("y1_delta")
        if y1_d is not None:
            y1_disp = "NEW" if y1_d >= 900 else f"{y1_d:+.0f}%"
            rows_html += f'<td class="fc12" style="{_chg_color(y1_d)}">{y1_disp}</td>'
        else:
            rows_html += '<td class="fc12" style="color:#aaa">—</td>'
        for fn in fund_names:
            pct = data.get(fn)
            if pct is not None:
                own = data.get(f"_own_{fn}")
                tip = f' title="{own:.2f}% of company"' if own else ""
                tr = (trends or {}).get(fn, {}).get(cusip)
                if tr == "up":
                    arrow = '<span class="tr-up">▲</span>'
                elif tr == "down":
                    arrow = '<span class="tr-dn">▼</span>'
                elif tr == "new":
                    arrow = '<span class="tr-new">★</span>'
                else:
                    arrow = ""
                rows_html += f'<td class="fund-val" style="{_pct_color(pct)}"{tip}>{pct:.2f}%{arrow}</td>'
            else:
                rows_html += '<td class="fund-val empty">—</td>'
        rows_html += "\n  </tr>"

    # JSON blobs for the modal and fund tooltip
    details_json = json.dumps(company_details or {}, ensure_ascii=False)
    etf_json     = json.dumps(etf_exposure   or {}, ensure_ascii=False)

    fund_info = {}
    for fn in fund_names:
        info = fund_data[fn]
        cfg  = all_cfg.get(fn, {})
        fund_info[fn] = {
            "category": cfg.get("category", ""),
            "period":   info.get("period", "")[:7],
            "size":     _fmt_size(info),
            "positions": len(info["holdings"]),
            "r3":       _fmt_return(cfg.get("return_3y")),
            "r5":       _fmt_return(cfg.get("return_5y")),
            "ftype":    "13F-HR" if info["type"] == "13f" else "NPORT-P",
        }
    fund_info_json = json.dumps(fund_info, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smart Money Overlap</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f4f6f9; color: #1a1a2e; }}

  .header {{ background: #1a1a2e; color: #fff; padding: 20px 32px;
             display: flex; align-items: baseline; gap: 16px; }}
  .header h1 {{ font-size: 1.4rem; font-weight: 700; letter-spacing: .03em; }}
  .header .ts {{ font-size: .8rem; color: #8899bb; margin-left: auto; }}

  /* Compact fund summary grid */
  .funds-bar {{
    background: #f8f9fc; border-bottom: 1px solid #e0e4ed;
  }}
  .funds-toggle {{
    display: flex; align-items: center; gap: 8px;
    padding: 6px 32px; cursor: pointer; user-select: none;
    font-size: .72rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .07em; color: #889;
    border: none; background: none; width: 100%; text-align: left;
  }}
  .funds-toggle:hover {{ color: #556; }}
  .toggle-arrow {{ font-size: .7rem; transition: transform .2s; display: inline-block; }}
  .funds-toggle.collapsed .toggle-arrow {{ transform: rotate(-90deg); }}
  .funds-grid {{
    display: flex; flex-wrap: wrap; gap: 0 32px;
    padding: 4px 32px 10px;
    overflow: hidden; transition: max-height .25s ease;
    max-height: 600px;
  }}
  .funds-grid.collapsed {{ max-height: 0; padding-bottom: 0; }}
  .fg-bucket {{
    width: 100%; font-size: .65rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .08em; color: #889; padding: 6px 0 2px;
  }}
  .fg-bucket:first-child {{ padding-top: 0; }}
  .fg-row {{
    display: flex; align-items: baseline; gap: 8px;
    font-size: .75rem; padding: 1px 0; white-space: nowrap;
  }}
  .fg-name {{ font-weight: 600; color: #1a1a2e; min-width: 160px; }}
  .fg-meta {{ color: #778; min-width: 52px; }}
  .fg-ret  {{ color: #226; font-weight: 600; min-width: 52px; }}

  /* Fund hover tooltip */
  .fund-tooltip {{
    position: fixed; z-index: 600; pointer-events: none;
    background: #fff; border: 1px solid #dde3ed; border-radius: 10px;
    padding: 13px 16px; min-width: 230px;
    box-shadow: 0 6px 24px rgba(0,0,0,.15);
    display: none;
  }}
  .ft-name {{ font-weight: 700; font-size: .9rem; color: #1a1a2e; margin-bottom: 2px; }}
  .ft-cat  {{ font-size: .68rem; color: #778; text-transform: uppercase;
              letter-spacing: .06em; margin-bottom: 8px; }}
  .ft-row  {{ font-size: .78rem; color: #445; margin-top: 4px; display: flex; gap: 6px; }}
  .ft-lbl  {{ color: #99a; }}
  .ft-val  {{ font-weight: 600; color: #1a1a2e; }}
  .ft-ret  {{ font-weight: 600; color: #226; }}

  .filter-bar {{ padding: 16px 32px; display: flex; gap: 24px;
                 align-items: center; font-size: .82rem; color: #445; }}
  .filter-bar input {{ padding: 5px 10px; border: 1px solid #ccd;
                       border-radius: 5px; font-size: .82rem; width: 220px; }}

  /* Outer div handles the side padding and visual chrome */
  .table-outer {{ padding: 0 32px 40px; }}
  /* Inner wrap is the scroll container for both axes; sticky works within it */
  .table-wrap {{
    overflow: auto;
    max-height: calc(100vh - 200px);
    border-radius: 8px;
    box-shadow: 0 1px 4px rgba(0,0,0,.08);
  }}
  table {{ border-collapse: collapse; width: 100%; font-size: .82rem;
           background: #fff; }}

  thead th {{ background: #1a1a2e; color: #fff; padding: 8px 12px;
              text-align: right; white-space: nowrap;
              position: sticky; top: 0; z-index: 10; cursor: default; }}
  thead th:first-child, thead th:nth-child(2) {{ text-align: left; }}
  thead th.cat-header {{ background: #2d3a5a; font-size: .7rem;
                         letter-spacing: .06em; text-transform: uppercase;
                         text-align: center; border-left: 2px solid #1a1a2e;
                         padding: 6px 4px; }}

  thead th.fund-col {{
    width: 62px; min-width: 62px; max-width: 62px;
    height: 130px; padding: 0; vertical-align: bottom;
    text-align: left; cursor: pointer; overflow: visible; white-space: nowrap;
  }}
  thead th.fund-col:hover {{ background: #2d2d50; }}
  .th-label {{
    display: block; transform: rotate(-45deg); transform-origin: left bottom;
    margin-left: 28px; padding-bottom: 8px; font-size: .72rem;
    font-weight: 600; white-space: nowrap; line-height: 1;
  }}
  .sort-icon {{ margin-left: 3px; opacity: .45; font-size: .65rem; }}

  tbody tr:hover td {{ background: #f0f4ff !important; color: #000 !important; }}
  tbody tr:nth-child(even) {{ background: #fafbfd; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #eef;
        text-align: right; white-space: nowrap; font-size: .82rem; }}
  td.fund-val {{ width: 62px; min-width: 62px; text-align: center;
                 padding: 6px 3px; font-size: .79rem; }}
  td.ticker {{ font-family: monospace; font-size: .85rem; font-weight: 700;
               text-align: left; position: relative; }}
  td.ticker-link {{ cursor: pointer; color: #1a3a8a; text-decoration: underline;
                    text-underline-offset: 2px; }}
  td.ticker-link:hover {{ color: #0a2060; }}
  td.company {{ text-align: left; overflow: hidden;
                text-overflow: ellipsis; font-weight: 500; }}
  td.mcap {{ color: #445; font-size: .79rem; }}
  td.n-funds {{ font-weight: 700; text-align: center; font-size: .85rem; color: #1a1a2e; }}
  td.empty {{ color: #ccd; }}
  .own-badge {{ font-size: .6rem; background: #e8f4e8; color: #1a6b2a;
                border-radius: 3px; padding: 1px 3px; margin-left: 4px;
                font-weight: 700; vertical-align: middle; white-space: nowrap; }}
  .tr-up  {{ font-size: .6rem; color: #1a7a3a; margin-left: 2px; vertical-align: middle; }}
  .tr-dn  {{ font-size: .6rem; color: #b83232; margin-left: 2px; vertical-align: middle; }}
  .tr-new {{ font-size: .55rem; color: #6644cc; margin-left: 2px; vertical-align: middle; }}
  .sp-badge {{ font-size: .58rem; background: #fff3cd; color: #856404;
               border: 1px solid #ffc107; border-radius: 3px; padding: 0px 3px;
               margin-left: 5px; font-weight: 600; vertical-align: middle; white-space: nowrap; }}
  tr.filtered-out {{ display: none; }}
  .legend {{ display: flex; gap: 4px; align-items: center; margin-left: auto; }}
  .legend span {{ display: inline-block; width: 20px; height: 14px; border-radius: 3px; }}
  .legend-label {{ font-size: .75rem; color: #778; }}

  /* ── Frozen left columns (fc0–fc12) ─────────────────────────────────── */
  td.fc0, td.fc1, td.fc2, td.fc3, td.fc4, td.fc5, td.fc6, td.fc7, td.fc8,
  td.fc9, td.fc10, td.fc11, td.fc12 {{
    position: sticky; z-index: 2; background: #fff;
  }}
  tbody tr:nth-child(even) td.fc0, tbody tr:nth-child(even) td.fc1,
  tbody tr:nth-child(even) td.fc2, tbody tr:nth-child(even) td.fc3,
  tbody tr:nth-child(even) td.fc4, tbody tr:nth-child(even) td.fc5,
  tbody tr:nth-child(even) td.fc6, tbody tr:nth-child(even) td.fc7,
  tbody tr:nth-child(even) td.fc8, tbody tr:nth-child(even) td.fc9,
  tbody tr:nth-child(even) td.fc10, tbody tr:nth-child(even) td.fc11,
  tbody tr:nth-child(even) td.fc12 {{ background: #fafbfd; }}
  tbody tr:hover td.fc0, tbody tr:hover td.fc1, tbody tr:hover td.fc2,
  tbody tr:hover td.fc3, tbody tr:hover td.fc4, tbody tr:hover td.fc5,
  tbody tr:hover td.fc6, tbody tr:hover td.fc7, tbody tr:hover td.fc8,
  tbody tr:hover td.fc9, tbody tr:hover td.fc10, tbody tr:hover td.fc11,
  tbody tr:hover td.fc12 {{ background: #f0f4ff !important; }}
  /* Column widths and left offsets — must sum correctly */
  td.fc0,  thead tr.col-header-row th.fc0  {{ left:   0px; width:  42px; min-width:  42px; }}
  td.fc1,  thead tr.col-header-row th.fc1  {{ left:  42px; width:  72px; min-width:  72px; }}
  td.fc2,  thead tr.col-header-row th.fc2  {{ left: 114px; width: 195px; min-width: 195px; max-width: 195px; }}
  td.fc3,  thead tr.col-header-row th.fc3  {{ left: 309px; width:  70px; min-width:  70px; }}
  td.fc4,  thead tr.col-header-row th.fc4  {{ left: 379px; width:  55px; min-width:  55px; }}
  td.fc5,  thead tr.col-header-row th.fc5  {{ left: 434px; width:  55px; min-width:  55px; }}
  td.fc6,  thead tr.col-header-row th.fc6  {{ left: 489px; width:  55px; min-width:  55px; }}
  td.fc7,  thead tr.col-header-row th.fc7  {{ left: 544px; width:  55px; min-width:  55px; }}
  td.fc8,  thead tr.col-header-row th.fc8  {{ left: 599px; width:  55px; min-width:  55px; }}
  td.fc9,  thead tr.col-header-row th.fc9  {{ left: 654px; width:  88px; min-width:  88px; }}
  td.fc10, thead tr.col-header-row th.fc10 {{ left: 742px; width:  62px; min-width:  62px; }}
  td.fc11, thead tr.col-header-row th.fc11 {{ left: 804px; width:  62px; min-width:  62px; }}
  td.fc12, thead tr.col-header-row th.fc12 {{ left: 866px; width:  62px; min-width:  62px;
    border-right: 2px solid rgba(100,120,180,.25); }}
  /* Freeze the first th in the category row */
  thead tr:first-child th.cat-fixed {{ position: sticky; left: 0; z-index: 15; }}
  /* Raise z-index on frozen header cells */
  thead tr.col-header-row th.fc0,  thead tr.col-header-row th.fc1,
  thead tr.col-header-row th.fc2,  thead tr.col-header-row th.fc3,
  thead tr.col-header-row th.fc4,  thead tr.col-header-row th.fc5,
  thead tr.col-header-row th.fc6,  thead tr.col-header-row th.fc7,
  thead tr.col-header-row th.fc8,  thead tr.col-header-row th.fc9,
  thead tr.col-header-row th.fc10, thead tr.col-header-row th.fc11,
  thead tr.col-header-row th.fc12 {{ z-index: 15; }}
  /* ── Column filter row ───────────────────────────────────────────────── */
  thead tr.filter-row th {{
    position: sticky; top: 164px; z-index: 10;
    background: #252e4a; padding: 3px 4px;
    border-bottom: 2px solid #1a1a2e;
  }}
  thead tr.filter-row th.fc0,  thead tr.filter-row th.fc1,
  thead tr.filter-row th.fc2,  thead tr.filter-row th.fc3,
  thead tr.filter-row th.fc4,  thead tr.filter-row th.fc5,
  thead tr.filter-row th.fc6,  thead tr.filter-row th.fc7,
  thead tr.filter-row th.fc8,  thead tr.filter-row th.fc9,
  thead tr.filter-row th.fc10, thead tr.filter-row th.fc11,
  thead tr.filter-row th.fc12 {{ z-index: 16; }}
  .col-filter {{
    width: 100%; min-width: 0; padding: 2px 4px;
    border: 1px solid #4a5570; border-radius: 3px;
    font-size: .68rem; background: #1e2840; color: #cdd; outline: none;
  }}
  .col-filter:focus {{ border-color: #7ec8f8; }}
  .col-filter::placeholder {{ color: #4a5a7a; }}
  .fund-col-filter {{ width: 46px; }}

  /* ── Modal ── */
  .modal-overlay {{
    display: none; position: fixed; inset: 0;
    background: rgba(10,14,30,.55); backdrop-filter: blur(3px);
    z-index: 1000; align-items: center; justify-content: center; padding: 24px;
  }}
  .modal-overlay.open {{ display: flex; }}
  .modal-box {{
    background: #fff; border-radius: 12px; width: 100%; max-width: 920px;
    max-height: 90vh; overflow-y: auto; box-shadow: 0 8px 40px rgba(0,0,0,.28);
    display: flex; flex-direction: column;
  }}
  .modal-head {{
    background: #1a1a2e; color: #fff; padding: 18px 24px 14px;
    display: flex; align-items: flex-start; gap: 14px; border-radius: 12px 12px 0 0;
    flex-shrink: 0;
  }}
  .modal-ticker-big {{
    font-family: monospace; font-size: 1.8rem; font-weight: 800;
    color: #7ec8f8; line-height: 1;
  }}
  .modal-head-right {{ flex: 1; }}
  .modal-company-name {{ font-size: 1rem; font-weight: 600; margin-bottom: 3px; }}
  .modal-sector-line {{ font-size: .78rem; color: #8899bb; }}
  .modal-close {{
    background: none; border: none; color: #8899bb; font-size: 1.5rem;
    cursor: pointer; padding: 0 4px; line-height: 1; margin-left: auto;
    align-self: flex-start;
  }}
  .modal-close:hover {{ color: #fff; }}
  .modal-tabs {{
    display: flex; gap: 0; border-bottom: 2px solid #eef; flex-shrink: 0;
    padding: 0 20px;
  }}
  .tab-btn {{
    background: none; border: none; padding: 11px 20px; font-size: .85rem;
    font-weight: 600; color: #667; cursor: pointer; border-bottom: 2px solid transparent;
    margin-bottom: -2px;
  }}
  .tab-btn.active {{ color: #1a1a2e; border-bottom-color: #1a1a2e; }}
  .tab-btn:hover {{ color: #1a1a2e; }}
  .tab-pane {{ padding: 0; }}
  #tab-etfs {{ padding: 20px 24px; }}
  #modalChart {{ width: 100%; }}
  .modal-lower {{ display: flex; gap: 20px; padding: 16px 24px 20px; }}
  .metrics-grid {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;
    min-width: 280px;
  }}
  .metric-card {{
    background: #f6f8fc; border-radius: 8px; padding: 10px 12px; text-align: center;
  }}
  .metric-label {{ font-size: .68rem; color: #778; text-transform: uppercase;
                   letter-spacing: .05em; margin-bottom: 4px; }}
  .metric-val {{ font-size: 1.05rem; font-weight: 700; color: #1a1a2e; }}
  .metric-val.na {{ color: #bbc; font-size: .85rem; }}
  .modal-desc {{
    flex: 1; font-size: .82rem; color: #334; line-height: 1.65;
    max-height: 160px; overflow-y: auto;
  }}
  /* ETF table */
  .etf-table {{ width: 100%; border-collapse: collapse; font-size: .83rem; }}
  .etf-table th {{
    background: #f0f2f8; font-size: .72rem; text-transform: uppercase;
    letter-spacing: .05em; padding: 7px 10px; text-align: left; color: #556;
  }}
  .etf-table th:not(:first-child):not(:nth-child(2)) {{ text-align: right; }}
  .etf-table td {{ padding: 7px 10px; border-bottom: 1px solid #eef; }}
  .etf-table td:not(:first-child):not(:nth-child(2)) {{ text-align: right; }}
  .etf-table tr:hover td {{ background: #f5f7ff; }}
  .etf-ticker {{ font-family: monospace; font-weight: 700; color: #1a3a8a; }}
  .etf-weight {{ font-weight: 600; color: #1a7a3a; }}
  .no-etf-msg {{ color: #99a; font-size: .83rem; padding: 20px 0; text-align: center; }}
  .etf-note {{ font-size: .74rem; color: #99a; margin-top: 10px; }}
</style>
</head>
<body>

<div class="header">
  <h1>Smart Money Overlap</h1>
  <span style="color:#8899bb;font-size:.85rem">
    min position {MIN_WEIGHT_PCT}% &nbsp;·&nbsp; held by &ge; {MIN_FUND_COUNT} funds
  </span>
  <span class="ts">Updated {now}</span>
</div>

<div class="funds-bar">
  <button class="funds-toggle collapsed" onclick="toggleFunds(this)">
    <span class="toggle-arrow">&#9660;</span> Funds ({n_funds})
  </button>
  {cards_html}
</div>
<div class="filter-bar">
  <label>Filter:
    <input type="text" id="filterBox" placeholder="ticker or company name..."
           oninput="filterTable()">
  </label>
  <div class="legend">
    <span class="legend-label">Weight:</span>
    <span style="background:rgb(238,255,245)"></span>
    <span style="background:rgb(180,240,210)"></span>
    <span style="background:rgb(100,200,150)"></span>
    <span style="background:rgb(40,140,80)"></span>
    <span style="background:rgb(20,100,40)"></span>
    <span class="legend-label">low → high</span>
  </div>
</div>

<div class="table-outer"><div class="table-wrap">
<table id="mainTable">
  <thead>
    <tr>{cat_th_html}</tr>
    <tr class="col-header-row">
      <th class="fc0" onclick="sortTable(0)" style="cursor:pointer;text-align:center"># <span class="sort-icon">&#8597;</span></th>
      <th class="fc1" onclick="sortTable(1)" style="cursor:pointer;text-align:left">Ticker <span class="sort-icon">&#8597;</span></th>
      <th class="fc2" onclick="sortTable(2)" style="cursor:pointer;text-align:left">Company <span class="sort-icon">&#8597;</span></th>
      <th class="fc3" onclick="sortTable(3)" style="cursor:pointer">Mkt Cap <span class="sort-icon">&#8597;</span></th>
      <th class="fc4" onclick="sortTable(4)" style="cursor:pointer">1M <span class="sort-icon">&#8597;</span></th>
      <th class="fc5" onclick="sortTable(5)" style="cursor:pointer">3M <span class="sort-icon">&#8597;</span></th>
      <th class="fc6" onclick="sortTable(6)" style="cursor:pointer">1Y <span class="sort-icon">&#8597;</span></th>
      <th class="fc7" onclick="sortTable(7)" style="cursor:pointer">3Y <span class="sort-icon">&#8597;</span></th>
      <th class="fc8" onclick="sortTable(8)" style="cursor:pointer">5Y <span class="sort-icon">&#8597;</span></th>
      <th class="fc9"  onclick="sortTable(9)"  style="cursor:pointer" title="Sector-appropriate valuation metric">Val <span class="sort-icon">&#8597;</span></th>
      <th class="fc10" onclick="sortTable(10)" style="cursor:pointer" title="YoY change in valuation metric (stored snapshots; populates after 1 year)">Val &#916;1Y <span class="sort-icon">&#8597;</span></th>
      <th class="fc11" onclick="sortTable(11)" style="cursor:pointer" title="% change in aggregate portfolio weight YTD (NEW = brand new position)">&#916;YTD <span class="sort-icon">&#8597;</span></th>
      <th class="fc12" onclick="sortTable(12)" style="cursor:pointer" title="% change in aggregate portfolio weight vs 1 year ago (NEW = brand new position)">&#916;1Y <span class="sort-icon">&#8597;</span></th>
      {th_funds}
    </tr>
    {filter_row_html}
  </thead>
  <tbody>{rows_html}</tbody>
</table>
</div></div>

<!-- Fund hover tooltip -->
<div id="fundTooltip" class="fund-tooltip">
  <div class="ft-name" id="ftName"></div>
  <div class="ft-cat"  id="ftCat"></div>
  <div class="ft-row"><span class="ft-lbl">Filed:</span><span class="ft-val" id="ftPeriod"></span>
    <span class="ft-lbl" style="margin-left:8px">Type:</span><span class="ft-val" id="ftType"></span></div>
  <div class="ft-row"><span class="ft-lbl">Size:</span><span class="ft-val" id="ftSize"></span>
    <span class="ft-lbl" style="margin-left:8px">Positions:</span><span class="ft-val" id="ftPos"></span></div>
  <div class="ft-row"><span class="ft-lbl">3Y:</span><span class="ft-ret" id="ftR3"></span>
    <span class="ft-lbl" style="margin-left:10px">5Y:</span><span class="ft-ret" id="ftR5"></span></div>
</div>

<!-- Stock detail modal -->
<div id="stockModal" class="modal-overlay" onclick="if(event.target===this)closeModal()">
  <div class="modal-box">
    <div class="modal-head">
      <div>
        <div class="modal-ticker-big" id="modalTicker"></div>
      </div>
      <div class="modal-head-right">
        <div class="modal-company-name" id="modalCompany"></div>
        <div class="modal-sector-line" id="modalSector"></div>
      </div>
      <button class="modal-close" onclick="closeModal()">&#x2715;</button>
    </div>
    <div class="modal-tabs">
      <button class="tab-btn active" onclick="showTab('overview',this)">Overview</button>
      <button class="tab-btn" onclick="showTab('etfs',this)">ETFs</button>
    </div>
    <div id="tab-overview" class="tab-pane">
      <div id="modalChart"></div>
      <div class="modal-lower">
        <div id="modalMetrics" class="metrics-grid"></div>
        <div id="modalDesc" class="modal-desc"></div>
      </div>
    </div>
    <div id="tab-etfs" class="tab-pane" style="display:none">
      <div id="etfContent"></div>
    </div>
  </div>
</div>

<script>
const stockDetails = {details_json};
const etfData      = {etf_json};
const fundInfo     = {fund_info_json};
let sortDir = {{}};
let _activeTab = 'overview';

function openModal(ticker, company) {{
  const d = stockDetails[ticker] || {{}};
  document.getElementById('modalTicker').textContent  = ticker;
  document.getElementById('modalCompany').textContent = company;
  const sector = [d.sector, d.industry].filter(Boolean).join(' › ');
  document.getElementById('modalSector').textContent  = sector;

  // Metrics grid
  const metrics = [
    ['Trailing P/E', d.trailing_pe],
    ['Forward P/E',  d.forward_pe],
    ['P / Sales',    d.ps_ratio],
    ['P / Book',     d.pb_ratio],
    ['EV / EBITDA',  d.ev_ebitda],
    ['52W High',     d['52w_high'] != null ? '$' + d['52w_high'].toFixed(2) : null],
    ['52W Low',      d['52w_low']  != null ? '$' + d['52w_low'].toFixed(2)  : null],
  ];
  document.getElementById('modalMetrics').innerHTML = metrics.map(([label, val]) => {{
    const display = (val == null || (typeof val === 'number' && isNaN(val)))
      ? '<span class="metric-val na">—</span>'
      : `<span class="metric-val">${{typeof val === 'number' ? val.toFixed(1) : val}}</span>`;
    return `<div class="metric-card"><div class="metric-label">${{label}}</div>${{display}}</div>`;
  }}).join('');

  // Description
  const desc = d.description || '';
  document.getElementById('modalDesc').textContent = desc;

  // ETF tab content
  const etfs = etfData[ticker] || [];
  let etfHtml;
  if (etfs.length === 0) {{
    etfHtml = '<p class="no-etf-msg">No concentrated ETF data found (may not be available for all tickers)</p>';
  }} else {{
    etfHtml = `<table class="etf-table">
      <thead><tr>
        <th>ETF</th><th>Name</th>
        <th style="text-align:right">Weight</th>
        <th>Category</th>
        <th style="text-align:right">Exp Ratio</th>
      </tr></thead>
      <tbody>` +
      etfs.map(e => `<tr>
        <td class="etf-ticker">${{e.ticker}}</td>
        <td>${{e.name}}</td>
        <td class="etf-weight">${{e.weight.toFixed(2)}}%</td>
        <td style="font-size:.78rem;color:#556">${{e.category || '—'}}</td>
        <td style="text-align:right;font-size:.78rem;color:#556">${{e.expense_ratio || '—'}}</td>
      </tr>`).join('') +
      `</tbody></table>
      <p class="etf-note">Source: ETFdb.com &middot; excludes leveraged / single-stock wrappers &middot; sorted by weight</p>`;
  }}
  document.getElementById('etfContent').innerHTML = etfHtml;

  // Reset to overview tab
  showTab('overview', document.querySelector('.tab-btn'));
  document.getElementById('stockModal').classList.add('open');
  document.body.style.overflow = 'hidden';

  // Finviz chart image — always works from file:// (no WebSocket/origin issues)
  const chartDiv = document.getElementById('modalChart');
  chartDiv.innerHTML = `
    <div style="position:relative;background:#f8f9fb;border-bottom:1px solid #eef">
      <img id="finvizChart"
        src="https://finviz.com/chart.ashx?t=${{ticker}}&ty=c&ta=1&p=w&s=xl"
        style="width:100%;height:360px;object-fit:contain;display:block"
        alt="${{ticker}} chart"
        onerror="document.getElementById('chartErr').style.display='flex'">
      <div id="chartErr" style="display:none;position:absolute;inset:0;align-items:center;
           justify-content:center;color:#99a;font-size:.85rem;flex-direction:column;gap:8px">
        <span>Chart unavailable</span>
      </div>
    </div>
    <div style="display:flex;gap:16px;justify-content:flex-end;padding:6px 12px 2px;
         font-size:.74rem;background:#f8f9fb">
      <span style="color:#aab">Finviz weekly chart &nbsp;·&nbsp; click to open interactive:</span>
      <a href="https://www.tradingview.com/chart/?symbol=${{ticker}}" target="_blank"
         style="color:#1a3a8a;font-weight:600">TradingView &#x2197;</a>
      <a href="https://finance.yahoo.com/chart/${{ticker}}" target="_blank"
         style="color:#1a3a8a;font-weight:600">Yahoo Finance &#x2197;</a>
    </div>`;
}}

function closeModal() {{
  document.getElementById('stockModal').classList.remove('open');
  document.body.style.overflow = '';
  document.getElementById('modalChart').innerHTML = '';
}}

function showTab(tab, btn) {{
  document.getElementById('tab-overview').style.display = tab === 'overview' ? '' : 'none';
  document.getElementById('tab-etfs').style.display     = tab === 'etfs'     ? '' : 'none';
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
}}

document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeModal(); }});

function toggleFunds(btn) {{
  const grid = btn.nextElementSibling;
  const collapsed = grid.classList.toggle('collapsed');
  btn.classList.toggle('collapsed', collapsed);
}}

// Fund column header tooltips
(function() {{
  const tip = document.getElementById('fundTooltip');
  document.querySelectorAll('th.fund-col[data-fund]').forEach(th => {{
    th.addEventListener('mouseenter', () => {{
      const f = fundInfo[th.dataset.fund];
      if (!f) return;
      document.getElementById('ftName').textContent    = th.dataset.fund;
      document.getElementById('ftCat').textContent     = f.category;
      document.getElementById('ftPeriod').textContent  = f.period;
      document.getElementById('ftType').textContent    = f.ftype;
      document.getElementById('ftSize').textContent    = f.size;
      document.getElementById('ftPos').textContent     = f.positions;
      document.getElementById('ftR3').textContent      = f.r3;
      document.getElementById('ftR5').textContent      = f.r5;
      const r = th.getBoundingClientRect();
      tip.style.display = 'block';
      // Position below header, nudge left if near right edge
      const left = Math.min(r.left, window.innerWidth - 250);
      tip.style.left = left + 'px';
      tip.style.top  = (r.bottom + 6) + 'px';
    }});
    th.addEventListener('mouseleave', () => {{ tip.style.display = 'none'; }});
  }});
}}());

function sortTable(col) {{
  const tbody = document.querySelector('#mainTable tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const dir = (sortDir[col] = -(sortDir[col] || 1));
  rows.sort((a, b) => {{
    const ca = a.cells[col]?.innerText.trim() || '';
    const cb = b.cells[col]?.innerText.trim() || '';
    const na = parseFloat(ca), nb = parseFloat(cb);
    if (!isNaN(na) && !isNaN(nb)) return dir * (na - nb);
    return dir * ca.localeCompare(cb);
  }});
  rows.forEach(r => tbody.appendChild(r));
}}

function matchFilter(cellText, fval) {{
  const s = cellText.replace(/[+%,$★▲▼◆]/g, '').trim();
  const cmp = fval.match(/^([><]=?)\s*(-?\d+\.?\d*)$/);
  if (cmp) {{
    const n = parseFloat(s), t = parseFloat(cmp[2]);
    if (isNaN(n)) return false;
    switch (cmp[1]) {{
      case '>':  return n > t;
      case '>=': return n >= t;
      case '<':  return n < t;
      case '<=': return n <= t;
    }}
  }}
  if (fval === '!') return s !== '—' && s !== '';
  return s.toLowerCase().includes(fval.toLowerCase());
}}

function filterTable() {{
  const globalQ = document.getElementById('filterBox')?.value.toLowerCase() || '';
  const colF = {{}};
  document.querySelectorAll('.filter-row input[data-col]').forEach(inp => {{
    const v = inp.value.trim();
    if (v) colF[parseInt(inp.dataset.col)] = v;
  }});
  const active = globalQ || Object.keys(colF).length > 0;
  document.querySelectorAll('#mainTable tbody tr').forEach(r => {{
    if (!active) {{ r.classList.remove('filtered-out'); return; }}
    if (globalQ && !r.innerText.toLowerCase().includes(globalQ)) {{
      r.classList.add('filtered-out'); return;
    }}
    for (const [col, fval] of Object.entries(colF)) {{
      const cell = r.cells[col];
      if (!cell || !matchFilter(cell.innerText, fval)) {{
        r.classList.add('filtered-out'); return;
      }}
    }}
    r.classList.remove('filtered-out');
  }});
}}
</script>
</body>
</html>"""

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Saved → {OUTPUT_HTML}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    cache = _load_cache()

    print("Building fund list ...")
    all_cfg = build_fund_list(cache)
    _save_cache(cache)

    print(f"\nFetching holdings for {len(all_cfg)} funds from SEC EDGAR ...\n")
    fund_data: dict = {}
    for label, cfg in all_cfg.items():
        try:
            if cfg["type"] == "nport":
                info = load_nport(label, cfg["cik"], cfg["series_name"])
            else:
                info = load_13f(label, cfg["cik"])
            fund_data[label] = info
        except Exception as exc:
            print(f"  ✗ {label}: {exc}", file=sys.stderr)

    if not fund_data:
        sys.exit("No holdings fetched — check connectivity and try again.")

    # Pre-filter: find CUSIPs held by ≥ MIN_FUND_COUNT funds at ≥ MIN_WEIGHT_PCT
    # This avoids resolving tickers for thousands of single-fund positions
    from collections import Counter
    cusip_fund_count: Counter = Counter()
    for info in fund_data.values():
        for cusip, h in info["holdings"].items():
            if h["pct"] >= MIN_WEIGHT_PCT:
                cusip_fund_count[cusip] += 1
    overlap_cusips = [c for c, n in cusip_fund_count.items() if n >= MIN_FUND_COUNT]
    print(f"\n  {len(overlap_cusips)} CUSIPs pass overlap filter "
          f"(from {sum(len(i['holdings']) for i in fund_data.values())} total positions)")

    # Resolve tickers only for the overlap set
    print("\nLooking up tickers ...")
    tickers = resolve_tickers(overlap_cusips, cache)
    _save_cache(cache)

    print("\nFetching company metrics ...")
    stock_tickers = [t for t in set(tickers.values()) if t]
    company_metrics = get_company_metrics(stock_tickers, cache)
    _save_cache(cache)

    overlap, fund_names = find_overlap(fund_data, company_metrics, tickers)

    # Drop positions with no public market data (privates, unresolved foreign CUSIPs,
    # money-market funds, etc.) — anything where both market_cap and return_1y are None.
    before = len(overlap)
    overlap = [(cusip, data) for cusip, data in overlap
               if (company_metrics.get(tickers.get(cusip, ""), {}).get("market_cap") is not None
                   or company_metrics.get(tickers.get(cusip, ""), {}).get("return_1y") is not None)]
    excluded = before - len(overlap)
    if excluded:
        print(f"  Excluded {excluded} private/unlisted positions (no market data).")

    overlap_tickers = list({tickers[c] for c, _ in overlap if tickers.get(c)})
    print("\nFetching company details ...")
    company_details = get_company_details(overlap_tickers, cache)
    print("Fetching ETF exposure ...")
    etf_exposure = get_etf_exposure_batch(overlap_tickers, cache)

    print("\nFetching fund performance (3Y/5Y) ...")
    fetch_fund_returns(all_cfg, cache)

    print("\nFetching S&P 500 members ...")
    sp500 = get_sp500_members(cache)

    print("\nComputing position trends ...")
    trends = get_fund_trends(fund_data, all_cfg, cache)

    print("\nComputing aggregate ownership changes (historical EDGAR filings) ...")
    ownership_changes = compute_aggregate_changes(overlap, fund_data, all_cfg, cache)
    _save_cache(cache)

    print("\nFetching annual financials for valuation change ...")
    annual_financials = get_annual_financials(overlap_tickers, cache)
    _save_cache(cache)

    print("\nComputing valuation metrics ...")
    valuation_changes = compute_valuation_changes(
        overlap_tickers, company_details, company_metrics, annual_financials, cache)
    _save_cache(cache)

    print_report(overlap, fund_names, fund_data, all_cfg, tickers, company_metrics)
    save_csv(overlap, fund_names, tickers, company_metrics)
    save_html(overlap, fund_names, fund_data, all_cfg, tickers, company_metrics,
              company_details, etf_exposure, trends, sp500,
              ownership_changes, valuation_changes)


if __name__ == "__main__":
    main()
