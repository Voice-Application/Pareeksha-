#!/bin/sh
# STUB(API-01): no-op branch below until API-01 adds alembic.ini.
# Runs Alembic when migrations exist (API-01 adds alembic.ini); before that there is nothing to migrate.
if [ -f alembic.ini ]; then exec alembic upgrade head; fi
echo "no alembic.ini yet (API-01 pending): nothing to migrate"
