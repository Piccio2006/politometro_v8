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
    """Cerca percentuali per partito nel testo plain della pagina."""
    patterns = {
        "fdi":  r"Fratelli d.Italia[^%\d]{0,60}?(\d{1,2}[,\.]\d)\s*%",
        "pd":   r"Partito Democratico[^%\d]{0,60}?(\d{1,2}[,\.]\d)\s*%",
        "m5s":  r"(?:Movimento 5 Stelle|M5S)[^%\d]{0,60}?(\d{1,2}[,\.]\d)\s*%",
        "lega": r"\bLega\b[^%\d]{0,60}?(\d{1,2}[,\.]\d)\s*%",
        "fi":   r"Forza Italia[^%\d]{0,60}?(\d{1,2}[,\.]\d)\s*%",
        "avs":  r"Alleanza Verdi[^%\d]{0,60}?(\d{1,2}[,\.]\d)\s*%",
    }
    results = {}
    for key, pat in patterns.items():
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            val = parse_pct(m.group(1))
            if val is not None:
                results[key] = val
    return results


def scrape_youtrend():
    """
    1) Trova l'articolo Supermedia più recente su YouTraend
    2) Lo scarica e ne estrae le percentuali
    """
    try:
        # Trova l'URL dell'ultimo articolo Supermedia dalla homepage
        home = requests.get("https://www.youtrend.it/", headers=HEADERS, timeout=15)
        home.raise_for_status()
        soup = BeautifulSoup(home.text, "html.parser")

        # Cerca link che contengono "supermedia" nell'href
        supermedia_url = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "supermedia" in href.lower() and "youtrend" in href.lower():
                if href.startswith("http"):
                    supermedia_url = href
                else:
                    supermedia_url = "https://www.youtrend.it" + href
                break

        if not supermedia_url:
            # Prova la pagina category
            cat = requests.get(
                "https://www.youtrend.it/?s=supermedia", headers=HEADERS, timeout=15
            )
            if cat.status_code == 200:
                soup2 = BeautifulSoup(cat.text, "html.parser")
                for a in soup2.find_all("a", href=True):
                    href = a["href"]
                    if "supermedia" in href.lower():
                        supermedia_url = href if href.startswith("http") else "https://www.youtrend.it" + href
                        break

        if not supermedia_url:
            print("  YouTraend: articolo Supermedia non trovato nella homepage")
            return None, None

        print(f"  YouTraend: articolo trovato → {supermedia_url}")
        article = requests.get(supermedia_url, headers=HEADERS, timeout=15)
        article.raise_for_status()

        # Prima prova a trovare una tabella con dati partiti
        soup_art = BeautifulSoup(article.text, "html.parser")
        results = {}

        for table in soup_art.find_all("table"):
            ttext = table.get_text(" ")
            if "Fratelli" in ttext or "FdI" in ttext:
                # Cerca righe con nome partito e percentuale
                for row in table.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                    if len(cells) < 2:
                        continue
                    name = cells[0].lower()
                    pct_cell = next((c for c in cells[1:] if re.search(r"\d+[,\.]\d", c)), None)
                    if not pct_cell:
                        continue
                    val = parse_pct(re.search(r"(\d+[,\.]\d)", pct_cell).group(1))
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

        # Fallback: cerca nel testo dell'articolo
        if len(results) < 4:
            results = _extract_from_text(soup_art.get_text(" "))

        if len(results) >= 5:
            print(f"  YouTraend OK: trovati {len(results)} partiti")
            return results, "YouTraend/Supermedia"

        print(f"  YouTraend: trovati solo {len(results)} partiti nell'articolo")
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
