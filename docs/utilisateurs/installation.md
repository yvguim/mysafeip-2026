# Installation avec Docker Compose

[Sommaire](../../README-FR.md) · [Présentation](presentation.md) · [Utilisation](utilisation.md) · [English](../users/installation.md)

## Démarrer une instance locale

Il te faut Docker démarré, le module Docker Compose et OpenSSL. Place-toi à la racine du dépôt, à côté de `compose.yaml`. Compose construit l’image depuis le `Dockerfile` fourni ; tu n’as pas besoin d’une image MySafeIP publiée ni d’identifiants de registre pour une installation standard.

```sh
(umask 077; set -C; secret=$(openssl rand -hex 32) && printf 'JWT_SECRET=%s\n' "$secret" > .env)
docker compose up -d --build --wait
docker compose ps
```

La première commande refuse d’écraser un `.env` existant. Si tu as déjà configuré l’instance, conserve son fichier et passe au démarrage. Ne partage pas `.env` : il contient le secret de signature des sessions. Ouvre `http://127.0.0.1:8000` ; le service doit être démarré et l’accueil accessible.

```text
Navigateur ── HTTP sur 127.0.0.1:8000 ──> Conteneur web
                                               │ lit et écrit
                                               ▼
                                     Volume Compose data
                                         /data/mysafeip.db
```

## Créer le premier compte administrateur

Le Compose ferme les inscriptions. Depuis un terminal interactif, lance la commande suivante. Le mot de passe est saisi sans être affiché ni passé en argument du processus.

```sh
docker compose exec web python -c 'from getpass import getpass; from init_admin import main; raise SystemExit(main([input("Adresse admin : "), getpass("Mot de passe : ")]))'
```

Une fois la commande terminée sans erreur, connecte-toi sur la page **Connexion**. Si l’adresse existe déjà, le script ne remplace pas le compte. Utilise un mot de passe unique et active le TOTP depuis ton profil ; voir [Utilisation](utilisation.md).

## Configurer le port, l’adresse et la langue

Si le port 8000 est déjà occupé, ajoute ces lignes à `.env` (sans remplacer `JWT_SECRET`), puis relance `docker compose up -d --wait` :

```dotenv
MYSAFEIP_PORT=8080
MYSAFEIP_URL=http://127.0.0.1:8080
MYSAFEIP_LANGUAGE=fr
```

`MYSAFEIP_PORT` change le port de l’hôte ; `MYSAFEIP_URL` est l’adresse utilisée pour générer les liens. Les deux doivent correspondre à ton installation. La langue par défaut accepte `fr` ou `en`.

Le port est lié à la boucle locale. Un lien généré avec `127.0.0.1` ne fonctionne pas pour un destinataire distant. Avant toute exposition, configure HTTPS et contrôle qui peut accéder à l’instance. Le profil fourni ne fait pas confiance aux en-têtes proxy. Si tu adaptes ce réglage, bloque tout accès direct et impose au proxy de remplacer les en-têtes d’IP transmis par le client.

## Arrêter, sauvegarder et mettre à jour

- `docker compose stop` arrête le service ; `docker compose up -d --wait` le redémarre.
- `docker compose down` retire les conteneurs et conserve le volume SQLite. **`docker compose down --volumes` supprime les données.** Ne lance pas cette commande pour une mise à jour.
- Avant une mise à jour, arrête le service et fais une sauvegarde cohérente de SQLite ; conserve séparément `.env` et la sauvegarde dans un emplacement privé. Teste la restauration sur une copie avant de toucher aux données réelles.
- Après avoir choisi et récupéré la révision voulue, reconstruis avec `docker compose up -d --build --wait`. Garde le même projet Compose et le même volume. Ne suppose pas qu’une ancienne base est automatiquement migrée.

## Si le démarrage échoue

- `docker compose config -q` vérifie la configuration sans afficher la valeur du secret. Si `JWT_SECRET` manque, vérifie `.env`.
- `docker compose ps` indique l’état du service ; `docker compose logs --tail=100 web` aide à identifier la cause. Relis les logs avant de les partager : ils peuvent contenir des informations sensibles.
- Si l’accueil est inaccessible après un changement de port, ouvre la nouvelle adresse et vérifie que le port n’est pas déjà utilisé. Si SQLite signale un problème de permissions, vérifie que le volume est accessible à l’utilisateur `10001` du conteneur ; ne contourne pas le problème en démarrant l’application en root.
