from runtime_config import get_client_runtime_config
from erp_providers import get_provider


async def run_query(sql, client_id="DEMO_CLIENT_123"):
    return await get_provider(get_client_runtime_config(client_id)).run_query(sql)


async def get_frappe_version(client_id="DEMO_CLIENT_123"):
    from erp_version import get_erp_version
    return await get_erp_version(client_id)


async def get_app_name(client_id="DEMO_CLIENT_123"):
    return await get_provider(get_client_runtime_config(client_id)).get_app_name()


async def get_default_currency_info(client_id="DEMO_CLIENT_123"):
    return await get_provider(get_client_runtime_config(client_id)).get_currency_info()
