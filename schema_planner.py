from collections import deque

from schema_fetcher import get_doctype_detail_map


def _table_to_doctype(table_name):
    if not table_name:
        return ""
    return table_name[3:] if table_name.startswith("tab") else table_name


def _doctype_to_table(doctype_name):
    if not doctype_name:
        return ""
    return doctype_name if doctype_name.startswith("tab") else f"tab{doctype_name}"


def _erp_type(schema):
    return (schema or {}).get("erp_type", "erpnext")


def _schema_table(schema, name):
    if _erp_type(schema) == "odoo":
        return name
    return _doctype_to_table(name)


def _schema_resource(schema, table_name):
    if _erp_type(schema) == "odoo":
        return table_name
    return _table_to_doctype(table_name)


def _build_relation_graph(schema):
    detail_map = get_doctype_detail_map(schema)
    graph = {doctype_name: [] for doctype_name in detail_map}

    for doctype_name, detail in detail_map.items():
        for field in detail.get("fields", []):
            fieldtype = field.get("fieldtype")
            fieldname = field.get("fieldname")
            options = field.get("options")

            if fieldtype in {"Link", "many2one"} and options:
                edge = {
                    "kind": "link",
                    "left_doctype": doctype_name,
                    "right_doctype": options,
                    "left_field": fieldname,
                }
                graph.setdefault(doctype_name, []).append((options, edge))
                graph.setdefault(options, []).append((doctype_name, edge))

            if fieldtype == "Table" and options:
                edge = {
                    "kind": "child_table",
                    "parent_doctype": doctype_name,
                    "child_doctype": options,
                    "parent_field": fieldname,
                }
                graph.setdefault(doctype_name, []).append((options, edge))
                graph.setdefault(options, []).append((doctype_name, edge))

    return graph, detail_map


def _find_shortest_path(graph, start, goal):
    if start == goal:
        return []

    queue = deque([(start, [])])
    visited = {start}

    while queue:
        current, path = queue.popleft()
        for neighbor, edge in graph.get(current, []):
            if neighbor in visited:
                continue
            next_path = path + [(current, neighbor, edge)]
            if neighbor == goal:
                return next_path
            visited.add(neighbor)
            queue.append((neighbor, next_path))

    return None


def _format_edge_step(current_doctype, next_doctype, edge, schema):
    if edge["kind"] == "link":
        left_table = _schema_table(schema, edge["left_doctype"])
        right_table = _schema_table(schema, edge["right_doctype"])
        left_field = edge["left_field"]
        target_key = "id" if _erp_type(schema) == "odoo" else "name"
        return (
            f"`{left_table}`.`{left_field}` links to `{right_table}`.`{target_key}`."
            f" Use this relation when connecting `{_schema_table(schema, current_doctype)}` and"
            f" `{_schema_table(schema, next_doctype)}`."
        )

    parent_table = _schema_table(schema, edge["parent_doctype"])
    child_table = _schema_table(schema, edge["child_doctype"])
    parent_field = edge["parent_field"]
    if _erp_type(schema) == "odoo":
        return f"`{child_table}` references `{parent_table}` through `{parent_table}_id` and `id`."
    return (
        f"`{child_table}` is a child table of `{parent_table}` via `{parent_field}`."
        f" Join with `{child_table}`.`parent` = `{parent_table}`.`name`"
        f" and `{child_table}`.`parenttype` = '{edge['parent_doctype']}'."
    )


def _build_path_steps(required_doctypes, graph, schema):
    if not required_doctypes:
        return []

    base = required_doctypes[0]
    steps = []
    seen_edges = set()

    for target in required_doctypes[1:]:
        path = _find_shortest_path(graph, base, target)
        if not path:
            continue

        for current, nxt, edge in path:
            edge_key = (
                edge["kind"],
                edge.get("left_doctype"),
                edge.get("right_doctype"),
                edge.get("left_field"),
                edge.get("parent_doctype"),
                edge.get("child_doctype"),
                edge.get("parent_field"),
            )
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            steps.append(_format_edge_step(current, nxt, edge, schema))

    return steps


def _build_shared_target_hints(required_doctypes, detail_map, schema):
    target_map = {}
    hints = []

    for doctype_name in required_doctypes:
        detail = detail_map.get(doctype_name, {})
        for field in detail.get("fields", []):
            if field.get("fieldtype") not in {"Link", "many2one"} or not field.get("options"):
                continue
            target_map.setdefault(field["options"], []).append((doctype_name, field.get("fieldname")))

    for target_doctype, refs in sorted(target_map.items()):
        if len(refs) < 2:
            continue

        field_groups = {}
        for doctype_name, fieldname in refs:
            field_groups.setdefault(fieldname, []).append(doctype_name)

        for fieldname, doctypes in field_groups.items():
            if len(doctypes) < 2:
                continue
            tables = ", ".join(f"`{_schema_table(schema, name)}`" for name in sorted(doctypes))
            hints.append(
                f"{tables} all have `{fieldname}` linking to `{_schema_table(schema, target_doctype)}`."
                f" Match those fields when the business logic requires the same {fieldname.replace('_', ' ')}."
            )

    return hints


def build_relation_plan_text(user_prompt, required_tables, schema):
    graph, detail_map = _build_relation_graph(schema)
    required_doctypes = [
        _schema_resource(schema, table_name)
        for table_name in required_tables or []
        if _schema_resource(schema, table_name) in graph
    ]

    if len(required_doctypes) < 2:
        return ""

    relation_steps = _build_path_steps(required_doctypes, graph, schema)
    shared_target_hints = _build_shared_target_hints(required_doctypes, detail_map, schema)

    if not relation_steps and not shared_target_hints:
        return ""

    lines = [
        "### DISCOVERED LIVE RELATION PLAN ###",
        "Use these tenant-specific join paths from the live ERP metadata before inventing any relation.",
        f"Prompt focus: {user_prompt}",
        "",
    ]

    if relation_steps:
        lines.append("Join path hints:")
        for step in relation_steps:
            lines.append(f"- {step}")

    if shared_target_hints:
        lines.append("")
        lines.append("Shared target hints:")
        for hint in shared_target_hints:
            lines.append(f"- {hint}")

    lines.append("")
    lines.append("Prefer these discovered relations over guessed ERPNext conventions.")
    return "\n".join(lines)


def build_relation_constraints(required_tables, schema):
    graph, _detail_map = _build_relation_graph(schema)
    required_doctypes = [
        _table_to_doctype(table_name)
        for table_name in required_tables or []
        if _table_to_doctype(table_name) in graph
    ]

    constraints = []
    seen = set()
    for doctype_name in required_doctypes:
        for neighbor, edge in graph.get(doctype_name, []):
            if edge["kind"] != "child_table":
                continue

            child_doctype = edge["child_doctype"]
            parent_doctype = edge["parent_doctype"]
            if child_doctype not in required_doctypes or parent_doctype not in required_doctypes:
                continue

            key = (parent_doctype, child_doctype, edge["parent_field"])
            if key in seen:
                continue
            seen.add(key)

            constraints.append(
                {
                    "kind": "child_table",
                    "parent_doctype": parent_doctype,
                    "child_doctype": child_doctype,
                    "parent_table": _doctype_to_table(parent_doctype),
                    "child_table": _doctype_to_table(child_doctype),
                    "parent_field": edge["parent_field"],
                    "message": (
                        f"`{_doctype_to_table(child_doctype)}` is a child table of "
                        f"`{_doctype_to_table(parent_doctype)}` and must join through "
                        f"`parent`/`parenttype`, not through a guessed business field."
                    ),
                }
            )

    return constraints
