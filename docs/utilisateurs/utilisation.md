# Utilisation de MySafeIP

[Sommaire](../../README-FR.md) · [Présentation](presentation.md) · [Installation](installation.md) · [English](../users/usage.md)

## Enregistrer ou retirer une adresse IP

1. Connecte-toi, puis ouvre la page des adresses IP (`/ips/config/`).
2. Vérifie l’adresse détectée avant de l’enregistrer, surtout derrière un proxy ou un VPN. Tu peux saisir à la place une adresse IPv4 ou IPv6 individuelle et ajouter une description.
3. Choisis une durée de 1 à 720 heures ou coche l’option permanente si l’entrée ne doit pas expirer. Le profil permet de modifier la durée proposée par défaut. Enregistre et vérifie que l’adresse apparaît dans la liste.
4. Supprime l’entrée quand elle n’est plus nécessaire. MySafeIP l’enlève de la liste ; le système externe doit ensuite retirer la règle correspondante. Une IP identique peut encore figurer dans une autre entrée.

## Partager un lien d’accès instantané

1. Ouvre la page d’accès instantané (`/instant-access/config/`).
2. Renseigne l’URL de destination (`http://` ou `https://`), une description et une durée de 1 à 720 heures. Préfère une durée courte à un lien permanent.
3. Copie le lien généré par MySafeIP et partage-le uniquement avec le destinataire. Si le lien commence par `127.0.0.1`, il ne sera pas joignable par une autre machine ; voir [Installation](installation.md).

```text
Créateur ── partage le lien ──> Visiteur
                                  │ ouvre le lien sans compte
                                  ▼
                               MySafeIP ── enregistre l’IP sous le compte du créateur
                                  │ affiche une page avant la redirection
                                  ▼
                               Destination
```

La **durée de vie du lien** et celle de **l’IP créée** sont distinctes : une nouvelle entrée IP créée à l’ouverture du lien est valable 24 heures. L’expiration du lien n’efface pas immédiatement les IP déjà créées. En revanche, **supprimer manuellement un lien depuis sa liste** efface aussi les entrées IP associées encore présentes ; si le lien n’est plus listé, vérifie les adresses et retire celles qui ne doivent plus figurer dans la liste. Cette opération ne révoque pas directement une règle mise en cache par un système externe.

Toute personne qui possède le lien peut l’utiliser tant qu’il est valide. Ne le publie pas, et ne le considère ni comme un lien à usage unique ni comme un remplacement de l’authentification à destination.

## Protéger son compte

- Dans ton profil, tu peux changer ton mot de passe et définir les durées par défaut des IP et des liens.
- Pour activer le TOTP, coche la double authentification et enregistre. Scanne le QR code dans ton application d’authentification ou saisis la clé manuellement. Protège cette clé comme un mot de passe. Vérifie que tu peux te connecter avec le code avant de fermer ta session actuelle, par exemple dans une fenêtre privée.
- Un administrateur peut ouvrir la liste des comptes (`/users/read`) et accéder à la documentation interactive à `/docs` après connexion. Ne présume pas qu’un compte administrateur a accès à toutes les adresses : ce réglage est désactivé dans le Compose fourni.

## Lire les IP depuis une intégration

Dans le profil du compte qui doit lire la liste, crée un jeton API et conserve sa clé et son secret dans le gestionnaire de secrets de ton intégration. Le script échange ces valeurs via `POST /token-signin` (champs de formulaire `key` et `secret`) contre un `access_token`. Il appelle ensuite `GET /ips/config/` avec `Authorization: Bearer …` et `Cli: 1` pour recevoir la liste en JSON plutôt qu’en HTML. La réponse contient `owner`, `value` et `description` pour chaque entrée visible.

Un échange par clé API n’utilise pas le code TOTP : ne partage pas la clé ni le secret. Supprime la clé dans le profil si elle est compromise et ne journalise pas les jetons. Côté intégration, valide la réponse avant de modifier des règles ; distingue une liste valide mais vide d’une erreur ou d’une réponse HTML. Prends en compte à chaque synchronisation les IP qui ne figurent plus dans la liste.
