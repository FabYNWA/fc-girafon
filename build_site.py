"""
FC Girafon — générateur de site statique.
Lit les CSV exportés de Grist (plus tard : l'API Grist directement) et
produit les pages HTML dans output/.
"""
import re
import unicodedata
import hashlib
from datetime import datetime, date
import pandas as pd
from pathlib import Path

DATA = Path(__file__).parent / "data"
OUT = Path(__file__).parent / "output"

CLUB = "FC GIRAFON"
SEASON = None  # saison en cours de génération (change à chaque passage de la boucle dans main())
SEASONS = []   # toutes les saisons présentes dans les données, la plus récente en premier
CURRENT_SEASON = None  # la plus récente — celle servie à la racine du site

# Chemin de base absolu du site, à ajuster si le dépôt est renommé (ex. "/" si le
# dépôt s'appelle <pseudo>.github.io, ou si un nom de domaine personnalisé est branché)
SITE_BASE = "/fc-girafon/"

# Pages qui existent en une version par saison (archivées dans un sous-dossier
# pour toutes les saisons sauf la plus récente, qui reste à la racine)
SEASON_PAGES = {"index.html", "calendrier.html", "championnat.html",
                 "coupe.html", "statistiques.html"}

def season_slug(season):
    """'2025 / 2026' -> '2025-2026', utilisé comme nom de sous-dossier d'archive."""
    return season.replace(" / ", "-").replace(" ", "")

# Rempli une fois par appel à generate_season() — voir main()
_CTX = {"season_path": ""}  # "" à la racine (saison courante), "2025-2026/" en archive

MOIS_FR = ["janvier","février","mars","avril","mai","juin","juillet","août",
           "septembre","octobre","novembre","décembre"]
JOURS_FR = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]

# ---------------------------------------------------------------------------
# Chargement des données
# ---------------------------------------------------------------------------

def compute_seasons(matchs):
    """Liste de toutes les saisons présentes, la plus récente en premier."""
    seasons = matchs["saison"].dropna().unique().tolist()
    if not seasons:
        return ["2025 / 2026"]
    return sorted(seasons, key=lambda s: int(s.split("/")[0].strip()), reverse=True)

def load():
    matchs = pd.read_csv(DATA / "matchs_2025_2026.csv")
    matchs["date_dt"] = pd.to_datetime(matchs["date"], format="%d/%m/%Y")
    part = pd.read_csv(DATA / "participations_2025_2026.csv")
    effectif = pd.read_csv(DATA / "effectif_template.csv")
    classement = pd.read_csv(DATA / "classement_template.csv")
    annonces = pd.read_csv(DATA / "annonces.csv")
    club_info = pd.read_csv(DATA / "club_info.csv")
    adversaires = pd.read_csv(DATA / "adversaires.csv")
    liens_utiles = pd.read_csv(DATA / "liens_utiles.csv")
    stades = pd.read_csv(DATA / "stades.csv")
    disponibilites = pd.read_csv(DATA / "disponibilites.csv")
    return matchs, part, effectif, classement, annonces, club_info, adversaires, liens_utiles, stades, disponibilites

# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def slugify(name):
    n = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    n = re.sub(r"[^a-zA-Z0-9]+", "-", n).strip("-").lower()
    return n

def date_fr(dt, with_weekday=False):
    if pd.isna(dt):
        return ""
    s = f"{dt.day:02d} {MOIS_FR[dt.month-1][:3]} {dt.year}"
    if with_weekday:
        s = f"{JOURS_FR[dt.weekday()].capitalize()} {dt.day} {MOIS_FR[dt.month-1]} {dt.year}"
    return s

def initials(name):
    return "".join([w[0] for w in str(name).split()][:2]).upper()

def build_color_map(adversaires):
    m = {}
    for _, r in adversaires.iterrows():
        if pd.notna(r.get("couleur")) and str(r["couleur"]).strip():
            m[r["nom"]] = str(r["couleur"]).strip()
    return m

def team_color(name, color_map):
    """Couleur d'équipe : celle renseignée dans Grist, sinon une couleur stable dérivée du nom
    (le même nom donne toujours la même couleur, contrairement à un tirage aléatoire)."""
    if color_map and name in color_map:
        return color_map[name]
    h = int(hashlib.md5(str(name).encode()).hexdigest(), 16)
    hue = h % 360
    return f"hsl({hue}, 55%, 42%)"

def build_stade_map(stades):
    m = {}
    for _, r in stades.iterrows():
        if pd.notna(r.get("latitude")) and pd.notna(r.get("longitude")):
            m[r["nom"]] = (float(r["latitude"]), float(r["longitude"]))
    return m

def maps_links(lieu, stade_map):
    if not lieu or pd.isna(lieu):
        return "", ""
    from urllib.parse import quote
    coord = stade_map.get(lieu) if stade_map else None
    if coord:
        lat, lon = coord
        maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        waze_url = f"https://waze.com/ul?ll={lat},{lon}&navigate=yes"
    else:
        q = quote(lieu)
        maps_url = f"https://www.google.com/maps/search/?api=1&query={q}"
        waze_url = f"https://waze.com/ul?q={q}&navigate=yes"
    return maps_url, waze_url

COMPETITION_TIERS = {"Bronze": "#B5651D", "Argent": "#9A9A9A", "Or": "#D9A521",
                      "Brassages": "#6B6B6B", "Départementale": "#2E5FA3"}

def competition_badge(competition):
    if not competition or pd.isna(competition):
        return ""
    tier_color = None
    for tier, color in COMPETITION_TIERS.items():
        if tier in competition:
            tier_color = color
            break
    if not tier_color:
        return ""
    shape = "comp-badge-round" if competition.startswith("Championnat") else "comp-badge-diamond"
    return f'<span class="comp-badge {shape}" style="background:{tier_color};"></span>'

def competition_watermark(competition):
    if not competition or pd.isna(competition):
        return ""
    tier_color = None
    for tier, color in COMPETITION_TIERS.items():
        if tier in competition:
            tier_color = color
            break
    if not tier_color:
        return ""
    label = "CHAMPIONNAT" if competition.startswith("Championnat") else "COUPE"
    return f'<div class="card-watermark" style="color:{tier_color};">{label}</div>'

def build_numero_map(effectif):
    m = {}
    for _, p in effectif.iterrows():
        if pd.notna(p.get("numero")):
            m[p["nom"]] = int(p["numero"])
    return m

def avatar_label(name, numero_map):
    """Affiche le numéro de maillot dans les ronds d'avatar ; initiales en repli si inconnu."""
    if numero_map and name in numero_map:
        return str(numero_map[name])
    return initials(name)

def fmt_stat_unit(value, key):
    value = int(value)
    if key == "buts":
        return f"{value} but" + ("s" if value != 1 else "")
    if key == "passes":
        return f"{value} passe d." if value == 1 else f"{value} passes d."
    return str(value)

def compute_age(date_naissance_str):
    if pd.isna(date_naissance_str) or not str(date_naissance_str).strip():
        return None
    try:
        d = datetime.strptime(str(date_naissance_str).strip(), "%d/%m/%Y").date()
    except ValueError:
        return None
    today = date.today()
    age = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    return age

def dense_ranks(rows, key):
    """Classement avec gestion des ex-aequo : deux valeurs égales partagent le même rang."""
    ranks = []
    prev_val, prev_rank = None, 0
    for i, r in enumerate(rows):
        if r[key] == prev_val:
            rank = prev_rank
        else:
            rank = i + 1
        ranks.append(rank)
        prev_val, prev_rank = r[key], rank
    return ranks

def medal_html(rank):
    if rank in (1, 2, 3):
        return f'<span class="medal medal-{rank}">{rank}</span>'
    return f'<span class="rank-plain">{rank}</span>'

# ---------------------------------------------------------------------------
# Forme récente (V/N/D des derniers matchs)
# ---------------------------------------------------------------------------

def matchs_comptabilises(matchs):
    """Matchs joués qui comptent pour les stats (exclut les matchs amicaux, qui restent visibles
    au calendrier mais ne doivent influencer ni les stats collectives ni individuelles)."""
    joue = matchs["statut"] == "Joué"
    pas_amical = ~matchs["competition"].fillna("").str.startswith("Amical")
    return matchs[joue & pas_amical]

# ---------------------------------------------------------------------------
# Forme récente (V/N/D des derniers matchs)
# ---------------------------------------------------------------------------

def compute_forme(matchs, n=5):
    joues = matchs_comptabilises(matchs).sort_values("date_dt")
    last = joues.tail(n)
    forme = []
    for _, r in last.iterrows():
        rc = result_class(r)
        forme.append({"result-v": "V", "result-n": "N", "result-d": "D"}.get(rc, "?"))
    return forme

def forme_html(forme):
    if not forme:
        return ""
    dots = "".join(f'<span class="forme-dot forme-{f.lower()}">{f}</span>' for f in forme)
    return f'<div class="forme-strip">{dots}</div>'

# ---------------------------------------------------------------------------
# Top du mois (buteurs / passeurs)
# ---------------------------------------------------------------------------

def compute_top_mois(matchs, part, effectif, key):
    joues = matchs_comptabilises(matchs).dropna(subset=["date_dt"])
    merged = part.merge(joues[["id", "date_dt"]], left_on="match_id", right_on="id", how="inner")
    if len(merged) == 0:
        return None, []
    merged["mois"] = merged["date_dt"].dt.to_period("M")
    candidates = merged[merged[key] > 0]
    if len(candidates) == 0:
        return None, []
    dernier_mois = candidates["mois"].max()
    scope = merged[merged["mois"] == dernier_mois]
    scope = scope[scope["joueur"].notna()]
    agg = scope.groupby("joueur")[key].sum().sort_values(ascending=False)
    top3 = [{"nom": nom, "valeur": int(v)} for nom, v in agg.head(3).items() if v > 0]
    mois_label = f"{MOIS_FR[dernier_mois.month-1].capitalize()} {dernier_mois.year}"
    return mois_label, top3

def mini_podium_html(title, mois_label, top3, accent, numero_map):
    if not top3:
        return f"""
        <div class="mini-podium">
          <div class="mini-podium-head {accent}-head">{title}</div>
          <div class="empty-state">Aucune donnée pour le moment.</div>
        </div>"""
    key = "buts" if accent == "buts" else "passes"
    rows = "".join(f"""
        <div class="mini-podium-row rank-tint-{i+1}">
          {medal_html(i+1)}
          <div class="lb-avatar">{avatar_label(p['nom'], numero_map)}</div>
          <div class="lb-name">{p['nom']}</div>
          <div class="mini-podium-value">{fmt_stat_unit(p['valeur'], key)}</div>
        </div>""" for i, p in enumerate(top3))
    return f"""
    <div class="mini-podium">
      <div class="mini-podium-head {accent}-head">{title} <span class="mini-podium-month">{mois_label}</span></div>
      {rows}
    </div>"""

# ---------------------------------------------------------------------------
# Podium visuel (saison entière, top 3)
# ---------------------------------------------------------------------------

def podium_visual_html(data, key, accent, numero_map):
    top3 = sorted(data, key=lambda d: -d[key])[:3]
    top3 = [p for p in top3 if p[key] > 0]
    if len(top3) < 3:
        return ""
    order = [1, 0, 2]
    heights = {0: 130, 1: 100, 2: 80}
    blocks = []
    for pos in order:
        p = top3[pos]
        blocks.append(f"""
        <div class="podium-block">
          <div class="podium-avatar">{avatar_label(p['nom'], numero_map)}</div>
          <div class="podium-name">{p['nom']}</div>
          <div class="podium-value">{p[key]}</div>
          <div class="podium-stand {accent}-bg" style="height:{heights[pos]}px;">{pos+1}</div>
        </div>""")
    return f'<div class="podium">{"".join(blocks)}</div>'

# ---------------------------------------------------------------------------
# Layout commun
# ---------------------------------------------------------------------------

NAV_ITEMS = [
    ("index.html", "Accueil"),
    ("club.html", "Club"),
    ("calendrier.html", "Calendrier"),
    ("championnat.html", "Championnat"),
    ("coupe.html", "Coupe"),
    ("confrontations.html", "Confrontations"),
    ("effectif.html", "Effectif"),
    ("statistiques.html", "Statistiques"),
    ("disponibilites.html", "Disponibilités"),
]

# Rempli une fois par main() puis utilisé par chaque appel à layout()
_STICKY_HTML = {"value": ""}
_LIENS_HTML = {"value": ""}

def build_liens_footer(liens_utiles):
    liens = [
        f'<a href="{r["url"]}" target="_blank" rel="noopener">{r["titre"]}</a>'
        for _, r in liens_utiles.iterrows() if pd.notna(r.get("url")) and str(r["url"]).strip()
    ]
    if not liens:
        return ""
    return f'<div class="footer-liens"><strong>LIENS UTILES</strong> | {" ; ".join(liens)}</div>'

def build_sticky(matchs):
    joues = matchs_comptabilises(matchs).sort_values("date_dt")
    programmes = matchs[matchs["statut"] == "Programmé"].sort_values("date_dt")
    if len(programmes) > 0:
        r = programmes.iloc[0]
        label = "Prochain match"
        opp = r["adversaire"]
        badge = ""
        detail = f'{CLUB} vs {opp} — {date_fr(r["date_dt"])} {r["heure"]}'
    elif len(joues) > 0:
        r = joues.iloc[-1]
        label = "Dernier résultat"
        opp = r["adversaire"]
        rclass = result_class(r)
        letter = {"result-v": "V", "result-n": "N", "result-d": "D"}.get(rclass, "")
        badge = f'<span class="sticky-badge {rclass}">{letter}</span>' if letter else ""
        detail = f'{CLUB} {int(r["score_girafon"])} - {int(r["score_adversaire"])} {opp}'
    else:
        return ""
    return f"""
    <div class="sticky-bar">
      <div class="container sticky-bar-inner">
        <span class="sticky-label">{label}</span>
        {badge}
        <span class="sticky-detail">{detail}</span>
      </div>
    </div>"""

def page_href(page_name):
    """URL absolue d'une page : dans le sous-dossier d'archive pour les pages
    'saison' d'une saison passée, à la racine sinon."""
    if page_name in SEASON_PAGES:
        return f"{SITE_BASE}{_CTX['season_path']}{page_name}"
    return f"{SITE_BASE}{page_name}"

def asset_href(path):
    """URL absolue d'un fichier statique (assets/...) — toujours la même,
    quel que soit le sous-dossier dans lequel la page courante est générée."""
    return f"{SITE_BASE}{path}"

def season_select_html(active_page):
    """Un vrai sélecteur : chaque option pointe vers l'URL réelle de la page
    équivalente dans l'autre saison (ou vers son accueil si la page n'existe
    pas en version archivée)."""
    target_page = active_page if active_page in SEASON_PAGES else "index.html"
    options = []
    for s in SEASONS:
        slug_path = "" if s == CURRENT_SEASON else season_slug(s) + "/"
        url = f"{SITE_BASE}{slug_path}{target_page}"
        selected = "selected" if s == SEASON else ""
        options.append(f'<option value="{url}" {selected}>Saison {s}</option>')
    return f"""<div class="season-select">
      <select onchange="window.location.href=this.value">{''.join(options)}</select>
    </div>"""

def layout(title, active, body):
    nav_html = "\n".join(
        f'<a href="{page_href(href)}" class="{"active" if href == active else ""}">{label}</a>'
        for href, label in NAV_ITEMS
    )
    sticky = "" if active == "index.html" and not _CTX["season_path"] else _STICKY_HTML["value"]
    logo = asset_href("assets/logo.png")
    style = asset_href("assets/style.css")
    home_href = f"{SITE_BASE}index.html"
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — {CLUB}</title>
<link rel="icon" type="image/png" href="{logo}">
<meta property="og:title" content="{title} — {CLUB}">
<meta property="og:description" content="{CLUB} — FSGT IDF — 94 — résultats, calendrier, effectif et statistiques.">
<meta property="og:image" content="{logo}">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{title} — {CLUB}">
<meta name="twitter:image" content="{logo}">
<link rel="stylesheet" href="{style}">
</head>
<body>
<div class="topbar">
  <div class="topbar-inner">
    <a href="{home_href}" class="brand">
      <img src="{logo}" alt="Blason {CLUB}">
      <div class="brand-name">{CLUB}</div>
    </a>
    <nav class="mainnav">{nav_html}</nav>
    {season_select_html(active)}
    <button class="burger" onclick="toggleMobileNav()" aria-label="Menu">
      <span></span><span></span><span></span>
    </button>
  </div>
  <nav class="mobilenav" id="mobilenav">{nav_html}</nav>
</div>
{sticky}
{body}
<footer>
  <div class="container">
    {CLUB} — FSGT IDF — 94
    {_LIENS_HTML["value"]}
  </div>
</footer>
<script>
function toggleMobileNav(){{
  document.getElementById('mobilenav').classList.toggle('open');
}}
function openModal(id){{
  var m = document.getElementById(id);
  if(m) m.classList.add('open');
  document.body.style.overflow = 'hidden';
}}
function closeModal(id){{
  var m = document.getElementById(id);
  if(m) m.classList.remove('open');
  document.body.style.overflow = '';
}}
document.addEventListener('keydown', function(e){{
  if(e.key === 'Escape'){{
    document.querySelectorAll('.match-modal.open').forEach(function(m){{ m.classList.remove('open'); }});
    document.body.style.overflow = '';
  }}
}});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Cards de match
# ---------------------------------------------------------------------------

def result_class(row):
    if row["statut"] != "Joué":
        return "result-a"
    if row["score_girafon"] > row["score_adversaire"]:
        return "result-v"
    if row["score_girafon"] < row["score_adversaire"]:
        return "result-d"
    return "result-n"

def build_participation_summary(part, all_names=None):
    """Résumé buteurs/passeurs/présents/absents par match, pour affichage sur les cards."""
    all_names = set(all_names or [])
    summary = {}
    for match_id, grp in part.groupby("match_id"):
        def fmt(col):
            items = []
            for _, r in grp[grp[col] > 0].sort_values(col, ascending=False).iterrows():
                nom = r["joueur"] if pd.notna(r["joueur"]) else r["joueur_invite"]
                n = int(r[col])
                items.append(f"{nom}" + (f" x{n}" if n > 1 else ""))
            return ", ".join(items)
        presents = []
        for _, r in grp.iterrows():
            nom = r["joueur"] if pd.notna(r["joueur"]) else r["joueur_invite"]
            if nom:
                presents.append(nom)
        absents = sorted(all_names - set(presents))
        summary[match_id] = {
            "buteurs": fmt("buts"), "passeurs": fmt("passes"),
            "presents": ", ".join(presents), "absents": ", ".join(absents),
        }
    return summary

def off_card(row):
    """Carte simplifiée pour les journées sans match (vacances, annulé)."""
    label = {"Vacances": "Trêve", "Annulé": "Match annulé"}.get(row["statut"], row["statut"])
    return f"""
    <div class="match-card result-a off-card">
      <div class="match-card-head"><span class="match-card-comp">{label}</span></div>
      <div class="match-card-body" style="justify-content:center;">
        <span class="status-chip">{date_fr(row['date_dt'])}</span>
      </div>
    </div>"""

RESULT_LABEL = {"result-v": "Victoire", "result-n": "Match nul", "result-d": "Défaite"}

def build_match_modal(modal_id, row, home, away, score_html, result_label, rclass, date_str, heure, lieu, phase, info, color_map, stade_map=None):
    def chip_list(s, cls):
        return "".join(f'<span class="chip {cls}">{n}</span>' for n in s.split(", ") if n)

    sections = []
    if info and info["presents"]:
        sections.append(f'<div class="modal-section"><div class="modal-section-head mj-head">Présents</div><div class="chip-row">{chip_list(info["presents"], "chip-present")}</div></div>')
    if info and info["buteurs"]:
        sections.append(f'<div class="modal-section"><div class="modal-section-head buts-head"><span class="stat-marker buts"></span>Buteurs</div><div class="chip-row">{chip_list(info["buteurs"], "chip-stat")}</div></div>')
    if info and info["passeurs"]:
        sections.append(f'<div class="modal-section"><div class="modal-section-head passes-head"><span class="stat-marker passes"></span>Passeurs</div><div class="chip-row">{chip_list(info["passeurs"], "chip-stat")}</div></div>')
    if info and info["absents"]:
        sections.append(f'<div class="modal-section"><div class="modal-section-head" style="background:#3a3a3a;">Absents</div><div class="chip-row">{chip_list(info["absents"], "chip-absent")}</div></div>')

    home_is_girafon = home == CLUB
    def badge(name, is_girafon):
        if is_girafon:
            return f'<div class="modal-badge girafon"><img src="{asset_href("assets/logo.png")}" alt="{name}"></div>'
        color = team_color(name, color_map)
        return f'<div class="modal-badge" style="background:{color};color:#fff;">{name[:3].upper()}</div>'

    maps_url, waze_url = maps_links(lieu, stade_map)
    directions_html = ""
    if maps_url:
        directions_html = f"""
        <div class="modal-directions">
          <a href="{maps_url}" target="_blank" rel="noopener" class="direction-btn">Google Maps</a>
          <a href="{waze_url}" target="_blank" rel="noopener" class="direction-btn">Waze</a>
        </div>"""

    return f"""
    <div class="match-modal" id="{modal_id}" onclick="if(event.target===this) closeModal('{modal_id}')">
      <div class="match-modal-content">
        <div class="modal-topband {rclass}">
          <span>{competition_badge(row['competition'])} {phase}</span>
          <button class="modal-close" onclick="closeModal('{modal_id}')" aria-label="Fermer">&times;</button>
        </div>
        <div class="modal-body">
          <div class="modal-teams">
            <div class="modal-team-col">{badge(home, home_is_girafon)}<div class="modal-team">{home}</div></div>
            <div class="modal-score-wrap">{f'<div class="result-label {rclass}">{result_label}</div>' if result_label else ''}<div class="modal-score">{score_html}</div></div>
            <div class="modal-team-col">{badge(away, not home_is_girafon)}<div class="modal-team">{away}</div></div>
          </div>
          <div class="modal-meta">{date_str}{' — ' + heure if heure else ''} · {lieu}</div>
          <div class="modal-sections">{''.join(sections) if sections else '<div class="empty-state">Aucun détail enregistré pour ce match.</div>'}</div>
          {directions_html}
        </div>
      </div>
    </div>"""

def match_card(row, part_summary=None, color_map=None, stade_map=None):
    if row["statut"] in ("Vacances", "Annulé") or pd.isna(row.get("adversaire")):
        return off_card(row), ""

    ha_badge = f'<span class="ha-badge {"dom" if row["domicile_exterieur"]=="Domicile" else "ext"}">{"DOM" if row["domicile_exterieur"]=="Domicile" else "EXT"}</span>'
    home = CLUB if row["domicile_exterieur"] == "Domicile" else row["adversaire"]
    away = row["adversaire"] if row["domicile_exterieur"] == "Domicile" else CLUB
    rclass = result_class(row)

    result_label = ""
    if row["statut"] == "Joué":
        hs = row["score_girafon"] if row["domicile_exterieur"] == "Domicile" else row["score_adversaire"]
        as_ = row["score_adversaire"] if row["domicile_exterieur"] == "Domicile" else row["score_girafon"]
        score_html = f"{int(hs)} - {int(as_)}"
        result_label = RESULT_LABEL.get(rclass, "")
        label_html = f'<div class="result-label {rclass}">{result_label}</div>' if result_label else ""
    elif row["statut"] == "Programmé":
        score_html = '<span class="pending">à venir</span>'
        label_html = ""
    else:
        score_html = f'<span class="pending">{row["statut"]}</span>'
        label_html = ""

    date_str = date_fr(row["date_dt"])
    phase = row["phase"] if pd.notna(row.get("phase")) else ""
    lieu = row["lieu"] if pd.notna(row.get("lieu")) else ""
    heure = row["heure"] if pd.notna(row.get("heure")) else ""

    info = None
    lineup_html = ""
    modal_id = f"modal-{row['id']}"
    if part_summary and row["id"] in part_summary:
        info = part_summary[row["id"]]
        lines = []
        if info["buteurs"]:
            lines.append(f'<div class="match-card-line"><span class="stat-marker buts"></span>Buts : {info["buteurs"]}</div>')
        if info["passeurs"]:
            lines.append(f'<div class="match-card-line"><span class="stat-marker passes"></span>Passes D. : {info["passeurs"]}</div>')
        if info["presents"]:
            lines.append(f'<div class="match-card-roster">Effectif : {info["presents"]}</div>')
        if lines:
            lineup_html = f'<div class="match-card-lineup">{"".join(lines)}</div>'

    comp_label = row['competition'] if pd.notna(row['competition']) else 'Trêve'
    modal_html = build_match_modal(modal_id, row, home, away, score_html, result_label, rclass,
                                    date_str, heure, lieu, f"{phase}", info, color_map, stade_map)

    click_attr = f' onclick="openModal(\'{modal_id}\')"' if modal_html else ""
    card_cls = "match-card clickable" if modal_html else "match-card"

    def team_cell(name, extra_cls):
        if name == CLUB:
            return f'<div class="match-card-team girafon-cell {extra_cls}"><img class="girafon-watermark" src="{asset_href("assets/logo.png")}" alt="">{name}</div>'
        return f'<div class="match-card-team {extra_cls}">{name}</div>'

    card_html = f"""
    <div class="{card_cls} {rclass}"{click_attr}>
      {competition_watermark(row['competition'])}
      <div class="match-card-head">
        <span class="match-card-comp">{competition_badge(row['competition'])}{row['competition'] if pd.notna(row['competition']) else 'Trêve'}</span>
        <span>{phase} {ha_badge}</span>
      </div>
      <div class="match-card-body">
        {team_cell(home, "home")}
        <div class="match-card-score-wrap">
          {label_html}
          <div class="match-card-score">{score_html}</div>
        </div>
        {team_cell(away, "")}
      </div>
      {lineup_html}
      <div class="match-card-foot">
        <span>{date_str}{' — ' + heure if heure else ''}</span>
        <span>{lieu}</span>
      </div>
      {'<div class="match-card-toggle">Voir la fiche complète</div>' if modal_html else ''}
    </div>"""
    return card_html, modal_html

def match_grid(rows, part_summary=None, color_map=None, stade_map=None):
    if len(rows) == 0:
        return '<div class="empty-state">Aucun match pour le moment.</div>'
    cards, modals = [], []
    for _, r in rows.iterrows():
        c, m = match_card(r, part_summary, color_map, stade_map)
        cards.append(c)
        if m:
            modals.append(m)
    return f'<div class="match-grid">{"".join(cards)}</div>{"".join(modals)}'

# ---------------------------------------------------------------------------
# Page Accueil
# ---------------------------------------------------------------------------

def render_index(matchs, part, annonces, effectif, color_map, stade_map):
    part_summary = build_participation_summary(part, effectif['nom'].tolist())
    joues = matchs_comptabilises(matchs).sort_values("date_dt")
    programmes = matchs[matchs["statut"] == "Programmé"].sort_values("date_dt")

    if len(programmes) > 0:
        hero_row = programmes.iloc[0]
        hero_label = "Prochain match"
    else:
        hero_row = joues.iloc[-1]
        hero_label = "Dernier résultat"

    home = CLUB if hero_row["domicile_exterieur"] == "Domicile" else hero_row["adversaire"]
    away = hero_row["adversaire"] if hero_row["domicile_exterieur"] == "Domicile" else CLUB
    home_is_girafon = hero_row["domicile_exterieur"] == "Domicile"

    if hero_row["statut"] == "Joué":
        hs = hero_row["score_girafon"] if home_is_girafon else hero_row["score_adversaire"]
        as_ = hero_row["score_adversaire"] if home_is_girafon else hero_row["score_girafon"]
        center = f'<div class="matchup-vs">{int(hs)} - {int(as_)}</div>'
    else:
        center = '<div class="matchup-vs">VS</div>'

    date_str = date_fr(hero_row["date_dt"], with_weekday=True)
    meta = f'<span>{date_str}</span><span>{hero_row["heure"]}</span><span>{hero_row["lieu"]}</span>'

    def badge(name, is_girafon):
        if is_girafon:
            return '<div class="crest-badge girafon"><img src="{}" alt="{}"></div>'.format(asset_href('assets/logo.png'), name)
        color = team_color(name, color_map)
        return f'<div class="crest-badge" style="background:{color};color:#fff;">{name[:3].upper()}</div>'

    forme = compute_forme(matchs)

    hero_html = f"""
    <div class="hero">
      <div class="container">
        <div class="hero-label">{hero_label.upper()} — {hero_row['competition']}</div>
        <div class="matchup">
          <div class="matchup-side home">
            {badge(home, home_is_girafon)}
            <div class="matchup-name">{home}</div>
          </div>
          <div class="matchup-center">
            {center}
            <div class="matchup-meta">{meta}</div>
          </div>
          <div class="matchup-side away">
            {badge(away, not home_is_girafon)}
            <div class="matchup-name">{away}</div>
          </div>
        </div>
        {forme_html(forme)}
      </div>
      <div class="hero-notch"></div>
    </div>"""

    if len(annonces) == 0:
        annonces_html = '<div class="empty-state">Aucune annonce publiée pour le moment.</div>'
    else:
        annonces_html = "\n".join(
            f"""<div class="announce">
                  <div class="announce-date">{r['date_publication']}</div>
                  <div class="announce-title">{r['titre']}</div>
                  <div class="announce-text">{r['texte']}</div>
                </div>"""
            for _, r in annonces.sort_values("date_publication", ascending=False).iterrows()
        )

    recents = joues.sort_values("date_dt", ascending=False).head(3)

    numero_map = build_numero_map(effectif)
    indiv = compute_individuelles(matchs, part, effectif)
    mois_buts, top_buts = compute_top_mois(matchs, part, effectif, "buts")
    mois_passes, top_passes = compute_top_mois(matchs, part, effectif, "passes")

    body = hero_html + f"""
    <div class="section">
      <div class="container">
        <div class="section-head"><h2>Annonces</h2></div>
        {annonces_html}
      </div>
    </div>
    <div class="section alt">
      <div class="container">
        <div class="section-head"><h2>Derniers résultats</h2>
          <a class="count" href="{page_href('calendrier.html')}">Voir tout le calendrier →</a>
        </div>
        {match_grid(recents, part_summary, color_map, stade_map)}
      </div>
    </div>
    <div class="section">
      <div class="container">
        <div class="section-head"><h2>Top du mois</h2></div>
        <div class="stat-cols-2">
          {mini_podium_html("Buteurs", mois_buts, top_buts, "buts", numero_map)}
          {mini_podium_html("Passeurs", mois_passes, top_passes, "passes", numero_map)}
        </div>
      </div>
    </div>"""
    return layout("Accueil", "index.html", body)

# ---------------------------------------------------------------------------
# Page Club
# ---------------------------------------------------------------------------

def render_club(club_info, stades):
    info = club_info.iloc[0] if len(club_info) > 0 else {}

    def field(name, empty_msg):
        val = info.get(name) if hasattr(info, "get") else None
        if val is not None and pd.notna(val) and str(val).strip():
            html_val = str(val).replace("\r\n", "\n").replace("\n", "<br>")
            return f'<p class="club-histoire-text">{html_val}</p>'
        return f'<div class="empty-state">{empty_msg}</div>'

    histoire_html = field("histoire", "L'histoire du club n'a pas encore été renseignée.")
    historique_html = field("historique", "Aucun historique renseigné pour le moment.")

    terrain = info.get("terrain_principal") if hasattr(info, "get") else None
    jour = info.get("jour_match_habituel") if hasattr(info, "get") else None
    infos = []
    if pd.notna(jour) and str(jour).strip():
        infos.append(("Jour de match habituel", jour))
    if pd.notna(terrain) and str(terrain).strip():
        infos.append(("Terrain principal", terrain))

    infos_html = "".join(
        f'<div class="info-card"><div class="info-card-label">{label}</div><div class="info-card-value">{value}</div></div>'
        for label, value in infos
    ) or '<div class="empty-state">Aucune info pratique renseignée pour le moment.</div>'

    stades_html = "".join(
        f'<div class="info-card"><div class="info-card-label">{r["nom"]}</div>'
        f'<a class="info-card-value" style="font-size:13px;" href="https://www.google.com/maps/search/?api=1&query={r["latitude"]},{r["longitude"]}" target="_blank" rel="noopener">Voir sur la carte</a></div>'
        for _, r in stades.iterrows() if pd.notna(r.get("latitude")) and pd.notna(r.get("longitude"))
    ) or '<div class="empty-state">Aucun stade renseigné pour le moment.</div>'

    body = f"""
    <div class="section">
      <div class="container">
        <div class="club-hero">
          <img src="{asset_href("assets/logo.png")}" alt="Blason {CLUB}" class="club-crest">
          <div>
            <h1 class="club-title">{CLUB}</h1>
            <div class="club-sub">FSGT IDF — 94</div>
          </div>
        </div>

        <div class="section-head" style="margin-top:32px;"><h2>Histoire</h2></div>
        {histoire_html}

        <div class="section-head" style="margin-top:32px;"><h2>Historique</h2></div>
        {historique_html}

        <div class="section-head" style="margin-top:32px;"><h2>Infos pratiques</h2></div>
        <div class="info-card-grid">{infos_html}</div>

        <div class="section-head" style="margin-top:32px;"><h2>Stades</h2></div>
        <div class="info-card-grid">{stades_html}</div>
      </div>
    </div>"""
    return layout("Club", "club.html", body)

# ---------------------------------------------------------------------------
# Page Calendrier
# ---------------------------------------------------------------------------

def render_calendrier(matchs, part, effectif, color_map, stade_map):
    part_summary = build_participation_summary(part, effectif['nom'].tolist())
    ordered = matchs.sort_values("date_dt")
    body = f"""
    <div class="section">
      <div class="container">
        <div class="section-head">
          <h2>Résultats &amp; calendrier — saison {SEASON}</h2>
          <span class="count">{len(ordered)} rencontres</span>
        </div>
        <p class="hint-text">Clique sur un match pour voir ses détails.</p>
        {match_grid(ordered, part_summary, color_map, stade_map)}
      </div>
    </div>"""
    return layout("Résultats & calendrier", "calendrier.html", body)

# ---------------------------------------------------------------------------
# Page Championnat (sous-onglets Championnat 1 / Championnat 2)
# ---------------------------------------------------------------------------

def classement_table(classement, championnat_label):
    rows = classement[classement["championnat"] == championnat_label] if "championnat" in classement.columns else classement.iloc[0:0]
    if len(rows) == 0:
        return '<div class="empty-state">Aucun classement pour le moment — sera mis à jour après la première journée.</div>'
    trs = []
    for _, r in rows.sort_values("classement").iterrows():
        self_cls = "self-team" if str(r["equipe"]).strip().upper() == CLUB.upper() else ""
        trs.append(f"""<tr class="{self_cls}">
          <td class="num">{int(r['classement'])}</td>
          <td>{r['equipe']}</td>
          <td class="num">{r['matchs_joues']}</td>
          <td class="num">{r['points']}</td>
          <td class="num">{r['diff_buts']:+d}</td>
          <td class="num">{r['victoires']}</td>
          <td class="num">{r['nuls']}</td>
          <td class="num">{r['defaites']}</td>
          <td class="num">{r['forfaits']}</td>
          <td class="num">{r['buts_pour']}</td>
          <td class="num">{r['buts_contre']}</td>
          <td class="num">{r['unites_administratives']}</td>
        </tr>""")
    return f"""<table class="data classement-table">
      <thead><tr>
        <th class="num">#</th><th>Équipe</th><th class="num">MJ</th><th class="num">Pts</th><th class="num">Diff.</th>
        <th class="num">V</th><th class="num">N</th><th class="num">D</th><th class="num">F</th>
        <th class="num">BP</th><th class="num">BC</th><th class="num">U.A.</th>
      </tr></thead>
      <tbody>{''.join(trs)}</tbody>
    </table>"""

def render_championnat(matchs, classement, part, effectif, color_map, stade_map):
    part_summary = build_participation_summary(part, effectif['nom'].tolist())

    competitions = sorted(
        matchs[matchs["competition"].str.startswith("Championnat", na=False)]["competition"].dropna().unique().tolist()
    )

    if not competitions:
        body = f"""
        <div class="section">
          <div class="container">
            <div class="section-head"><h2>Championnat</h2></div>
            <div class="empty-state">Les championnats de cette saison n'ont pas encore été déterminés.</div>
          </div>
        </div>"""
        return layout("Championnat", "championnat.html", body)

    tabs_html = "".join(
        f'<button class="{"active" if i == 0 else ""}" onclick="showSub(\'c{i}\')">{comp.replace(" | ", " — ")}</button>'
        for i, comp in enumerate(competitions)
    )
    panels_html = "".join(f"""
        <div id="c{i}" class="subpanel {'active' if i == 0 else ''}">
          <div class="section-head"><h2>Classement</h2></div>
          {classement_table(classement, comp)}
          <div class="section-head" style="margin-top:32px;"><h2>Résultats &amp; calendrier</h2></div>
          {match_grid(matchs[matchs["competition"] == comp].sort_values("date_dt"), part_summary, color_map, stade_map)}
        </div>""" for i, comp in enumerate(competitions))

    body = f"""
    <div class="section">
      <div class="container">
        <div class="subtabs">{tabs_html}</div>
        <p class="hint-text">Clique sur un match pour voir ses détails.</p>
        {panels_html}
      </div>
    </div>
    <script>
    function showSub(id){{
      document.querySelectorAll('.subpanel').forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.subtabs button').forEach(b => b.classList.remove('active'));
      document.getElementById(id).classList.add('active');
      event.target.classList.add('active');
    }}
    </script>"""
    return layout("Championnat", "championnat.html", body)

# ---------------------------------------------------------------------------
# Page Coupe
# ---------------------------------------------------------------------------

def render_coupe(matchs, part, effectif, color_map, stade_map):
    part_summary = build_participation_summary(part, effectif['nom'].tolist())
    coupe = matchs[matchs["competition"].str.startswith("Coupe", na=False)].sort_values("date_dt")
    body = f"""
    <div class="section">
      <div class="container">
        <div class="section-head">
          <h2>Coupe</h2>
          <span class="count">{len(coupe)} rencontres</span>
        </div>
        <p class="hint-text">Clique sur un match pour voir ses détails.</p>
        {match_grid(coupe, part_summary, color_map, stade_map)}
      </div>
    </div>"""
    return layout("Coupe", "coupe.html", body)

# ---------------------------------------------------------------------------
# Page Effectif + fiches joueurs
# ---------------------------------------------------------------------------

def player_card(p, linked=True, show_phrase=False):
    numero_bg = f'<span class="player-number-bg">#{int(p["numero"])}</span>' if pd.notna(p.get("numero")) else ""
    postes = [x.strip() for x in str(p["poste"]).split(",")] if pd.notna(p.get("poste")) else []
    postes_html = " ".join(f'<span class="poste-chip">{poste}</span>' for poste in postes)
    phrase = ""
    if show_phrase and pd.notna(p.get("phrase")) and str(p["phrase"]).strip():
        phrase = f'<div class="player-phrase">{p["phrase"]}</div>'
    age_html = ""
    age = compute_age(p.get("date_naissance"))
    if age is not None:
        age_html = f'<div class="player-age">{age} ans</div>'
    flocage = f'<div class="player-flocage">{p["flocage"]}</div>' if pd.notna(p.get("flocage")) else ""

    has_photo = pd.notna(p.get("photo_url")) and str(p.get("photo_url")).strip()
    if has_photo:
        photo_inner = f'<img class="player-photo-img" src="{asset_href(p["photo_url"])}" alt="{p["nom"]}">{numero_bg}'
    else:
        photo_inner = f'{numero_bg}<span class="player-initials">{initials(p["nom"])}</span>'

    inner = f"""
        <div class="player-photo">{photo_inner}</div>
        <div class="player-name">{p['nom']}</div>
        {flocage}
        <div class="player-postes">{postes_html}</div>
        {age_html}
        {phrase}"""
    if linked:
        player_page_name = f"joueur-{slugify(p['nom'])}.html"
        return f'<a class="player-card" href="{page_href(player_page_name)}">{inner}</a>'
    return f'<div class="player-card">{inner}</div>'

# ---------------------------------------------------------------------------
# Page Confrontations
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Page Disponibilités
# ---------------------------------------------------------------------------

# À remplacer par l'URL du formulaire Grist une fois publié (Grist > icône Partager > Formulaire).
GRIST_FORM_URL = "https://docs.getgrist.com/forms/b75z7NDjzzYgMkzT8BGu4k/31"

def render_disponibilites(matchs, effectif, disponibilites):
    if GRIST_FORM_URL:
        content = f'<iframe src="{GRIST_FORM_URL}" class="grist-form-frame" title="Formulaire de disponibilité"></iframe>'
    else:
        content = """
        <div class="empty-state">
          Le formulaire n'est pas encore configuré — une fois publié dans Grist
          (icône Partager → Formulaire), colle son URL dans la constante
          <code>GRIST_FORM_URL</code> en haut du script de génération.
        </div>"""

    programmes = matchs[matchs["statut"] == "Programmé"].sort_values("date_dt")
    reponses_html = '<div class="empty-state">Aucun match à venir programmé pour le moment.</div>'

    if len(programmes) > 0:
        prochain = programmes.iloc[0]
        match_date_str = date_fr(prochain["date_dt"])
        date_formatee = pd.to_datetime(prochain["date_dt"]).strftime('%d/%m/%Y')
        rows = disponibilites[disponibilites["Match"].str.contains(date_formatee, na=False)] if "Match" in disponibilites.columns else disponibilites.iloc[0:0]

        groups = {"Présent": [], "Absent": [], "Incertain": []}
        repondants = set()
        for _, r in rows.iterrows():
            rep = r.get("reponse")
            nom = r.get("joueur")
            if pd.notna(rep) and pd.notna(nom) and rep in groups:
                groups[rep].append(nom)
                repondants.add(nom)

        sans_reponse = [n for n in effectif["nom"].tolist() if n not in repondants]

        DISPO_CLASS = {"Présent": "dispo-present", "Absent": "dispo-absent", "Incertain": "dispo-incertain"}
        cols = "".join(f"""
        <div class="dispo-col">
          <div class="dispo-col-head {DISPO_CLASS.get(key, '')}">{key} <span>({len(names)})</span></div>
          <div class="chip-row">{"".join(f'<span class="chip chip-present">{n}</span>' for n in names) or '<span class="empty-inline">—</span>'}</div>
        </div>""" for key, names in groups.items())

        cols += f"""
        <div class="dispo-col">
          <div class="dispo-col-head" style="background:#6b6b6b;">Sans réponse <span>({len(sans_reponse)})</span></div>
          <div class="chip-row">{"".join(f'<span class="chip chip-absent">{n}</span>' for n in sans_reponse) or '<span class="empty-inline">—</span>'}</div>
        </div>"""

        reponses_html = f"""
        <div class="section-head" style="margin-top:36px;"><h2>Réponses pour le {match_date_str} vs {prochain['adversaire']}</h2></div>
        <div class="dispo-grid">{cols}</div>"""

    body = f"""
    <div class="section">
      <div class="container">
        <div class="section-head"><h2>Disponibilités</h2></div>
        <p style="color:var(--grey);font-size:14px;margin-bottom:20px;">
          Indique si tu seras présent au prochain match — ça prend 10 secondes. Les réponses sont actualisées 3 x par jour (pas en temps réel).
        </p>
        {content}
        {reponses_html}
      </div>
    </div>"""
    return layout("Disponibilités", "disponibilites.html", body)

def render_confrontations(matchs, color_map):
    joues = matchs[matchs["statut"] == "Joué"].dropna(subset=["adversaire"])
    cards = []
    for adv, grp in sorted(joues.groupby("adversaire"), key=lambda kv: kv[0]):
        grp = grp.sort_values("date_dt", ascending=False)
        v = (grp["score_girafon"] > grp["score_adversaire"]).sum()
        d = (grp["score_girafon"] < grp["score_adversaire"]).sum()
        n = len(grp) - v - d
        bp = int(grp["score_girafon"].sum())
        bc = int(grp["score_adversaire"].sum())
        color = team_color(adv, color_map)

        rows_html = "".join(f"""
        <tr>
          <td class="confront-date">{date_fr(r['date_dt'])}</td>
          <td>{r['competition']}</td>
          <td class="num confront-score"><span class="result-letter {result_class(r)}">{ {"result-v":"V","result-n":"N","result-d":"D"}.get(result_class(r), "") }</span>{int(r['score_girafon'])} - {int(r['score_adversaire'])}</td>
        </tr>""" for _, r in grp.iterrows())

        cards.append(f"""
        <div class="confront-card">
          <div class="confront-head" style="border-left-color:{color};">
            <span class="confront-swatch" style="background:{color};"></span>
            <span class="confront-name">{adv}</span>
            <span class="confront-record">{v}V {n}N {d}D · {bp}-{bc}</span>
          </div>
          <table class="data">
            <tbody>{rows_html}</tbody>
          </table>
        </div>""")

    body = f"""
    <div class="section">
      <div class="container">
        <div class="section-head">
          <h2>Confrontations</h2>
          <span class="count">{len(cards)} adversaires rencontrés</span>
        </div>
        <div class="confront-grid">{''.join(cards) if cards else '<div class="empty-state">Aucun match joué pour le moment.</div>'}</div>
      </div>
    </div>"""
    return layout("Confrontations", "confrontations.html", body)

def render_effectif(effectif, matchs):
    cards = "".join(player_card(p) for _, p in effectif.iterrows())
    body = f"""
    <div class="section">
      <div class="container">
        <div class="section-head">
          <h2>Effectif</h2>
          <span class="count">{len(effectif)} joueurs</span>
        </div>
        <p class="hint-text">Clique sur un joueur pour voir son historique détaillé.</p>
        <div class="roster-grid">{cards}</div>
      </div>
    </div>"""
    return layout("Effectif", "effectif.html", body)

def render_player_page(p, matchs, part):
    nom = p["nom"]
    joues_ids = set(matchs_comptabilises(matchs)["id"])
    mine = part[(part["joueur"] == nom) & (part["match_id"].isin(joues_ids))]
    mine_ok = mine[mine["comptabilise"] == True]

    nb_matchs = len(mine_ok)
    nb_buts = int(mine["buts"].sum())
    nb_passes = int(mine["passes"].sum())

    history_rows = mine.merge(matchs, left_on="match_id", right_on="id").sort_values("date_dt", ascending=False)

    def match_row_html(r):
        opp = r["adversaire"]
        home_is = r["domicile_exterieur"] == "Domicile"
        hs = r["score_girafon"] if home_is else r["score_adversaire"]
        as_ = r["score_adversaire"] if home_is else r["score_girafon"]
        rclass = result_class(r)
        rlabel = RESULT_LABEL.get(rclass, "")
        result_tag = f'<span class="result-label {rclass}" style="margin-bottom:0;">{rlabel}</span>' if rlabel else ""
        stat_bits = []
        if r["buts"] > 0:
            stat_bits.append(fmt_stat_unit(r["buts"], "buts"))
        if r["passes"] > 0:
            stat_bits.append(fmt_stat_unit(r["passes"], "passes"))
        stat_txt = ", ".join(stat_bits) if stat_bits else "—"
        return f"""
        <tr>
          <td>{date_fr(r['date_dt'])}</td>
          <td>{r['competition']}</td>
          <td>vs {opp}</td>
          <td class="num">{result_tag} {int(hs)} - {int(as_)}</td>
          <td>{stat_txt}</td>
        </tr>"""

    def history_table_html(rows):
        body_rows = "".join(match_row_html(r) for _, r in rows.iterrows())
        if not body_rows:
            return '<div class="empty-state">Aucun match enregistré pour ce joueur.</div>'
        return f"""<table class="data">
          <thead><tr><th>Date</th><th>Compétition</th><th>Match</th><th class="num">Résultat</th><th>Perf.</th></tr></thead>
          <tbody>{body_rows}</tbody>
        </table>"""

    # --- Onglet Carrière : totaux + historique complet, toutes saisons ---
    carriere_html = f"""
    <div class="stat-highlight stat-highlight-3col">
      <div class="stat-big"><span class="stat-big-num">{nb_matchs}</span><span class="stat-big-label">Matchs joués</span></div>
      <div class="stat-big"><span class="stat-big-num">{nb_buts}</span><span class="stat-big-label">Buts</span></div>
      <div class="stat-big"><span class="stat-big-num">{nb_passes}</span><span class="stat-big-label">Passes D.</span></div>
    </div>
    <div class="section-head" style="margin-top:28px;"><h2>Historique des matchs</h2></div>
    {history_table_html(history_rows)}"""

    # --- Onglet Par saison : un bloc de stats + un historique par saison ---
    saisons_html = ""
    for s in sorted(history_rows["saison"].dropna().unique().tolist(),
                     key=lambda x: int(x.split("/")[0].strip()), reverse=True):
        rows_s = history_rows[history_rows["saison"] == s]
        ids_s = set(rows_s["id"])
        mine_ok_s = mine_ok[mine_ok["match_id"].isin(ids_s)]
        buts_s = int(mine[mine["match_id"].isin(ids_s)]["buts"].sum())
        passes_s = int(mine[mine["match_id"].isin(ids_s)]["passes"].sum())
        saisons_html += f"""
        <div class="section-head" style="margin-top:28px;"><h3 style="font-family:var(--font-display);font-size:16px;">Saison {s}</h3></div>
        <div class="stat-highlight stat-highlight-3col" style="margin-bottom:16px;">
          <div class="stat-big"><span class="stat-big-num">{len(mine_ok_s)}</span><span class="stat-big-label">Matchs joués</span></div>
          <div class="stat-big"><span class="stat-big-num">{buts_s}</span><span class="stat-big-label">Buts</span></div>
          <div class="stat-big"><span class="stat-big-num">{passes_s}</span><span class="stat-big-label">Passes D.</span></div>
        </div>
        {history_table_html(rows_s)}"""
    if not saisons_html:
        saisons_html = '<div class="empty-state">Aucun match enregistré pour ce joueur.</div>'

    card_html = player_card(p, linked=False, show_phrase=True)

    body = f"""
    <div class="section">
      <div class="container">
        <a href="{page_href('effectif.html')}" class="count">&larr; Retour à l'effectif</a>
        <div class="player-page-grid" style="margin-top:16px;">
          <div>{card_html}</div>
          <div>
            <div class="subtabs">
              <button class="active" onclick="showSub('carriere')">Carrière</button>
              <button onclick="showSub('parsaison')">Par saison</button>
            </div>
            <div id="carriere" class="subpanel active">{carriere_html}</div>
            <div id="parsaison" class="subpanel">{saisons_html}</div>
          </div>
        </div>
      </div>
    </div>
    <script>
    function showSub(id){{
      document.querySelectorAll('.subpanel').forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.subtabs button').forEach(b => b.classList.remove('active'));
      document.getElementById(id).classList.add('active');
      event.target.classList.add('active');
    }}
    </script>"""
    return layout(nom, "effectif.html", body)

# ---------------------------------------------------------------------------
# Page Statistiques
# ---------------------------------------------------------------------------

def compute_collectives(matchs):
    joues = matchs_comptabilises(matchs)

    def stats(df):
        n = len(df)
        v = (df["score_girafon"] > df["score_adversaire"]).sum()
        d = (df["score_girafon"] < df["score_adversaire"]).sum()
        nul = n - v - d
        bp = df["score_girafon"].sum()
        bc = df["score_adversaire"].sum()
        return dict(matchs=n, v=v, n=nul, d=d,
                    pct=round(v/n*100) if n else 0,
                    pctn=round(nul/n*100) if n else 0,
                    pctd=round(d/n*100) if n else 0,
                    bp=int(bp), bc=int(bc), diff=int(bp-bc),
                    diffm=round((bp-bc)/n,2) if n else 0,
                    bpm=round(bp/n,1) if n else 0,
                    bcm=round(bc/n,1) if n else 0)

    groups = [
        ("Total", joues),
        ("Championnat", joues[joues["competition"].str.startswith("Championnat", na=False)]),
        ("Coupe", joues[joues["competition"].str.startswith("Coupe", na=False)]),
    ]
    championnats_reels = sorted(
        joues[joues["competition"].str.startswith("Championnat", na=False)]["competition"].dropna().unique().tolist()
    )
    for comp in championnats_reels:
        groups.append((f"— {comp}", joues[joues["competition"] == comp]))
    return [(label, stats(df)) for label, df in groups]

def compute_individuelles(matchs, part, effectif):
    joues_ids = set(matchs_comptabilises(matchs)["id"])
    p = part[part["match_id"].isin(joues_ids)].copy()
    p_ok = p[p["comptabilise"] == True]

    matchs_joues = p_ok[p_ok["joueur"].notna()].groupby("joueur").size()
    buts = p.groupby("joueur")["buts"].sum()
    passes = p.groupby("joueur")["passes"].sum()

    noms = effectif["nom"].tolist()
    data = []
    for nom in noms:
        data.append(dict(
            nom=nom,
            matchs=int(matchs_joues.get(nom, 0)),
            buts=int(buts.get(nom, 0)),
            passes=int(passes.get(nom, 0)),
        ))
    return data

def leaderboard(data, key, label, accent, numero_map):
    """Classement façon site pro : barres proportionnelles, numéro de maillot en avatar, égalités gérées, top 3 mis en valeur."""
    rows = sorted(data, key=lambda d: -d[key])
    ranks = dense_ranks(rows, key)
    maxval = max((r[key] for r in rows), default=0) or 1
    items = []
    for r, rank in zip(rows, ranks):
        top_cls = f"top-{rank}" if rank <= 3 else ""
        items.append(f"""
        <div class="lb-row {top_cls}">
          <div class="lb-rank">{medal_html(rank)}</div>
          <div class="lb-avatar">{avatar_label(r['nom'], numero_map)}</div>
          <div class="lb-name">{r['nom']}</div>
          <div class="lb-bar-track"><div class="lb-bar {accent}-bar" style="width:{round(r[key]/maxval*100)}%"></div></div>
          <div class="lb-value">{r[key]}</div>
        </div>""")
    return f"""
    <div class="leaderboard">
      <div class="leaderboard-head {accent}-head">{label}</div>
      <div class="leaderboard-body">{''.join(items)}</div>
    </div>"""

def competition_card(label, s):
    return f"""
    <div class="comp-card">
      <div class="comp-card-head">{label}</div>
      <div class="comp-card-record">{s['v']}<span>V</span> {s['n']}<span>N</span> {s['d']}<span>D</span></div>
      <div class="comp-card-grid">
        <div><span class="cc-num">{s['matchs']}</span><span class="cc-label">Matchs</span></div>
        <div><span class="cc-num">{s['pct']}%</span><span class="cc-label">%V</span></div>
        <div><span class="cc-num">{s['pctd']}%</span><span class="cc-label">%D</span></div>
        <div><span class="cc-num">{'+' if s['diff']>=0 else ''}{s['diff']}</span><span class="cc-label">Diff.</span></div>
        <div><span class="cc-num">{s['bp']}</span><span class="cc-label">Buts +</span></div>
        <div><span class="cc-num">{s['bc']}</span><span class="cc-label">Buts −</span></div>
        <div><span class="cc-num">{s['bpm']}</span><span class="cc-label">Buts +/m</span></div>
        <div><span class="cc-num">{s['bcm']}</span><span class="cc-label">Buts −/m</span></div>
      </div>
    </div>"""

def render_statistiques(matchs, part, effectif):
    coll = dict(compute_collectives(matchs))
    numero_map = build_numero_map(effectif)

    t = coll["Total"]
    highlight = f"""
    <div class="stat-hero">
      <span class="stat-hero-num">{t['matchs']}</span>
      <span class="stat-hero-label">Matchs joués</span>
    </div>
    <div class="stat-highlight">
      <div class="stat-big"><span class="stat-big-num">{t['v']}</span><span class="stat-big-label">Victoires</span><span class="stat-big-sub">{t['pct']}%</span></div>
      <div class="stat-big"><span class="stat-big-num">{t['n']}</span><span class="stat-big-label">Nuls</span><span class="stat-big-sub">{t['pctn']}%</span></div>
      <div class="stat-big"><span class="stat-big-num">{t['d']}</span><span class="stat-big-label">Défaites</span><span class="stat-big-sub">{t['pctd']}%</span></div>
      <div class="stat-big"><span class="stat-big-num">{'+' if t['diff']>=0 else ''}{t['diff']}</span><span class="stat-big-label">Différence de buts</span></div>
      <div class="stat-big"><span class="stat-big-num">{t['bp']}</span><span class="stat-big-label">Buts marqués</span><span class="stat-big-sub">{t['bpm']}/match</span></div>
      <div class="stat-big"><span class="stat-big-num">{t['bc']}</span><span class="stat-big-label">Buts encaissés</span><span class="stat-big-sub">{t['bcm']}/match</span></div>
    </div>"""

    comp_cards = "".join(
        competition_card(label, s) for label, s in coll.items() if label != "Total"
    )

    indiv = compute_individuelles(matchs, part, effectif)

    podium_buts = podium_visual_html(indiv, "buts", "buts", numero_map)
    podium_passes = podium_visual_html(indiv, "passes", "passes", numero_map)

    podium_section = ""
    if podium_buts or podium_passes:
        podium_section = '<div class="stat-cols-2" style="margin-bottom:20px;">'
        if podium_buts:
            podium_section += f'<div><h3 class="podium-title">Top buteurs</h3>{podium_buts}</div>'
        if podium_passes:
            podium_section += f'<div><h3 class="podium-title">Top passeurs</h3>{podium_passes}</div>'
        podium_section += '</div>'

    body = f"""
    <div class="section">
      <div class="container">
        {highlight}

        <div class="section-head" style="margin-top:8px;"><h2>Par compétition</h2></div>
        <div class="comp-card-grid-outer">{comp_cards}</div>

        <div class="section-head" style="margin-top:36px;"><h2>Statistiques individuelles</h2></div>

        {podium_section}

        <div class="stat-cols">
          {leaderboard(indiv, 'matchs', 'Matchs joués', 'mj', numero_map)}
          {leaderboard(indiv, 'buts', 'Buteurs', 'buts', numero_map)}
          {leaderboard(indiv, 'passes', 'Passeurs', 'passes', numero_map)}
        </div>
      </div>
    </div>"""
    return layout("Statistiques", "statistiques.html", body)

# ---------------------------------------------------------------------------
# Génération
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Génération
# ---------------------------------------------------------------------------

def generate_season_pages(matchs_all, part, effectif, classement_all, annonces, color_map, stade_map):
    """Génère les 6 pages 'saison' pour la saison actuellement pointée par SEASON/_CTX,
    dans le bon dossier (racine pour la saison courante, sous-dossier sinon)."""
    matchs = matchs_all[matchs_all["saison"] == SEASON].reset_index(drop=True)
    classement = classement_all[classement_all["saison"] == SEASON].reset_index(drop=True)

    pages = {
        "index.html": render_index(matchs, part, annonces, effectif, color_map, stade_map),
        "calendrier.html": render_calendrier(matchs, part, effectif, color_map, stade_map),
        "championnat.html": render_championnat(matchs, classement, part, effectif, color_map, stade_map),
        "coupe.html": render_coupe(matchs, part, effectif, color_map, stade_map),
        "statistiques.html": render_statistiques(matchs, part, effectif),
    }

    folder = OUT / _CTX["season_path"] if _CTX["season_path"] else OUT
    folder.mkdir(parents=True, exist_ok=True)
    for name, html in pages.items():
        (folder / name).write_text(html, encoding="utf-8")
    return len(pages)

def main():
    global SEASON, SEASONS, CURRENT_SEASON
    matchs_all, part, effectif, classement_all, annonces, club_info, adversaires, liens_utiles, stades, disponibilites = load()

    SEASONS = compute_seasons(matchs_all)
    CURRENT_SEASON = SEASONS[0]
    color_map = build_color_map(adversaires)
    stade_map = build_stade_map(stades)

    # Le bandeau sticky et les liens de pied de page reflètent toujours la saison
    # courante, sur TOUTES les pages, y compris quand on navigue dans une archive
    matchs_current = matchs_all[matchs_all["saison"] == CURRENT_SEASON].reset_index(drop=True)
    _STICKY_HTML["value"] = build_sticky(matchs_current)
    _LIENS_HTML["value"] = build_liens_footer(liens_utiles)

    OUT.mkdir(parents=True, exist_ok=True)
    total_pages = 0

    # Une passe par saison : la plus récente à la racine, les autres archivées
    # dans un sous-dossier (ex. 2025-2026/) — voir SITE_BASE / season_slug()
    for s in SEASONS:
        SEASON = s
        _CTX["season_path"] = "" if s == CURRENT_SEASON else season_slug(s) + "/"
        total_pages += generate_season_pages(matchs_all, part, effectif, classement_all,
                                              annonces, color_map, stade_map)

    # Pages hors saison : une seule version, toujours à la racine, reflète
    # l'effectif et les informations actuelles du club (pas d'archive par saison)
    SEASON = CURRENT_SEASON
    _CTX["season_path"] = ""
    (OUT / "club.html").write_text(render_club(club_info, stades), encoding="utf-8")
    (OUT / "disponibilites.html").write_text(
        render_disponibilites(matchs_current, effectif, disponibilites), encoding="utf-8")
    (OUT / "effectif.html").write_text(render_effectif(effectif, matchs_current), encoding="utf-8")
    (OUT / "confrontations.html").write_text(
        render_confrontations(matchs_all, color_map), encoding="utf-8")
    for _, p in effectif.iterrows():
        (OUT / f"joueur-{slugify(p['nom'])}.html").write_text(
            render_player_page(p, matchs_all, part), encoding="utf-8")
    total_pages += 4 + len(effectif)

    print(f"Site généré : {total_pages} pages sur {len(SEASONS)} saison(s) — {SEASONS}")

if __name__ == "__main__":
    main()
