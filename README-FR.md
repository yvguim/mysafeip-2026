# MySafeIP

MySafeIP permet aux utilisateurs autorisés d’enregistrer leurs adresses IP pour les systèmes qui gèrent des listes d’accès. L’application ne configure pas elle-même de pare-feu.

[English version](README.md)

## Documentation utilisateur

- [Présentation et fonctionnalités](docs/utilisateurs/presentation.md) — à quoi sert MySafeIP et ce qui reste à la charge du système externe.
- [Installation](docs/utilisateurs/installation.md) — démarrer avec Docker Compose, créer le premier administrateur et conserver ses données.
- [Utilisation](docs/utilisateurs/utilisation.md) — gérer les IP, partager des liens, sécuriser son compte et lire la liste depuis un script.

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
