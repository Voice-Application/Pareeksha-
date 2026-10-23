#!/bin/sh
# Runs Alembic when migrations exist (API-01 adds alembic.ini); before that there is nothing to migrate.
if [ -f alembic.ini ]; then exec alembic upgrade head; fi
echo "no alembic.ini yet (API-01 pending): nothing to migrate"
