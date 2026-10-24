#!/bin/sh
# Applies all Alembic migrations (DATABASE_URL from the environment). Used by the compose
# `migrate` service; idempotent, so re-running at head is a no-op.
exec alembic upgrade head
