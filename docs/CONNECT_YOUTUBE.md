# Connecter YouTube

Objectif : obtenir des identifiants OAuth pour **votre** projet Google Cloud, puis
les renseigner dans SocialDock. Durée : 15 minutes (hors audit éventuel).

## 1. Créer le projet et activer l'API

1. Ouvrez <https://console.cloud.google.com/> et créez un projet
   (par exemple `SocialDock`).
2. **APIs et services → Bibliothèque** → recherchez **YouTube Data API v3** →
   **Activer**.
3. **APIs et services → Écran de consentement OAuth** :
   * type d'utilisateur : **Externe** ;
   * nom de l'application, e-mail de contact ;
   * **Audience** : ajoutez votre propre adresse Google en *utilisateur de test*
     (tant que l'app n'est pas publiée, seuls les testeurs peuvent autoriser).
4. **Identifiants → Créer des identifiants → ID client OAuth** :
   * type : **Application de bureau** (le flux est local, `127.0.0.1`) ;
   * si vous choisissez *Application Web*, déclarez exactement cette URI de
     redirection : `http://127.0.0.1:8000/api/oauth/youtube/callback`
     (ou `http://127.0.0.1:8010/...` si vous changez de port).
5. Copiez l'**ID client** et le **secret client**.

## 2. Renseigner SocialDock

Dans `.env` (copié de `.env.example`) :

```ini
SOCIALDOCK_GOOGLE_CLIENT_ID=1234567890-xxxxxxxx.apps.googleusercontent.com
SOCIALDOCK_GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxx
SOCIALDOCK_OAUTH_REDIRECT_BASE=http://127.0.0.1:8000
```

Redémarrez (`.\stop.bat` puis `.\start.bat`), puis
**Comptes → votre compte YouTube → Connecter / reconnecter**. Le navigateur
s'ouvre sur `accounts.google.com`, vous autorisez, et SocialDock enregistre le
jeton chiffré.

### Scopes demandés (minimaux)

| Scope | Usage |
|---|---|
| `https://www.googleapis.com/auth/youtube.upload` | téléverser les vidéos et leur miniature |
| `https://www.googleapis.com/auth/youtube.readonly` | lister vos chaînes, vérifier le statut et les statistiques |
| `https://www.googleapis.com/auth/youtube.force-ssl` | modifier la miniature et le statut de publication d'une vidéo que vous venez d'envoyer |

Aucun scope de gestion de compte, de monétisation ou de suppression n'est demandé.

## 3. L'audit YouTube : obligatoire pour publier en public

Depuis le **28 juillet 2020**, les vidéos téléversées via `videos.insert` depuis
un **projet API non audité** créé après cette date sont **verrouillées en privé**.

Conséquence concrète dans SocialDock :

* tant que l'audit n'est pas déclaré, `publish_public` est `false` ;
* toute publication réussit mais est enregistrée comme **`published_private`**,
  avec une action requise (« passer en public depuis YouTube ») ;
* l'interface l'affiche clairement — rien n'est présenté comme publié publiquement.

### Demander l'audit

1. Remplissez le formulaire **YouTube API Services Audit Form**
   (accessible depuis la console Google Cloud, ou via le lien fourni dans la
   documentation YouTube pour les projets dépassant les seuils d'upload).
2. Décrivez l'usage : upload de vos propres vidéos depuis un poste local,
   un seul utilisateur, aucune revente de données.
3. Après approbation, déclarez-le dans SocialDock :
   **Comptes → votre compte → case « Audit réussi »** (champ
   `extra.audit_passed`). Les publications suivantes pourront être publiques.

## 4. Quota

* 10 000 unités/jour/projet par défaut.
* `videos.insert` = **1 600 unités** → ≈ 6 uploads/jour ; `search.list` = 100.
* Une **extension de quota** se demande dans la console (formulaire d'augmentation
  de quota) et nécessite généralement l'audit.

SocialDock traite `quotaExceeded` comme une erreur **réessayable** : la cible
repart au prochain cycle, elle n'est ni perdue ni dupliquée.

## 5. Programmation native

YouTube accepte `status.publishAt` (date/heure de mise en ligne) **uniquement**
si `privacyStatus=private` et si la vidéo n'a jamais été publiée. SocialDock
utilise cette voie quand vous programmez une publication YouTube : la vidéo est
envoyée immédiatement en privé, et YouTube la rend publique à l'heure dite —
même si votre ordinateur est éteint.

## 6. Vérifier que tout fonctionne

```powershell
%LOCALAPPDATA%\SocialDock\venv\Scripts\python.exe -m socialdock doctor
```

Sortie attendue après connexion :

```
youtube : connecté — publication publique : non   (avant audit)
youtube : connecté — publication publique : oui   (après audit déclaré)
```

Puis, dans l'application : composez une publication, choisissez le compte
YouTube, **Publier maintenant**, et ouvrez la page
**Diagnostics → Tentatives récentes** : chaque appel API y est journalisé
(phase, code HTTP, durée).

## 7. Pannes fréquentes

| Symptôme | Cause | Solution |
|---|---|---|
| `redirect_uri_mismatch` | URI de redirection non déclarée | Déclarez `http://127.0.0.1:8000/api/oauth/youtube/callback` |
| `access_blocked` / écran « application non vérifiée » | App en mode test | Ajoutez votre compte en utilisateur de test |
| Vidéo systématiquement privée | Projet non audité | Voir section 3 |
| `youtubeSignupRequired` | Chaîne non créée | Créez une chaîne sur ce compte Google |
| `invalidPublishAt` | `publishAt` sans `private` | Déjà géré par SocialDock ; signalez-le si vous le rencontrez |
| Quota épuisé | 10 000 unités/jour | Attendez le renouvellement ou demandez une extension |
