#!/usr/bin/env python3
"""Lit le contenu d'un article ZoneBourse.

Le contenu est dans une variable JavaScript `articleBody` (page HTML complète,
pas de rendu JS nécessaire). Les entités HTML sont échappées dans la page
et sont déséchappées ici.
"""

import subprocess, json, re, sys, html as html_lib
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent.resolve()
COOKIES_FILE = SCRIPT_DIR / "cookies.txt"


CURL_ARGS = [
    "curl", "-s",
    "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "-H", "Accept-Language: fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "-H", "Accept-Encoding: gzip, deflate, br",
    "-H", "Connection: keep-alive",
    "-H", "Upgrade-Insecure-Requests: 1",
    "-H", "Sec-Fetch-Dest: document",
    "-H", "Sec-Fetch-Mode: navigate",
    "-H", "Sec-Fetch-Site: none",
    "-H", "Sec-Fetch-User: ?1",
    "-H", "Cache-Control: max-age=0",
    "--compressed",
]


def load_cookies(path: Path) -> str:
    """Construit le header Cookie depuis le fichier.

    Supporte deux formats :
    - Simplifié : une ligne ``key=value`` par cookie
    - Netscape   : ``domain<TAB>flag<TAB>path<TAB>secure<TAB>exp<TAB>name<TAB>value``
    """
    if not path.exists():
        return ""
    cookies = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 7:
                name, value = parts[5], parts[6]
                cookies.append(f"{name}={value}")
        elif "=" in line:
            cookies.append(line)
    return "; ".join(cookies)


def unescape(text: str) -> str:
    """Déséchappe les entités HTML (double-encoded dans le JSON ZoneBourse)."""
    text = text.replace("\\n", "\n")
    text = html_lib.unescape(text)  # 1st pass: &amp;amp; → &amp;
    text = html_lib.unescape(text)  # 2nd pass: &amp; → &
    return text


def detect_paywall(html: str) -> bool:
    """Détecte un paywall via les marqueurs schema.org / HTML.

    Stratégie par ordre de fiabilité :
    1. JSON-LD isAccessibleForFree:false (standard schema.org pour SEO)
    2. JSON-LD hasPart avec cssSelector pointant sur .paywall
    3. Texte « réservé aux abonnés » dans la page
    """
    if re.search(r'"isAccessibleForFree"\s*:\s*false', html, re.IGNORECASE):
        return True
    if re.search(r'"cssSelector"\s*:\s*"[^"]*paywall', html, re.IGNORECASE):
        return True
    if re.search(r'(réservé aux abonnés|réservé à nos abonnés|abonnés uniquement)', html, re.IGNORECASE):
        return True
    return False


def fetch_article(url: str) -> dict:
    """Récupère titre + contenu complet d'un article ZoneBourse."""
    cookie_header = load_cookies(COOKIES_FILE)

    cmd = CURL_ARGS + ["-H", f"Cookie: {cookie_header}", url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    html = result.stdout

    if result.returncode != 0 or len(html) < 200:
        return {"url": url, "titre": None, "contenu": None, "paywall": None, "error": "page inaccessible"}

    if "Access Denied" in html:
        return {"url": url, "titre": None, "contenu": None, "paywall": None, "error": "access_denied"}

    # Titre
    title_match = re.search(r"<title>([^<]+)</title>", html)
    titre = title_match.group(1).replace(" | Zonebourse", "").strip() if title_match else None

    # Date de publication — depuis <meta property="article:published_time">
    date_iso = None
    date_match = re.search(r'<meta property="article:published_time" content="([^"]+)"', html)
    if date_match:
        date_iso = date_match.group(1)[:10]  # "2026-05-18T16:37:52+02:00" → "2026-05-18"

    # Contenu principal — embedded dans articleBody (JSON-LD dans le HTML)
    contenu = None
    article_match = re.search(r'"articleBody":\s*"([^"]+)"', html)
    if article_match:
        contenu = unescape(article_match.group(1))

    # Fallback : og:description (teaser / articles courts sans JSON-LD complet)
    if not contenu:
        og_desc = re.search(r'<meta[^>]+og:description[^>]+content="([^"]+)"', html)
        if og_desc:
            contenu = unescape(og_desc.group(1).strip())

    # Paywall = UNIQUEMENT si marqueurs explicites (isAccessibleForFree:false, "réservé aux abonnés", etc.)
    # Pas d'inférence sur la longueur : un article gratuit peut être court (dépêche broker 1 ligne).
    paywall = detect_paywall(html)

    # Métadonnée schema.org isAccessibleForFree (true/false/absent) — explicite pour le caller
    is_free_match = re.search(r'"isAccessibleForFree"\s*:\s*(true|false)', html, re.IGNORECASE)
    is_free_meta = is_free_match.group(1).lower() == "true" if is_free_match else None

    return {
        "url": url,
        "titre": titre,
        "date": date_iso,
        "contenu": contenu if contenu else None,
        "paywall": paywall,
        "isAccessibleForFree": is_free_meta,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 read_article.py <url>")
        sys.exit(1)

    result = fetch_article(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))