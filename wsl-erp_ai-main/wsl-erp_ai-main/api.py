import frappe

@frappe.whitelist()
def run_ai_query(sql):
    return frappe.db.sql(sql, as_dict=True)

@frappe.whitelist()
def test_connection():
    return "ERP AI App Connected Successfully 🚀"

@frappe.whitelist()
def get_frappe_version():
    return frappe.__version__