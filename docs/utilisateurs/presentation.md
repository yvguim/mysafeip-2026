# Présentation et fonctionnalités

[Sommaire](../../README-FR.md) · [Installation](installation.md) · [Utilisation](utilisation.md) · [English](../users/overview.md)

## À quoi sert MySafeIP ?

MySafeIP permet à des utilisateurs autorisés d’enregistrer les adresses IP qui doivent figurer dans une liste d’accès. Exemple : une personne dont l’IP change enregistre sa nouvelle adresse ; un système externe récupère la liste et applique ses propres règles d’accès.

```text
Utilisateur ── enregistre une adresse ──> MySafeIP ── conserve ──> SQLite
                                             ▲
                                             │ lit la liste via l’API
                                             │
Service protégé <── règles appliquées ── Système externe
```

**MySafeIP ne modifie pas ton pare-feu et n’ouvre aucun port sur le service protégé.** Sans intégration externe, une adresse enregistrée reste une entrée dans MySafeIP. L’intégration doit tenir compte aussi des entrées disparues et décider comment réagir si l’API est indisponible.

## Ce que l’application permet

- **Gérer des adresses IPv4 ou IPv6 individuelles.** Ajoute une description et choisis une durée limitée ou une entrée permanente. La liste ne renvoie plus les entrées expirées.
- **Partager des liens d’accès instantané.** Un visiteur peut ouvrir le lien sans compte ; MySafeIP enregistre son adresse sous le compte du créateur et le redirige vers la destination. La destination doit rester protégée par ses propres règles.
- **Sécuriser les comptes.** Le profil permet de modifier son mot de passe, d’activer la double authentification TOTP et de définir les durées par défaut. Les inscriptions sont fermées dans le Compose fourni.
- **Automatiser la lecture.** Une clé API et son secret permettent d’obtenir un jeton de session pour un script. La visibilité des adresses dépend du compte et de la configuration : elle n’est pas globale par défaut.
- **Administrer l’instance.** Un administrateur peut consulter la liste des comptes, réinitialiser leurs mots de passe et accéder à la documentation interactive de l’API. Voir les IP d’autres comptes est un réglage distinct, désactivé par défaut ; le droit de les voir ne permet pas de les supprimer.

Pour essayer l’application sur ta machine, suis le [guide d’installation](installation.md). Pour enregistrer une IP ou créer un lien, passe au [guide d’utilisation](utilisation.md).
