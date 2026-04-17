import argparse
import json
import re
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET

NAMESPACE = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CHAT_PATTERN = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|ok|okay)\b", re.IGNORECASE)


def _read_shared_strings(workbook_zip):
    try:
        root = ET.fromstring(workbook_zip.read("xl/sharedStrings.xml"))
    except KeyError:
        return []

    values = []
    for item in root.findall("a:si", NAMESPACE):
        text = "".join(node.text or "" for node in item.iter(f"{{{NAMESPACE['a']}}}t"))
        values.append(text)
    return values


def read_workbook_rows(workbook_path):
    with zipfile.ZipFile(workbook_path) as workbook_zip:
        shared_strings = _read_shared_strings(workbook_zip)
        sheet_root = ET.fromstring(workbook_zip.read("xl/worksheets/sheet1.xml"))

    rows = []
    for row in sheet_root.findall("a:sheetData/a:row", NAMESPACE):
        values = []
        for cell in row.findall("a:c", NAMESPACE):
            raw_value = cell.find("a:v", NAMESPACE)
            if raw_value is None:
                values.append("")
                continue
            if cell.attrib.get("t") == "s":
                values.append(shared_strings[int(raw_value.text)])
            else:
                values.append(raw_value.text or "")
        rows.append(values)

    if not rows:
        return []

    headers = rows[0]
    records = []
    for row in rows[1:]:
        if not any(str(value).strip() for value in row):
            continue
        record = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            record[header] = row[index] if index < len(row) else ""
        records.append(record)
    return records


def summarize_legacy_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    message_columns = {
        row[1] for row in cur.execute("PRAGMA table_info(conversation_messages)").fetchall()
    }
    has_message_client_id = "client_id" in message_columns
    client_id_expr = (
        "TRIM(cm.client_id)"
        if has_message_client_id
        else "TRIM(COALESCE(c.client_id, ''))"
    )
    join_clause = (
        ""
        if has_message_client_id
        else " LEFT JOIN conversations c ON c.id = cm.conversation_id"
    )

    summary = {
        "conversation_count": cur.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
        "message_count": cur.execute("SELECT COUNT(*) FROM conversation_messages").fetchone()[0],
        "saved_report_count": cur.execute("SELECT COUNT(*) FROM saved_reports").fetchone()[0],
        "status_counts": {
            row[0] if row[0] is not None else "null": row[1]
            for row in cur.execute(
                "SELECT execution_status, COUNT(*) FROM conversation_messages GROUP BY execution_status"
            ).fetchall()
        },
        "feedback_counts": {
            str(row[0]) if row[0] is not None else "null": row[1]
            for row in cur.execute(
                "SELECT user_feedback, COUNT(*) FROM conversation_messages GROUP BY user_feedback"
            ).fetchall()
        },
        "client_ids": sorted(
            {
                (row[0] or "").strip()
                for row in cur.execute(
                    f"SELECT DISTINCT {client_id_expr} AS client_id FROM conversation_messages cm{join_clause}"
                ).fetchall()
                if (row[0] or "").strip()
            }
        ),
        "format_in_sql_count": cur.execute(
            "SELECT COUNT(*) FROM conversation_messages WHERE generated_sql LIKE '%FORMAT(%'"
        ).fetchone()[0],
    }

    prompts = cur.execute(
        "SELECT cm.id, "
        f"{client_id_expr} AS client_id, "
        "cm.user_prompt, cm.execution_status, cm.error_message, cm.user_feedback "
        f"FROM conversation_messages cm{join_clause}"
    ).fetchall()
    summary["chat_false_failure_count"] = sum(
        1
        for row in prompts
        if row["execution_status"] == "error" and CHAT_PATTERN.match(row["user_prompt"] or "")
    )
    summary["negative_feedback_samples"] = [
        {
            "id": row["id"],
            "client_id": (row["client_id"] or "").strip(),
            "prompt": row["user_prompt"],
            "execution_status": row["execution_status"],
            "error_message": row["error_message"],
        }
        for row in prompts
        if row["user_feedback"] == -1
    ][:20]

    conn.close()
    return summary


def _classify_workbook_failure(record):
    findings = (record.get("Findings") or "").lower()
    prompt = (record.get("Prompt") or "").lower()

    if "reorder" in prompt:
        return "reorder_schema_mismatch"
    if "exhaust" in prompt or "run out of stock" in prompt or "replenishment" in prompt:
        return "stock_runout_filtering"
    if "format()" in findings or "highest revenue" in prompt or "revenue" in prompt:
        return "numeric_sorting_formatting"
    if "payment" in prompt:
        return "payment_entry_semantics"
    if "salesperson" in prompt:
        return "salesperson_field_selection"
    if "month-wise" in prompt and "sales" in prompt and "purchase" in prompt:
        return "many_to_many_time_join"
    return "other"


def build_workbook_failure_records(rows):
    records = []
    for index, row in enumerate(rows, start=1):
        findings = (row.get("Findings") or "").strip()
        if not findings or findings.lower() == "all good":
            continue

        records.append(
            {
                "id": f"workbook-{index:03d}",
                "prompt": (row.get("Prompt") or "").strip(),
                "generated_sql": (row.get("AI genrated Query") or "").strip(),
                "output": (row.get("Output") or "").strip(),
                "findings": findings,
                "failure_category": _classify_workbook_failure(row),
            }
        )
    return records


def build_eval_candidates(workbook_failures):
    candidates = []
    for record in workbook_failures:
        item = {
            "id": record["id"],
            "prompt": record["prompt"],
            "source": "workbook",
            "notes": record["failure_category"],
        }

        category = record["failure_category"]
        if category == "reorder_schema_mismatch":
            item["expected_sql_contains"] = ["tabItem Reorder", "warehouse"]
            item["expected_sql_not_contains"] = ["FORMAT(", "tabItem`.`reorder_level"]
        elif category == "stock_runout_filtering":
            item["expected_sql_contains"] = ["actual_qty", "> 0"]
        elif category == "numeric_sorting_formatting":
            item["expected_sql_contains"] = ["SUM("]
            item["expected_sql_not_contains"] = ["FORMAT("]
        elif category == "salesperson_field_selection":
            item["expected_sql_not_contains"] = ["sales_partner"]
        elif category == "payment_entry_semantics":
            item["expected_sql_contains"] = ["docstatus = 1"]
            item["expected_sql_not_contains"] = ["status = 'Completed'", "FORMAT("]
        elif category == "many_to_many_time_join":
            item["expected_sql_contains"] = ["WITH", "tabSales Invoice", "tabPurchase Invoice"]
            item["expected_sql_not_contains"] = [
                "DATE_FORMAT(si.posting_date, '%Y-%m') = DATE_FORMAT(pi.posting_date, '%Y-%m')"
            ]
        else:
            continue

        candidates.append(item)

    return candidates


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Build Phase 1 eval artifacts from workbook and legacy DB inputs.")
    parser.add_argument("--workbook", required=True, help="Path to the workbook with tested prompts.")
    parser.add_argument("--legacy-db", required=True, help="Path to the legacy erp_ai_memory.db file.")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent / "phase1_eval_assets"),
        help="Directory where JSON artifacts will be written.",
    )
    args = parser.parse_args()

    workbook_rows = read_workbook_rows(args.workbook)
    workbook_failures = build_workbook_failure_records(workbook_rows)
    legacy_summary = summarize_legacy_db(args.legacy_db)
    eval_candidates = build_eval_candidates(workbook_failures)

    category_counts = Counter(item["failure_category"] for item in workbook_failures)
    write_json(Path(args.output_dir) / "workbook_failures.json", workbook_failures)
    write_json(Path(args.output_dir) / "workbook_failure_summary.json", category_counts)
    write_json(Path(args.output_dir) / "legacy_db_summary.json", legacy_summary)
    write_json(Path(args.output_dir) / "eval_candidates.json", eval_candidates)

    print(f"Processed {len(workbook_rows)} workbook rows.")
    print(f"Captured {len(workbook_failures)} workbook failure cases.")
    print(f"Built {len(eval_candidates)} eval candidates.")
    print(f"Wrote artifacts to: {args.output_dir}")


if __name__ == "__main__":
    main()
