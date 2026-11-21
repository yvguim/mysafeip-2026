# MySafeIP

MySafeIP permet aux utilisateurs autorisés d’enregistrer leurs adresses IP pour les systèmes qui gèrent des listes d’accès. L’application ne configure pas elle-même de pare-feu.

[English version](README.md)

## Démarrage local avec Docker Compose

Depuis un nouveau clone, avec Docker, son module Compose et OpenSSL installés :

```sh
(umask 077; set -C; printf 'JWT_SECRET=%s\n' "$(openssl rand -hex 32)" > .env)
docker compose up -d --build --wait
```

La première commande refuse d’écraser un `.env` existant. Garde ce fichier privé et conserve le même secret entre les redémarrages. Ouvre `http://127.0.0.1:8000`. Les inscriptions sont fermées par défaut. Crée le premier compte administrateur de façon interactive :

```sh
docker compose exec web python -c 'from getpass import getpass; from init_admin import main; raise SystemExit(main([input("Adresse admin : "), getpass("Mot de passe : ")]))'
```

Connecte-toi avec ce compte. Le port est publié uniquement sur la boucle locale de l’hôte. Pour changer le port, règle à la fois `MYSAFEIP_PORT` et `MYSAFEIP_URL` dans `.env` (par exemple `8080` et `http://127.0.0.1:8080`). `MYSAFEIP_LANGUAGE` accepte `fr` ou `en`. Avant d’exposer l’application sur un réseau, configure HTTPS et revois les règles d’accès.

SQLite conserve ses données dans le volume Compose `data`. `docker compose down` arrête l’application sans supprimer le volume ; `docker compose down --volumes` efface les données. Sauvegarde la base avant les mises à jour.

## Lancer les tests

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-test.txt
python scripts/smoke-runtime.py app
python -m pytest -q
```

## Licence

Le code de MySafeIP est sous [licence Apache 2.0](LICENSE). Les fichiers tiers conservent leurs licences et mentions de droits respectives.
