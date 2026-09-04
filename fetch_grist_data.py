"""
FC Girafon — récupère les données depuis l'API Grist et les écrit dans data/
au même format que les CSV utilisés pour les tests, afin que build_site.py
n'ait besoin d'aucune modification.

Variables d'environnement requises (à définir en secrets GitHub Actions) :
  GRIST_API_KEY   — clé API personnelle Grist (Profil > Paramètres > API)
  GRIST_DOC_ID    — identifiant du document, visible dans son URL
                    (https://docs.getgrist.com/<DOC_ID>/...)
  GRIST_SERVER    — optionnel, par défaut https://docs.getgrist.com
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

API_KEY = os.environ["GRIST_API_KEY"]
DOC_ID = os.environ["GRIST_DOC_ID"]
SERVER = os.environ.get("GRIST_SERVER", "https://docs.getgrist.com")

HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def fetch_table(table_id):
    """Renvoie la liste des lignes d'une table Grist, sous forme de dicts
    {id: ..., <ColonneGrist>: valeur, ...} — valeurs brutes, non converties."""
    url = f"{SERVER}/api/docs/{DOC_ID}/tables/{table_id}/records"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    records = resp.json()["records"]
    rows = []
    for r in records:
        row = {"id": r["id"]}
        row.update(r["fields"])
        rows.append(row)
    return rows


def unlist(value):
    """Grist encode les colonnes de type liste (Choice List, Reference List,
    pièces jointes) sous la forme ['L', v1, v2, ...]. On enlève ce marqueur."""
    if isinstance(value, list) and len(value) > 0 and value[0] == "L":
        return value[1:]
    if isinstance(value, list):
        return value
    return []


def grist_date_to_str(unix_seconds):
    """Convertit un timestamp Grist (secondes depuis epoch, UTC) en DD/MM/YYYY,
    le format attendu partout dans build_site.py."""
    if unix_seconds is None or unix_seconds == "" or pd.isna(unix_seconds):
        return ""
    d = datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
    return d.strftime("%d/%m/%Y")


def main():
    print("Récupération des tables Grist...")

    effectif_raw = fetch_table("Effectif")
    matchs_raw = fetch_table("Matchs")
    participations_raw = fetch_table("Participations")
    classement_raw = fetch_table("Classement")
    annonces_raw = fetch_table("Annonces")
    club_info_raw = fetch_table("Club_Info")
    adversaires_raw = fetch_table("Adversaires")
    liens_utiles_raw = fetch_table("Liens_Utiles")
    stades_raw = fetch_table("Stades")
    prochains_raw = fetch_table("Prochains_Matchs")
    try:
        disponibilites_raw = fetch_table("Disponibilites")
    except requests.HTTPError:
        disponibilites_raw = []

    # Table de correspondance id Effectif -> Nom, pour résoudre les références
    nom_par_id = {r["id"]: r.get("Nom", "") for r in effectif_raw}
    # Table de correspondance id Matchs -> Date (str), pour Prochains_Matchs/Disponibilites
    date_match_par_id = {r["id"]: grist_date_to_str(r.get("Date")) for r in matchs_raw}
    # Table de correspondance id Prochains_Matchs -> Date (str)
    date_prochain_par_id = {r["id"]: grist_date_to_str(r.get("Date")) for r in prochains_raw}

    # -----------------------------------------------------------------
    # Effectif — les photos sont des pièces jointes Grist, téléchargées
    # à part et déposées dans fetched_assets/photos/ (voir deploy.yml)
    # -----------------------------------------------------------------
    import mimetypes
    PHOTOS_DIR = Path(__file__).parent / "fetched_assets" / "photos"
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    def download_photo(attachment_id, slug):
        url = f"{SERVER}/api/docs/{DOC_ID}/attachments/{attachment_id}/download"
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        ext = mimetypes.guess_extension(resp.headers.get("Content-Type", "").split(";")[0]) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        filename = f"{slug}{ext}"
        (PHOTOS_DIR / filename).write_bytes(resp.content)
        return f"assets/photos/{filename}"

    effectif_out = []
    for r in effectif_raw:
        nom = r.get("Nom", "")
        slug = "".join(c.lower() if c.isalnum() else "-" for c in nom).strip("-")
        photo_ids = unlist(r.get("Photo"))
        photo_url = ""
        if photo_ids:
            try:
                photo_url = download_photo(photo_ids[0], slug)
            except requests.HTTPError as e:
                print(f"  ! Photo de {nom} non récupérée : {e}", file=sys.stderr)
        effectif_out.append({
            "nom": nom,
            "photo_url": photo_url,
            "poste": ", ".join(unlist(r.get("Poste"))),
            "numero": r.get("Numero"),
            "flocage": r.get("Flocage", ""),
            "phrase": r.get("Phrase", ""),
            "date_naissance": grist_date_to_str(r.get("Date_Naissance")),
        })
    pd.DataFrame(effectif_out).to_csv(DATA_DIR / "effectif_template.csv", index=False)

    # -----------------------------------------------------------------
    # Matchs
    # -----------------------------------------------------------------
    matchs_out = []
    for r in matchs_raw:
        matchs_out.append({
            "id": r["id"],
            "date": grist_date_to_str(r.get("Date")),
            "saison": r.get("Saison", ""),
            "competition": r.get("Competition", ""),
            "phase": r.get("Phase", ""),
            "domicile_exterieur": r.get("Domicile_Exterieur", ""),
            "adversaire": r.get("Adversaire", ""),
            "score_girafon": r.get("Score_Girafon"),
            "score_adversaire": r.get("Score_Adversaire"),
            "lieu": r.get("Lieu", ""),
            "heure": r.get("Heure", ""),
            "statut": r.get("Statut", ""),
        })
    pd.DataFrame(matchs_out).to_csv(DATA_DIR / "matchs_2025_2026.csv", index=False)

    # -----------------------------------------------------------------
    # Participations
    # -----------------------------------------------------------------
    part_out = []
    for r in participations_raw:
        match_id = r.get("Match")
        joueur_id = r.get("Joueur")
        part_out.append({
            "match_id": match_id,
            "match_date": date_match_par_id.get(match_id, ""),
            "joueur": nom_par_id.get(joueur_id, "") if joueur_id else "",
            "joueur_invite": r.get("Joueur_Invite", ""),
            "buts": r.get("Buts", 0) or 0,
            "passes": r.get("Passes", 0) or 0,
            "comptabilise": bool(r.get("Comptabilise", True)),
        })
    pd.DataFrame(part_out).to_csv(DATA_DIR / "participations_2025_2026.csv", index=False)

    # -----------------------------------------------------------------
    # Classement
    # -----------------------------------------------------------------
    classement_out = []
    for r in classement_raw:
        classement_out.append({
            "saison": r.get("Saison", ""),
            "championnat": r.get("Championnat", ""),
            "classement": r.get("Classement"),
            "equipe": r.get("Equipe", ""),
            "points": r.get("Points"),
            "matchs_joues": r.get("Matchs_Joues"),
            "victoires": r.get("Victoires"),
            "nuls": r.get("Nuls"),
            "defaites": r.get("Defaites"),
            "forfaits": r.get("Forfaits"),
            "buts_pour": r.get("Buts_Pour"),
            "buts_contre": r.get("Buts_Contre"),
            "diff_buts": r.get("Diff_Buts"),
            "unites_administratives": r.get("Unites_Administratives"),
        })
    pd.DataFrame(classement_out).to_csv(DATA_DIR / "classement_template.csv", index=False)

    # -----------------------------------------------------------------
    # Annonces
    # -----------------------------------------------------------------
    annonces_out = []
    for r in annonces_raw:
        annonces_out.append({
            "titre": r.get("Titre", ""),
            "texte": r.get("Texte", ""),
            "date_publication": grist_date_to_str(r.get("Date_Publication")),
            "date_expiration": grist_date_to_str(r.get("Date_Expiration")),
        })
    pd.DataFrame(annonces_out, columns=["titre", "texte", "date_publication", "date_expiration"]).to_csv(
        DATA_DIR / "annonces.csv", index=False)

    # -----------------------------------------------------------------
    # Club_Info (une seule ligne attendue)
    # -----------------------------------------------------------------
    club_info_out = []
    for r in club_info_raw:
        club_info_out.append({
            "histoire": r.get("Histoire", ""),
            "historique": r.get("Historique", ""),
            "terrain_principal": r.get("Terrain_Principal", ""),
            "jour_match_habituel": r.get("Jour_Match_Habituel", ""),
        })
    pd.DataFrame(club_info_out, columns=["histoire", "historique", "terrain_principal", "jour_match_habituel"]).to_csv(
        DATA_DIR / "club_info.csv", index=False)

    # -----------------------------------------------------------------
    # Adversaires
    # -----------------------------------------------------------------
    adversaires_out = [{"nom": r.get("Nom", ""), "couleur": r.get("Couleur", "")} for r in adversaires_raw]
    pd.DataFrame(adversaires_out, columns=["nom", "couleur"]).to_csv(DATA_DIR / "adversaires.csv", index=False)

    # -----------------------------------------------------------------
    # Liens_Utiles
    # -----------------------------------------------------------------
    liens_out = [{"titre": r.get("Titre", ""), "url": r.get("URL", "")} for r in liens_utiles_raw]
    pd.DataFrame(liens_out, columns=["titre", "url"]).to_csv(DATA_DIR / "liens_utiles.csv", index=False)

    # -----------------------------------------------------------------
    # Stades
    # -----------------------------------------------------------------
    stades_out = [{"nom": r.get("Nom", ""), "latitude": r.get("Latitude"), "longitude": r.get("Longitude")}
                  for r in stades_raw]
    pd.DataFrame(stades_out, columns=["nom", "latitude", "longitude"]).to_csv(DATA_DIR / "stades.csv", index=False)

    # -----------------------------------------------------------------
    # Disponibilites (Match référence Prochains_Matchs)
    # -----------------------------------------------------------------
    dispo_out = []
    for r in disponibilites_raw:
        prochain_id = r.get("Match")
        joueur_id = r.get("Joueur")
        dispo_out.append({
            "match_date": date_prochain_par_id.get(prochain_id, ""),
            "joueur": nom_par_id.get(joueur_id, "") if joueur_id else "",
            "reponse": r.get("Reponse", ""),
        })
    pd.DataFrame(dispo_out, columns=["match_date", "joueur", "reponse"]).to_csv(
        DATA_DIR / "disponibilites.csv", index=False)

    print(f"OK — {len(matchs_out)} matchs, {len(part_out)} participations, "
          f"{len(effectif_out)} joueurs, {len(classement_out)} lignes de classement.")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"Erreur API Grist : {e}", file=sys.stderr)
        print(f"Réponse : {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except KeyError as e:
        print(f"Table ou colonne introuvable — vérifie le nom exact dans Grist : {e}", file=sys.stderr)
        sys.exit(1)
