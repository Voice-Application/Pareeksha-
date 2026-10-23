# NOTES

- INFRA-01: apache/kafka:4.0.0 + KRaft compose works unchanged from starter; kafka-init is idempotent. Behind a TLS-intercepting proxy `pip` inside `docker build` fails SSL; use `docker-compose.proxy.yml` (CA as build secret) rather than disabling verification. See proof/INFRA-01/proof.md.
- INFRA-01: worker services need compose profile `workers` until their modules exist (INFRA-02+), else crash-loop. See docker-compose.yml.
