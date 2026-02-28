FORBIDDEN = ["DELETE", "UPDATE", "DROP", "INSERT", "ALTER", "TRUNCATE"]

def validate_sql(sql: str):
    upper_sql = sql.upper()

    if not upper_sql.startswith("SELECT"):
        raise Exception("Only SELECT queries are allowed.")

    for word in FORBIDDEN:
        if word in upper_sql:
            raise Exception("Forbidden SQL detected.")

    if "LIMIT" not in upper_sql:
        sql += " LIMIT 600"

    return sql