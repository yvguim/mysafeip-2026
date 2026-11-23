# Installation avec Docker Compose

[Sommaire](../../README-FR.md) · [Présentation](presentation.md) · [Utilisation](utilisation.md) · [English](../users/installation.md)

## Démarrer une instance locale

Il te faut Docker Engine 28.0.0 ou une version ultérieure et le module Docker Compose. Les anciennes versions de Docker Engine peuvent exposer les ports liés à la boucle locale aux autres machines du réseau local. Place-toi à la racine du dépôt, à côté de `compose.yaml`. Compose récupère l’image publique `yvguim/mysafeip` sur Docker Hub, sans build local. `env.template` liste les variables disponibles.

Utilise une version publiée qui prend en charge l’installation sans jeton et le démarrage sans `JWT_SECRET`. Le tag par défaut doit être publié avant de lancer ces commandes ; les anciennes images ne sont pas compatibles avec ce guide de premier démarrage.

```sh
docker compose up -d --wait
docker compose ps
```

Aucun fichier `.env` n’est requis pour démarrer. Si `JWT_SECRET` est absent ou vide, MySafeIP génère un nouveau secret de signature à chaque démarrage et affiche un avertissement sans révéler sa valeur. Les sessions sont invalidées au redémarrage, mais les comptes et les données sont conservés. Pour garder les sessions, génère une valeur privée avec `openssl rand -hex 32`, renseigne `JWT_SECRET` dans `.env`, puis relance `docker compose up -d --wait`. Conserve cette valeur sans la modifier ni la partager. Au démarrage, MySafeIP crée aussi le fichier SQLite et ses tables s’ils sont absents.

Si ton déploiement utilise plusieurs processus web ou réplicas, configure le même `JWT_SECRET` partout pour que les sessions restent valides quel que soit le processus qui traite la requête.

```text
Navigateur ── HTTP sur 127.0.0.1:8000 ──> Conteneur web
                                               │ lit et écrit
                                               ▼
                                     Volume Compose data
                                         /data/mysafeip.db
```

## Créer le premier compte administrateur

**N’expose pas l’instance sur le réseau, même via un proxy, tant que le premier administrateur n’a pas été créé.** Pendant cette étape, toute personne pouvant atteindre la page pourrait créer le compte. Cela vaut aussi pour une installation dont la configuration initiale a été interrompue.

1. Ouvre `http://127.0.0.1:8000`. Pour une installation neuve, MySafeIP affiche le formulaire de création du premier administrateur.
2. Indique ton adresse e-mail et choisis un mot de passe unique. Aucun jeton n’est nécessaire.
3. Valide, puis connecte-toi. Le formulaire se ferme définitivement pour cette base, même après un redémarrage.

Le formulaire ne s’active que pour une base en attente de configuration initiale. Les inscriptions ordinaires restent fermées. Active le TOTP depuis ton profil ; voir [Utilisation](utilisation.md).

Utilise `localhost`, `127.0.0.1` ou l’hôte configuré dans `MYSAFEIP_URL`. Si tu utilises un proxy privé pour cette étape, conserve l’en-tête `Host` vu par le navigateur (port compris) et règle `X-Forwarded-Proto` sur le protocole d’origine.

Si tu dois créer un administrateur sans le formulaire (par exemple sur une ancienne base), lance la commande suivante depuis un terminal interactif. Le mot de passe n’est ni affiché ni passé en argument du processus.

```sh
docker compose exec web python -c 'from getpass import getpass; from init_admin import main; raise SystemExit(main([input("Adresse admin : "), getpass("Mot de passe : ")]))'
```

Si l’adresse existe déjà, le script ne remplace pas le compte.

## Réinitialiser le mot de passe d’un compte depuis l’hôte Docker

Utilise une version de l’image qui contient `/app/scripts/reset_admin.py`. Le tag par défaut de Compose peut être plus ancien : si le fichier est absent, sélectionne un tag publié compatible en suivant la procédure de mise à jour ci-dessous. Il n’est pas nécessaire de copier le script sur l’hôte.

Sur l’hôte Docker, depuis le dossier du fichier Compose, lance la commande et saisis l’adresse exacte d’un compte actif (administrateur ou utilisateur standard) :

```sh
printf 'Adresse du compte : ' >&2
IFS= read -r account_email && docker compose exec -T web python -B /app/scripts/reset_admin.py -- "$account_email"
```

Si tu as démarré le conteneur sans Compose, remplace `mysafeip` par son nom ou son ID :

```sh
printf 'Adresse du compte : ' >&2
IFS= read -r account_email && docker exec mysafeip python -B /app/scripts/reset_admin.py -- "$account_email"
```

Le script s’exécute dans le conteneur en cours d’exécution, avec son utilisateur habituel. Il n’ajoute pas de route HTTP de récupération. Réserve l’accès au démon Docker et à la base de données aux personnes de confiance.

La commande affiche le nouveau mot de passe sur la sortie standard uniquement après l’avoir enregistré. Lance-la dans un terminal privé. Elle conserve par défaut l’authentification à deux facteurs (TOTP). Si le second facteur a aussi été perdu, ajoute `--clear-totp` juste avant `--`, puis réactive le TOTP après connexion. Elle ne crée ni ne réactive de compte et ne révoque pas les sessions existantes ni les clés API.

## Configurer le port, l’adresse et la langue

Si le port 8000 est déjà occupé, ajoute ces lignes à `.env` (sans remplacer `JWT_SECRET`), puis relance `docker compose up -d --wait` :

```dotenv
MYSAFEIP_PORT=8080
MYSAFEIP_URL=http://127.0.0.1:8080
MYSAFEIP_LANGUAGE=fr
```

`MYSAFEIP_PORT` change le port de l’hôte ; `MYSAFEIP_URL` est l’adresse utilisée pour générer les liens. Les deux doivent correspondre à ton installation. La langue par défaut accepte `fr` ou `en`.

Le port est lié à la boucle locale. Un lien généré avec `127.0.0.1` ne fonctionne pas pour un destinataire distant. Les en-têtes proxy sont acceptés par défaut uniquement depuis la boucle locale **du conteneur**. Si ton proxy est sur l’hôte ou dans un autre conteneur, renseigne `MYSAFEIP_FORWARDED_ALLOW_IPS` avec son adresse telle que vue par MySafeIP. Laisse cette variable vide pour désactiver la confiance. Avant d’exposer l’instance, configure HTTPS, bloque les accès directs et impose au proxy de remplacer les en-têtes transmis par le client.

## Arrêter, sauvegarder et mettre à jour

- `docker compose stop` arrête le service ; `docker compose up -d --wait` le redémarre.
- `docker compose down` retire les conteneurs et conserve le volume SQLite. **`docker compose down --volumes` supprime les données.** Ne lance pas cette commande pour une mise à jour.
- Avant une mise à jour, arrête le service et fais une sauvegarde cohérente de SQLite ; conserve séparément `.env` et la sauvegarde dans un emplacement privé. Teste la restauration sur une copie avant de toucher aux données réelles.
- Après avoir choisi une version publiée, renseigne `MYSAFEIP_IMAGE_TAG` dans `.env`, puis lance `docker compose pull` et `docker compose up -d --wait`. Garde le même projet Compose et le même volume. Ne suppose pas qu’une ancienne base est automatiquement migrée.

## Si le démarrage échoue

- `docker compose config -q` vérifie la configuration sans afficher un éventuel secret configuré.
- `docker compose ps` indique l’état du service ; `docker compose logs --tail=100 web` aide à identifier la cause. Relis les logs avant de les partager : ils peuvent contenir des informations sensibles.
- Si l’accueil est inaccessible après un changement de port, ouvre la nouvelle adresse et vérifie que le port n’est pas déjà utilisé. Si SQLite signale un problème de permissions, vérifie que le volume est accessible à l’utilisateur `10001` du conteneur ; ne contourne pas le problème en démarrant l’application en root.
