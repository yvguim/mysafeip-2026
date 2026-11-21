# Overview and features

[Index](../../README.md) · [Installation](installation.md) · [Usage](usage.md) · [Français](../utilisateurs/presentation.md)

## What is MySafeIP for?

MySafeIP lets authorized users register IP addresses for an access allowlist. For example, when someone's IP changes, they register the new address; an external system reads the list and applies its own access rules.

```text
User ── registers an address ──> MySafeIP ── stores data in ──> SQLite
                                     ▲
                                     │ reads the list via the API
                                     │
Protected service <── rules ── External system
```

**MySafeIP does not edit your firewall or open ports on the protected service.** Without an external integration, a registered address is only an entry in MySafeIP. The integration must account for entries that disappear and decide what to do when the API is unavailable.

## What you can do

- **Manage individual IPv4 or IPv6 addresses.** Add a description, then choose a lifetime or make the entry permanent. Expired entries are no longer returned in the list.
- **Share instant-access links.** A visitor can open a link without an account. MySafeIP registers their IP under the link owner's account and redirects them to the destination. The destination still needs its own access controls.
- **Secure accounts.** In your profile you can change your password, enable TOTP two-factor authentication, and set default lifetimes. Signups are disabled in the supplied Compose configuration.
- **Automate reads.** A script can exchange an API key and secret for a session token. Which IP addresses it can see depends on the account and configuration; visibility is not global by default.
- **Administer the instance.** An administrator can list accounts, reset their passwords, and access the interactive API documentation. Viewing other accounts' IPs is a separate setting, disabled by default; viewing does not grant permission to delete them.

To run the app on your machine, follow the [installation guide](installation.md). To register an IP or create a link, see the [usage guide](usage.md).
