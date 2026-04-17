from runtime_config import get_client_runtime_config
from erp_providers import FrappeProvider, OdooProvider

def get_provider(client_id: str):
    config = get_client_runtime_config(client_id)
    erp_type = config.get("erp_type", "erpnext")
    
    if erp_type == "odoo":
        return OdooProvider(config)
    else:
        return FrappeProvider(config)

async def run_query(sql, client_id="DEMO_CLIENT_123"):
    provider = get_provider(client_id)
    return await provider.run_query(sql)

async def get_app_name(client_id="DEMO_CLIENT_123"):
    provider = get_provider(client_id)
    return await provider.get_app_name()

async def get_default_currency_info(client_id="DEMO_CLIENT_123"):
    provider = get_provider(client_id)
    return await provider.get_currency_info()
