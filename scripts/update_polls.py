#!/usr/bin/env python3
"""
Scarica le ultime percentuali dei partiti italiani da YouTraend (fallback: Wikipedia)
e aggiorna SONDAGGI_TRENDS in politometro_standalone.html.
Salva anche data/polls_latest.json come archivio della fetch.

Uso: python scripts/update_polls.py
Esce con codice 1 se lo scraping fallisce (non sovrascrive nulla).
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERRORE: installa le dipendenze con: pip install requests beautifulsoup4")
    sys.exit(1)

ROOT = Path(__file__).parent.parent
POLLS_FILE = ROOT / "data" / "polls_latest.json"
STANDALONE = ROOT / "politometro_standalone.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PolitometroBot/1.0; "
        "+https://piccio2006.github.io/politometro-v6m2)"
    )
}

MESI_IT = {
    1: "Gen", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mag", 6: "Giu",
    7: "Lug", 8: "Ago", 9: "Set", 10: "Ott", 11: "Nov", 12: "Dic",
}


def parse_pct(s):
    s = s.strip().rstrip("%").replace(",", ".")
    try:
        v = float(s)
        return v if 1.0 <= v <= 60.0 else None
    except ValueError:
        return None


def scrape_youtrend():
    """Prova a ricavare percentuali dalla pagina aggregatore YouTraend."""
    try:
        url = "https://youtrend.it/sondaggi-politici-italia/"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        patterns = {
            "fdi":  r"Fratelli d.Italia\D{0,40}?(\d{1,2}[,\.]\d)",
            "pd":   r"Partito Democratico\D{0,40}?(\d{1,2}[,\.]\d)",
            "m5s":  r"Movimento 5 Stelle\D{0,40}?(\d{1,2}[,\.]\d)",
            "lega": r"\bLega\b\D{0,40}?(\d{1,2}[,\.]\d)",
            "fi":   r"Forza Italia\D{0,40}?(\d{1,2}[,\.]\d)",
            "avs":  r"Alleanza Verdi\D{0,40}?(\d{1,2}[,\.]\d)",
        }
        results = {}
        for key, pat in patterns.items():
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = parse_pct(m.group(1))
                if val is not None:
                    results[key] = val

        if len(results) >= 5:
            print(f"  YouTraend OK: trovati {len(results)} partiti")
            return results, "YouTraend"
        print(f"  YouTraend: troppo pochi dati ({len(results)} partiti), provo fallback")
    except Exception as e:
        print(f"  YouTraend non disponibile: {e}")
    return None, None


def _map_header(h):
    h = h.lower().strip()
    if "fratelli" in h or h in ("fdi", "f.d'i.", "f.d'i"):
        return "fdi"
    if "democratico" in h or h in ("pd",):
        return "pd"
    if "movimento" in h or "stelle" in h or h in ("m5s", "5s"):
        return "m5s"
    if "lega" in h:
        return "lega"
    if "forza" in h or h in ("fi", "f.i."):
        return "fi"
    if "verdi" in h or "alleanza" in h or h in ("avs",):
        return "avs"
    return None


def scrape_wikipedia():
    """Scarica la pagina Wikipedia dei sondaggi italiani e legge l'ultima riga dati."""
    url = "https://it.wikipedia.org/wiki/Sondaggi_politici_italiani"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    target_parties = {"fratelli", "democratico", "movimento", "lega", "forza", "verdi"}
    best_table = None
    best_hits = 0

    for table in soup.find_all("table", class_="wikitable"):
        text = table.get_text().lower()
        hits = sum(1 for p in target_parties if p in text)
        if hits > best_hits:
            best_hits = hits
            best_table = table

    if best_hits < 4:
        raise ValueError("Nessuna tabella con abbastanza partiti trovata su Wikipedia")

    # Trova header
    rows = best_table.find_all("tr")
    col_map = {}
    header_row_idx = 0
    for ri, row in enumerate(rows):
        cells = row.find_all(["th"])
        if len(cells) >= 5:
            for ci, cell in enumerate(cells):
                key = _map_header(cell.get_text(strip=True))
                if key:
                    col_map[key] = ci
            if len(col_map) >= 4:
                header_row_idx = ri
                break

    if len(col_map) < 4:
        raise ValueError(f"Troppo poche colonne mappate: {col_map}")

    print(f"  Wikipedia: colonne trovate: {col_map}")

    # Leggi ultima riga con valori numerici validi
    results = {}
    for row in reversed(rows[header_row_idx + 1:]):
        cells = row.find_all(["td", "th"])
        if len(cells) < max(col_map.values()) + 1:
            continue
        candidate = {}
        for key, idx in col_map.items():
            val = parse_pct(cells[idx].get_text(strip=True))
            if val is not None:
                candidate[key] = val
        if len(candidate) >= 4:
            results = candidate
            break

    if not results:
        raise ValueError("Nessuna riga dati valida trovata")

    return results, "Wikipedia"


def compute_altri(data):
    known = sum(data.get(k, 0) for k in ("fdi", "pd", "m5s", "lega", "fi", "avs"))
    altri = round(100.0 - known, 1)
    return max(altri, 0.0)


def load_previous():
    if POLLS_FILE.exists():
        return json.loads(POLLS_FILE.read_text(encoding="utf-8"))
    return None


def main():
    print("=== update_polls.py ===")
    today = date.today()
    month_str = f"{MESI_IT[today.month]} {today.year}"
    print(f"Mese corrente: {month_str}")

    # Scraping
    data, fonte = scrape_youtrend()
    if data is None:
        print("Tentativo Wikipedia...")
        data, fonte = scrape_wikipedia()

    if data is None:
        print("ERRORE: nessuna fonte disponibile. Nessun file modificato.")
        sys.exit(1)

    data["altri"] = compute_altri(data)
    print(f"  Fonte: {fonte}")
    print(f"  Dati: {data}")

    # Confronto con precedente
    prev = load_previous()
    if prev:
        prev_p = prev.get("partiti", {})
        print("\nVariazioni rispetto al mese precedente:")
        for k in ("fdi", "pd", "m5s", "lega", "fi", "avs"):
            old = prev_p.get(k.upper(), prev_p.get(k))
            new = data.get(k)
            if old is not None and new is not None:
                diff = round(new - old, 1)
                arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "=")
                print(f"  {k.upper():5s}: {old:.1f}% → {new:.1f}% ({arrow}{abs(diff):.1f})")

    # Salva polls_latest.json
    polls_out = {
        "data_aggiornamento": today.isoformat(),
        "fonte": fonte,
        "mese": month_str,
        "partiti": {k.upper(): v for k, v in data.items() if k != "altri"},
    }
    POLLS_FILE.write_text(json.dumps(polls_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSalvato: {POLLS_FILE.relative_to(ROOT)}")

    # Aggiorna politometro_standalone.html
    html = STANDALONE.read_text(encoding="utf-8")

    # Formatta nuova entry
    new_entry = (
        f'      {{ month: "{month_str}", '
        f'fdi: {data["fdi"]}, pd: {data["pd"]}, m5s: {data["m5s"]}, '
        f'lega: {data["lega"]}, fi: {data["fi"]}, avs: {data["avs"]}, altri: {data["altri"]} }}'
    )

    start_marker = "const SONDAGGI_TRENDS = ["
    end_marker = "\n    ];"

    start_idx = html.index(start_marker)
    end_idx = html.index(end_marker, start_idx)
    trends_block = html[start_idx:end_idx]

    # Se il mese corrente esiste già → sostituisci; altrimenti aggiungi
    month_pattern = re.compile(
        r'\{ month: "' + re.escape(month_str) + r'"[^}]+\}'
    )
    if month_pattern.search(trends_block):
        html = html[:start_idx] + month_pattern.sub(new_entry.strip(), trends_block) + html[end_idx:]
        print(f"Aggiornata voce esistente per {month_str}")
    else:
        html = html[:end_idx] + f",\n{new_entry}" + html[end_idx:]
        print(f"Aggiunta nuova voce per {month_str}")

    STANDALONE.write_text(html, encoding="utf-8")
    print(f"Aggiornato: politometro_standalone.html")
    print("\nDone.")


if __name__ == "__main__":
    main()
