import unittest

from ai_engine import _extract_referenced_tables, _find_unknown_tables
from erp_providers import FrappeProvider, OdooProvider, get_provider
from main import ClientConfigRequest
from schema_fetcher import extract_available_table_names, format_live_doctype_details_for_prompt
from schema_planner import build_relation_plan_text
from schema_router import filter_schema
from sql_validator import validate_sql


class MultiERPTests(unittest.TestCase):
    def test_erpnext_remains_default_provider(self):
        provider = get_provider({"erp_url": "https://erp.example", "api_key": "key", "api_secret": "secret"})
        self.assertIsInstance(provider, FrappeProvider)

    def test_odoo_selects_odoo_provider(self):
        provider = get_provider({
            "erp_type": "odoo",
            "erp_url": "https://odoo.example",
            "api_secret": "bridge-secret",
            "odoo_db": "odoo_db",
        })
        self.assertIsInstance(provider, OdooProvider)

    def test_odoo_configuration_requires_database(self):
        with self.assertRaises(ValueError):
            ClientConfigRequest(
                client_id="odoo-client",
                erp_url="https://odoo.example",
                api_key="user@example.com",
                api_secret="bridge-secret",
                erp_type="odoo",
            )

    def test_erpnext_configuration_does_not_require_odoo_database(self):
        config = ClientConfigRequest(
            client_id="erpnext-client",
            erp_url="https://erpnext.example",
            api_key="key",
            api_secret="secret",
        )
        self.assertEqual(config.erp_type, "erpnext")

    def test_sql_validator_keeps_read_only_limit(self):
        self.assertEqual(validate_sql("SELECT id FROM sale_order"), "SELECT id FROM sale_order LIMIT 1000")
        with self.assertRaises(Exception):
            validate_sql("UPDATE sale_order SET name = 'bad'")

    def test_odoo_schema_names_have_no_tab_prefix(self):
        schema = {
            "erp_type": "odoo",
            "available_doctypes": [{"name": "sale_order"}],
            "custom_doctypes": [],
            "doctype_details": {
                "sale_order": {
                    "fields": [{"fieldname": "partner_id", "fieldtype": "many2one", "options": "res_partner"}],
                    "child_tables": [],
                }
            },
            "custom_fields": [],
        }
        self.assertEqual(extract_available_table_names(schema), {"sale_order"})
        prompt = format_live_doctype_details_for_prompt(schema, ["sale_order"])
        self.assertIn("`sale_order`", prompt)
        self.assertNotIn("`tabsale_order`", prompt)

    def test_odoo_relation_plan_uses_id_foreign_keys(self):
        schema = {
            "erp_type": "odoo",
            "doctype_details": {
                "sale_order": {
                    "fields": [{"fieldname": "partner_id", "fieldtype": "many2one", "options": "res_partner"}],
                },
                "res_partner": {"fields": []},
            },
            "custom_doctypes": [],
        }
        plan = build_relation_plan_text("show orders and customers", ["sale_order", "res_partner"], schema)
        self.assertIn("sale_order", plan)
        self.assertIn("res_partner", plan)
        self.assertIn("id", plan)
        self.assertNotIn("parenttype", plan)

    def test_unknown_odoo_tables_are_checked_without_tab_prefix(self):
        schema = {"erp_type": "odoo", "available_doctypes": [{"name": "sale_order"}]}
        self.assertEqual(_extract_referenced_tables("SELECT id FROM sale_order", "odoo"), ["sale_order"])
        self.assertEqual(_find_unknown_tables("SELECT id FROM sale_order", schema), [])
        self.assertEqual(_find_unknown_tables("SELECT id FROM missing_table", schema), ["missing_table"])

    def test_schema_filter_accepts_both_erp_types(self):
        erpnext_schema = filter_schema(
            "`tabCustomer`: name",
            "",
            "",
            "",
            ["tabCustomer"],
            erp_type="erpnext",
        )
        odoo_schema = filter_schema(
            "`res_partner`: id",
            "",
            "",
            "",
            ["res_partner"],
            erp_type="odoo",
        )
        self.assertIn("tabCustomer", erpnext_schema)
        self.assertIn("res_partner", odoo_schema)


if __name__ == "__main__":
    unittest.main()
