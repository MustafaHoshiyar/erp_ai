import logging
import re

from odoo import http
from odoo.http import request


_logger = logging.getLogger(__name__)
_SECRET_PARAMETER = "erp_ai.bridge_secret"
_FORBIDDEN_SQL = re.compile(
    r"\b(DELETE|UPDATE|INSERT|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CREATE)\b",
    re.IGNORECASE,
)
_MODEL_NAME = re.compile(r"^[a-zA-Z0-9_.]+$")


class ErpAiController(http.Controller):
    def _authorized(self):
        supplied = request.httprequest.headers.get("X-ERP-AI-Secret")
        configured = request.env["ir.config_parameter"].sudo().get_param(_SECRET_PARAMETER)
        return bool(configured and supplied and supplied == configured)

    @staticmethod
    def _validate_sql(sql):
        sql = (sql or "").strip()
        if not re.match(r"^(SELECT|WITH)\b", sql, re.IGNORECASE):
            return None
        if _FORBIDDEN_SQL.search(sql) or sql.count(";") > 1:
            return None
        if "/* NO_LIMIT */" not in sql.upper() and not re.search(r"\bLIMIT\s+\d+\b", sql, re.IGNORECASE):
            sql = sql.rstrip(";").rstrip() + " LIMIT 1000"
        return sql

    @http.route("/erp_ai/run_query", type="json", auth="none", methods=["POST"], csrf=False)
    def run_query(self, **kwargs):
        if not self._authorized():
            return {"error": "Unauthorized"}

        sql = self._validate_sql(kwargs.get("sql"))
        if not sql:
            return {"error": "Only a single read-only SELECT or WITH query is allowed."}

        try:
            request.cr.execute(sql)
            return {"status": "success", "data": request.cr.dictfetchall()}
        except Exception:
            _logger.exception("ERP AI SQL execution failed")
            return {"error": "The Odoo query could not be executed."}

    @http.route("/erp_ai/fetch_metadata", type="json", auth="none", methods=["POST"], csrf=False)
    def fetch_metadata(self, **kwargs):
        if not self._authorized():
            return {"error": "Unauthorized"}

        mode = kwargs.get("mode", "models")
        if mode == "models":
            sql = (
                "SELECT tablename AS model, tablename AS name, 'table' AS info "
                "FROM pg_tables WHERE schemaname = 'public'"
            )
            params = ()
        elif mode == "fields":
            model_name = kwargs.get("model")
            if not model_name or not _MODEL_NAME.fullmatch(model_name):
                return {"error": "Invalid Odoo model name."}
            sql = (
                "SELECT name, field_description AS label, ttype AS type, relation "
                "FROM ir_model_fields WHERE model = %s"
            )
            params = (model_name,)
        else:
            return {"error": "Unsupported metadata mode."}

        try:
            request.cr.execute(sql, params)
            return {"status": "success", "data": request.cr.dictfetchall()}
        except Exception:
            _logger.exception("ERP AI metadata query failed")
            return {"error": "The Odoo metadata query could not be executed."}
