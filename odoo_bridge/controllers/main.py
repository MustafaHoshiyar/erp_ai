from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

# SECURITY: This key must match the one in your AI Engine's connection settings
AI_BRIDGE_SECRET = "ODOO_SECRET_123" 

class ErpAiController(http.Controller):

    def _check_security(self):
        # We check for the secret in a custom header
        secret = request.httprequest.headers.get('X-ERP-AI-Secret')
        if secret != AI_BRIDGE_SECRET:
            return False
        return True

    @http.route('/erp_ai/run_query', type='json', auth='none', methods=['POST'], csrf=False)
    def run_query(self, **kwargs):
        if not self._check_security():
            return {"error": "Unauthorized"}

        sql = kwargs.get('sql')
        if not sql:
            return {"error": "No SQL provided"}

        # Safety check: Only allow SELECT queries
        if not sql.strip().upper().startswith("SELECT") and not sql.strip().upper().startswith("WITH"):
             return {"error": "Only SELECT queries are allowed for safety."}

        try:
            request.cr.execute(sql)
            result = request.cr.dictfetchall()
            return {"status": "success", "data": result}
        except Exception as e:
            _logger.error("ERP AI SQL Error: %s", str(e))
            return {"error": str(e)}

    @http.route('/erp_ai/fetch_metadata', type='json', auth='none', methods=['POST'], csrf=False)
    def fetch_metadata(self, **kwargs):
        """Helper to fetch model and field metadata for the AI schema fetcher"""
        if not self._check_security():
            return {"error": "Unauthorized"}

        mode = kwargs.get('mode', 'models') # 'models' or 'fields'
        
        if mode == 'models':
            # Instead of just Odoo models, we fetch all tables in the public schema 
            # to ensure the AI can discover things like stock_quant, product_template etc.
            sql = "SELECT tablename as model, tablename as name, 'table' as info FROM pg_tables WHERE schemaname = 'public'"
        else:
            model_name = kwargs.get('model')
            sql = f"SELECT name, field_description as label, ttype as type, relation FROM ir_model_fields WHERE model = '{model_name}'"

        try:
            request.cr.execute(sql)
            result = request.cr.dictfetchall()
            return {"status": "success", "data": result}
        except Exception as e:
            return {"error": str(e)}
