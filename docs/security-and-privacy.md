# Security and privacy

## Data minimization

The current app reads broker account data for the local user. It does not ask for broker passwords, OTPs, or UPI PINs. The Zerodha developer API key and secret are read from `.env` on the server; access tokens are held in process memory only. Avoid personal data and free-text journal analytics unless there is a clear, reviewed purpose and user control.

## Future design requirements

- Threat-model authentication, authorization, exports, storage, and dependencies before deploying a service.
- Define data classification, retention, deletion, backup, and breach-response procedures.
- Encrypt sensitive data in transit and at rest where applicable; restrict access by least privilege.
- Keep secrets out of Git, client code, logs, and demo recordings. The local `.env` file is gitignored. A hosted deployment would require a managed secret store and a different security design.
- Make telemetry opt-in or otherwise appropriately disclosed, minimal, and easy to disable.

## Out of scope

The local prototype must not be exposed to the public internet or used as a multi-user service. Live order submission is disabled by default and requires a local setting, review screen, and typed confirmation. This does not replace broker/exchange controls or a qualified regulatory review.
