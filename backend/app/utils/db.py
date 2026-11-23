from sqlalchemy.exc import IntegrityError

# Postgres SQLSTATE for unique_violation. psycopg 3 exposes it as `.sqlstate`
# on the driver exception (psycopg 2 called it `.pgcode`), so both are
# checked rather than assuming the driver in use -- verified against the
# installed driver, which raises psycopg.errors.UniqueViolation with
# .sqlstate == "23505" and no .pgcode attribute at all.
SQLSTATE_UNIQUE_VIOLATION = "23505"


def is_unique_violation(exc: IntegrityError) -> bool:
    orig = getattr(exc, "orig", None)
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return code == SQLSTATE_UNIQUE_VIOLATION
