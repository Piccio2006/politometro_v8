#!/usr/bin/env python3
"""
Scarica le ultime percentuali dei partiti italiani da YouTraend (Supermedia)
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
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9",
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


def _extract_from_text(text):
    """Cerca percentuali per partito nel testo plain della pagina.
    Gestisce formati: '28,2%', 'al 28,2', 'al 28,2%', '28,2 per cento'.
    """
    PCT = r"(?:al\s+)?(\d{1,2}[,\.]\d+)(?:\s*%|\s+per\s+cento)?"
    patterns = {
        "fdi":  rf"(?:Fratelli d.Italia|FdI)[^%\d]{{0,80}}?{PCT}",
        "pd":   rf"(?:Partito Democratico|\bPD\b)[^%\d]{{0,80}}?{PCT}",
        "m5s":  rf"(?:Movimento 5 Stelle|M5S|Cinque Stelle)[^%\d]{{0,80}}?{PCT}",
        "lega": rf"\bLega\b[^%\d]{{0,80}}?{PCT}",
        "fi":   rf"(?:Forza Italia|\bFI\b)[^%\d]{{0,80}}?{PCT}",
        "avs":  rf"(?:Alleanza Verdi[^%\d]{{0,10}}Sinistra|AVS)[^%\d]{{0,80}}?{PCT}",
    }
    results = {}
    for key, pat in patterns.items():
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            val = parse_pct(m.group(1))
            if val is not None:
                results[key] = val
    return results


def _find_supermedia_article_url():
    """Trova l'URL dell'ultimo articolo Supermedia tramite RSS o ricerca."""
    # 1) RSS feed di YouTraend
    for feed_url in [
        "https://www.youtrend.it/feed/",
        "https://www.youtrend.it/feed/?s=supermedia",
    ]:
        try:
            r = requests.get(feed_url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            # Parse XML manualmente (evita dipendenza da feedparser)
            for link in re.findall(r"<link>(https://www\.youtrend\.it/[^<]+supermedia[^<]+)</link>", r.text, re.IGNORECASE):
                print(f"  YouTraend RSS: articolo trovato → {link}")
                return link
        except Exception as e:
            print(f"  YouTraend RSS errore: {e}")

    # 2) Pagina di ricerca
    try:
        r = requests.get("https://www.youtrend.it/?s=supermedia+agi", headers=HEADERS, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "supermedia" in href.lower() and re.search(r"/\d{4}/\d{2}/\d{2}/", href):
                    print(f"  YouTraend search: articolo trovato → {href}")
                    return href
    except Exception as e:
        print(f"  YouTraend search errore: {e}")

    return None


def scrape_youtrend():
    """Scarica l'ultimo articolo Supermedia YouTraend e ne estrae le percentuali."""
    try:
        url = _find_supermedia_article_url()
        if not url:
            print("  YouTraend: nessun articolo Supermedia trovato")
            return None, None

        article = requests.get(url, headers=HEADERS, timeout=15)
        article.raise_for_status()
        soup_art = BeautifulSoup(article.text, "html.parser")
        results = {}

        # Prova prima le tabelle
        for table in soup_art.find_all("table"):
            ttext = table.get_text(" ")
            if not ("Fratelli" in ttext or "FdI" in ttext):
                continue
            for row in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if len(cells) < 2:
                    continue
                name = cells[0].lower()
                pct_cell = next((c for c in cells[1:] if re.search(r"\d+[,\.]\d", c)), None)
                if not pct_cell:
                    continue
                m = re.search(r"(\d+[,\.]\d)", pct_cell)
                if not m:
                    continue
                val = parse_pct(m.group(1))
                if val is None:
                    continue
                if "fratelli" in name or "fdi" in name:
                    results["fdi"] = val
                elif "democratico" in name or name.strip() == "pd":
                    results["pd"] = val
                elif "movimento" in name or "m5s" in name or "stelle" in name:
                    results["m5s"] = val
                elif "lega" in name:
                    results["lega"] = val
                elif "forza" in name or name.strip() == "fi":
                    results["fi"] = val
                elif "verdi" in name or "alleanza" in name or "avs" in name:
                    results["avs"] = val
            if len(results) >= 4:
                break

        # Fallback: testo libero dell'articolo
        if len(results) < 4:
            results = _extract_from_text(soup_art.get_text(" "))

        if len(results) >= 4:
            print(f"  YouTraend OK: {len(results)} partiti trovati")
            return results, "YouTraend/Supermedia"

        print(f"  YouTraend: solo {len(results)} partiti trovati nell'articolo")
    except Exception as e:
        print(f"  YouTraend non disponibile: {e}")
    return None, None


def scrape_wikipedia_api():
    """Usa la Wikipedia API (JSON) invece della pagina HTML diretta — meno bloccata."""
    page_names = [
        "Sondaggi_sull'intenzione_di_voto_in_Italia",
        "Sondaggi_politici_sulla_XXI_legislatura_italiana",
    ]
    for page in page_names:
        try:
            api_url = (
                "https://it.wikipedia.org/w/api.php"
                f"?action=parse&page={requests.utils.quote(page)}"
                "&prop=text&format=json&disabletoc=1"
            )
            resp = requests.get(api_url, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if "error" in data:
                continue
            html_content = data["parse"]["text"]["*"]
            print(f"  Wikipedia API OK: pagina '{page}'")

            soup = BeautifulSoup(html_content, "html.parser")
            target_parties = {"fratelli", "democratico", "movimento", "lega", "forza", "verdi"}
            best_table = None
            best_hits = 0
            for table in soup.find_all("table"):
                text = table.get_text().lower()
                hits = sum(1 for p in target_parties if p in text)
                if hits > best_hits:
                    best_hits = hits
                    best_table = table

            if best_hits < 4 or best_table is None:
                continue

            # Cerca ultima riga con dati numerici
            rows = best_table.find_all("tr")
            # Prima riga = header
            header_cells = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]

            col_map = {}
            for i, h in enumerate(header_cells):
                if "fratelli" in h or h in ("fdi",):
                    col_map["fdi"] = i
                elif "democratico" in h or h == "pd":
                    col_map["pd"] = i
                elif "movimento" in h or "stelle" in h or h in ("m5s",):
                    col_map["m5s"] = i
                elif "lega" in h:
                    col_map["lega"] = i
                elif "forza" in h or h in ("fi",):
                    col_map["fi"] = i
                elif "verdi" in h or "alleanza" in h or h in ("avs",):
                    col_map["avs"] = i

            if len(col_map) < 4:
                continue

            results = {}
            for row in reversed(rows[1:]):
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

            if results:
                return results, "Wikipedia"

        except Exception as e:
            print(f"  Wikipedia API errore ({page}): {e}")

    return None, None


def compute_altri(data):
    known = sum(data.get(k, 0) for k in ("fdi", "pd", "m5s", "lega", "fi", "avs"))
    return round(max(100.0 - known, 0.0), 1)


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
        print("Tentativo Wikipedia API...")
        data, fonte = scrape_wikipedia_api()

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
    print("Aggiornato: politometro_standalone.html")
    print("\nDone.")


if __name__ == "__main__":
    main()
