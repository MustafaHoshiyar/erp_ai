import re

FORBIDDEN = ["DELETE", "UPDATE", "DROP", "INSERT", "ALTER", "TRUNCATE"]
FORBIDDEN_RE = re.compile(rf"\b({'|'.join(FORBIDDEN)})\b", re.IGNORECASE)

def validate_sql(sql: str):
    sql = sql.strip()
    upper_sql = sql.upper()

    if not (upper_sql.startswith("SELECT") or upper_sql.startswith("WITH")):
        raise Exception("Only SELECT or WITH queries are allowed.")

    if FORBIDDEN_RE.search(sql):
        raise Exception("Forbidden SQL detected.")

    if "/* NO_LIMIT */" in upper_sql:
        return sql

    if "LIMIT" not in upper_sql:
        if sql.endswith(";"):
            sql = sql[:-1] + " LIMIT 1000;"
        else:
            sql += " LIMIT 1000"

    return sql