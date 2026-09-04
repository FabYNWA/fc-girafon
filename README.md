# FC Girafon — mise en ligne

## 1. Créer le dépôt GitHub

1. Sur [github.com](https://github.com), crée un nouveau dépôt **public** (par exemple `fc-girafon-site`).
2. Pousse tout le contenu de ce dossier dedans (via l'interface web "Upload files" en glissant tout, ou via `git` si tu es à l'aise avec).

La structure doit ressembler à ça une fois poussée :
```
build_site.py
fetch_grist_data.py
assets/style.css
assets/logo.png
widgets/gestion_matchs.html
.github/workflows/deploy.yml
.gitignore
```

## 2. Récupérer ta clé API Grist

1. Dans Grist, clique sur ton profil (en haut à droite) → **Paramètres du profil**.
2. Section **Clé API** → génère-en une si tu n'en as pas, puis copie-la (elle ne sera montrée qu'une fois).

## 3. Récupérer l'identifiant de ton document Grist

Regarde l'URL de ton document Grist, du type :
```
https://docs.getgrist.com/AbCd1234EfGh/FC-Girafon
```
L'identifiant est la partie `AbCd1234EfGh` (juste après `docs.getgrist.com/`).

## 4. Ajouter les deux secrets sur GitHub

Sur ton dépôt : **Settings** → **Secrets and variables** → **Actions** → **New repository secret**, et crée :
- `GRIST_API_KEY` → la clé copiée à l'étape 2
- `GRIST_DOC_ID` → l'identifiant récupéré à l'étape 3

Ces valeurs restent privées, jamais visibles dans le code ni dans les logs.

## 5. Activer GitHub Pages

**Settings** → **Pages** → sous "Build and deployment", choisis **Source : GitHub Actions** (pas "Deploy from a branch").

## 6. Lancer une première génération

Onglet **Actions** de ton dépôt → clique sur le workflow "Générer et déployer le site FC Girafon" → **Run workflow** → **Run workflow** (bouton vert).

Après 1 à 2 minutes, le site est en ligne à une adresse du type :
```
https://<ton-pseudo-github>.github.io/fc-girafon-site/
```
(visible aussi dans Settings → Pages une fois le premier déploiement terminé).

**Ensuite, le site se régénère tout seul 3 fois par jour** (5h, 11h, 17h UTC), et à chaque fois que tu modifies `build_site.py` ou les fichiers dans `assets/`. Tu peux aussi forcer une mise à jour immédiate à tout moment via "Run workflow".

## 7. Héberger le widget de gestion des matchs

Le fichier `widgets/gestion_matchs.html` est maintenant aussi dans ce dépôt, donc il a déjà une URL publique une fois poussé :
```
https://raw.githubusercontent.com/<ton-pseudo-github>/fc-girafon-site/main/widgets/gestion_matchs.html
```
C'est cette URL qu'il faut coller dans Grist quand tu ajoutes le widget "Custom" (Accès : Accès complet au document).

## Si quelque chose ne colle pas

Le tout premier essai réel avec tes vraies données Grist peut révéler un nom de colonne qui ne correspond pas exactement (accents, majuscules, espace). Si ça arrive :
1. Onglet **Actions** → clique sur le run qui a échoué → regarde le message d'erreur (il indique en général le nom de la colonne ou de la table en cause).
2. Dis-le-moi, je corrige `fetch_grist_data.py` en conséquence — tout le mapping des noms de colonnes est centralisé dedans, un ajustement est rapide.
