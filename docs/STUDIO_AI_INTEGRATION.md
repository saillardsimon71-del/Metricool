# Intégration Studio IA

SocialDock peut recevoir les rendus vidéo d'un outil externe — par exemple un
générateur local de vidéos (**Studio IA**) — **sans jamais dépendre de lui** et
**sans modifier son dépôt**. Deux mécanismes, cumulables :

1. **Dossier surveillé** : Studio IA écrit ses rendus dans un dossier ;
   SocialDock les importe automatiquement.
2. **API d'ingestion** : Studio IA appelle `POST /api/ingest/video` (ou
   `/upload`) avec un jeton ; SocialDock importe et crée un brouillon prêt à
   composer.

```
Studio IA (externe)                     SocialDock (ce dépôt)
├── rend un .mp4 ──────────────┐
│                              ├──► dossier surveillé ──► import + brouillon
│                              │
└── POST /api/ingest/video ────┴──► jeton X-SocialDock-Token ──► import + brouillon
```

## 1. Dossier surveillé

**Automatisations → Dossiers surveillés (Studio IA) → Ajouter**, ou :

```powershell
curl -X POST http://127.0.0.1:8000/api/watchers `
  -H "Content-Type: application/json" `
  -d '{"path":"C:\\Users\\moi\\StudioIA\\sorties","recursive":true,"tags":["studio-ai"],"create_draft":true,"enabled":true}'
```

Comportement :

* analyse du dossier (manuellement, au démarrage, ou `POST /api/watchers/scan-all`) ;
* **stabilité** : un fichier modifié depuis moins de 5 s est ignoré (rendu en
  cours d'écriture) et retenté au scan suivant — `STABILITY_SECONDS` dans
  `backend/socialdock/services/watcher.py` ;
* **anti-doublon** : l'empreinte SHA-256 est comparée, un rendu identique n'est
  jamais réimporté ;
* chaque import crée un **brouillon** prêt à composer (modèle applicable).

## 2. API d'ingestion

Protégée par un jeton (comparaison à temps constant) et limitée aux dossiers
autorisés.

### Obtenir le jeton

**Paramètres → Intégration Studio IA** (bouton *Régénérer* disponible), ou :

```powershell
curl http://127.0.0.1:8000/api/settings   # champ integrations.ingest_token
```

Le jeton est stocké dans `%LOCALAPPDATA%\SocialDock\secrets\` avec des
permissions restreintes. Il n'apparaît jamais dans les journaux.

### Envoyer un rendu par chemin local

```powershell
curl -X POST http://127.0.0.1:8000/api/ingest/video `
  -H "X-SocialDock-Token: VOTRE_JETON" `
  -H "Content-Type: application/json" `
  -d '{"path":"C:\\Users\\moi\\StudioIA\\sorties\\episode-12.mp4","title":"Épisode 12","tags":["studio-ai","ia"],"create_draft":true}'
```

Réponse :

```json
{"media_id":"9f1c…","created":true,"duplicate_of":null,"draft_post_id":"4b2a…"}
```

### Envoyer un rendu par téléversement

```powershell
curl -X POST http://127.0.0.1:8000/api/ingest/upload `
  -H "X-SocialDock-Token: VOTRE_JETON" `
  -F "file=@episode-12.mp4" -F "title=Épisode 12" -F "tags=studio-ai,ia"
```

### Côté Studio IA (Python)

```python
import httpx

with httpx.Client(base_url="http://127.0.0.1:8000") as client:
    response = client.post(
        "/api/ingest/video",
        headers={"X-SocialDock-Token": TOKEN},
        json={"path": str(chemin_rendu), "title": titre, "tags": ["studio-ai"], "create_draft": True},
    )
    response.raise_for_status()
    print(response.json()["draft_post_id"])
```

## 3. Garantie d'indépendance

* SocialDock **n'importe aucun module** de Studio IA et **n'écrit jamais** dans
  son dépôt : l'intégration est strictement unidirectionnelle (fichiers + HTTP).
* Si Studio IA est absent, SocialDock fonctionne normalement.
* Aucun appel sortant n'est effectué vers Studio IA.

## 4. Sécurité

| Mesure | Détail |
|---|---|
| Authentification | En-tête `X-SocialDock-Token`, comparaison à temps constant |
| Périmètre | Uniquement le répertoire de données et les dossiers surveillés déclarés — **pas** le répertoire personnel complet |
| Traversée de chemin | Le chemin est résolu puis comparé aux racines autorisées |
| Formats | Seules les extensions média supportées sont acceptées |
| Journalisation | Les appels sont tracés sans le jeton |
| Contenu IA | Le drapeau `is_aigc` est transmis à TikTok lors de la publication |

## 5. Dépannage

| Réponse | Signification |
|---|---|
| `401` | Jeton absent ou invalide |
| `403` | Chemin hors des dossiers autorisés |
| `404` | Fichier introuvable |
| `400` | Format non supporté, ou chemin manquant |
| `201` avec `created: false` | Doublon : `duplicate_of` donne l'identifiant existant |

Voir aussi [SECURITY.md](SECURITY.md) et [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
