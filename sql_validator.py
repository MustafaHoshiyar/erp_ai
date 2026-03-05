FORBIDDEN = ["DELETE", "UPDATE", "DROP", "INSERT", "ALTER", "TRUNCATE"]

def validate_sql(sql: str):
    upper_sql = sql.upper()

    if not (upper_sql.startswith("SELECT") or upper_sql.startswith("WITH")):
        raise Exception("Only SELECT or WITH queries are allowed.")

    for word in FORBIDDEN:
        if word in upper_sql:
            raise Exception("Forbidden SQL detected.")

    if "/* NO_LIMIT */" in upper_sql:
        return sql

    if "LIMIT" not in upper_sql:
        sql = sql.strip()
        if sql.endswith(";"):
            sql = sql[:-1] + " LIMIT 600;"
        else:
            sql += " LIMIT 600"

    return sql