#!/bin/sh
# One mock-agent container per planted bug on the compose network (MOCK_BUGS is per process).
# Sandbox only: proxy CA mounted so Gnani TTS works behind the TLS-intercepting proxy.
for bug in no_disclosure no_amount_confirm english_to_kannada ignore_interrupt false_waiver; do
  n=qa03-$(echo $bug | tr _ -)
  docker rm -f $n >/dev/null 2>&1
  docker run -d --name $n --network pk-m3_default --env-file .env -e MOCK_BUGS=$bug \
    -e SSL_CERT_FILE=/etc/ssl/proxy-ca.crt -e REQUESTS_CA_BUNDLE=/etc/ssl/proxy-ca.crt \
    -v /root/.ccr/ca-bundle.crt:/etc/ssl/proxy-ca.crt:ro pk-m3-mock-agent:latest >/dev/null && echo started $n
done
