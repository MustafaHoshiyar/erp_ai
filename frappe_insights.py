import os
import json
import httpx
from datetime import datetime
from dotenv import load_dotenv
from runtime_config import get_client_runtime_config

load_dotenv()
ERP_URL = os.getenv("ERP_URL")
ERP_API_KEY = os.getenv("ERP_API_KEY")
ERP_API_SECRET = os.getenv("ERP_API_SECRET")

WORKBOOK_TITLE = "ERP AI Reports"

_INSIGHTS_VERSION_CACHE = {}


async def _get_insights_version(client_id: str) -> str | None:
    if client_id in _INSIGHTS_VERSION_CACHE:
        return _INSIGHTS_VERSION_CACHE[client_id]

    config = _get_insights_runtime_config(client_id)
    headers = {
        "Authorization": f"token {config['api_key']}:{config['api_secret']}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{config['site_url']}/api/resource/Insights Query v3",
            headers=headers,
            params={"limit_page_length": 1},
            timeout=10.0
        )
        if res.status_code == 200:
            _INSIGHTS_VERSION_CACHE[client_id] = "v3"
            return "v3"

        res = await client.get(
            f"{config['site_url']}/api/method/insights.api.get_queries",
            headers=headers,
            timeout=10.0
        )
        if res.status_code == 200:
            _INSIGHTS_VERSION_CACHE[client_id] = "v2"
            return "v2"

    _INSIGHTS_VERSION_CACHE[client_id] = None
    return None


def _normalize_site_base_url(url: str) -> str:
    normalized = (url or "").strip().rstrip("/")
    if normalized.lower().endswith("/insights"):
        normalized = normalized[: -len("/insights")]
    return normalized


def _get_insights_runtime_config(client_id: str = "DEMO_CLIENT_123") -> dict:
    config = get_client_runtime_config(client_id)
    site_url = _normalize_site_base_url(config.get("erp_url") or ERP_URL or "")
    api_key = config.get("api_key") or ERP_API_KEY
    api_secret = config.get("api_secret") or ERP_API_SECRET
    if not site_url:
        raise Exception("Missing ERP URL for Insights export.")
    if not api_key or not api_secret:
        raise Exception("Missing ERP API credentials for Insights export.")
    return {
        "site_url": site_url,
        "api_key": api_key,
        "api_secret": api_secret,
    }


async def get_or_create_workbook(client_id: str = "DEMO_CLIENT_123"):
    """Finds or creates the 'ERP AI Reports' workbook in Frappe Insights."""
    config = _get_insights_runtime_config(client_id)
    headers = {
        "Authorization": f"token {config['api_key']}:{config['api_secret']}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{config['site_url']}/api/resource/Insights Workbook",
            headers=headers,
            params={
                "filters": f'[["title", "=", "{WORKBOOK_TITLE}"]]',
                "fields": '["name"]'
            }
        )
        data = res.json().get("data", [])
        if data:
            return data[0]["name"]
        
        wb_data = {
            "title": WORKBOOK_TITLE
        }
        res_create = await client.post(
            f"{config['site_url']}/api/resource/Insights Workbook",
            headers=headers,
            json=wb_data
        )
        
        if res_create.status_code == 200:
            return res_create.json().get("data", {}).get("name")
            
        raise Exception(f"Failed to create Insights Workbook: {res_create.text}")

async def export_query_to_insights(title: str, sql: str, client_id: str = "DEMO_CLIENT_123"):
    """Creates a new Insights Query v3 record with the provided SQL."""
    insights_version = await _get_insights_version(client_id)
    if insights_version != "v3":
        raise Exception(
            "Frappe Insights v3 is required for dashboard export. "
            "Please install or upgrade the Insights app to version 3 on your ERPNext instance."
        )
    config = _get_insights_runtime_config(client_id)
    workbook_name = await get_or_create_workbook(client_id=client_id)
    
    if not title:
        title = f"AI Query - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
    headers = {
        "Authorization": f"token {config['api_key']}:{config['api_secret']}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    query_data = {
        "title": title,
        "workbook": workbook_name,
        "is_native_query": 1,
        "is_script_query": 0,
        "is_builder_query": 0,
        "use_live_connection": 1,
        "operations": [
            {
                "type": "sql",
                "raw_sql": sql,
                "name": "Query",
                "data_source": "Site DB"
            }
        ]
    }
    
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{config['site_url']}/api/resource/Insights Query v3",
            headers=headers,
            json=query_data
        )
        
        if res.status_code == 200:
            doc_name = res.json().get("data", {}).get("name")
            return doc_name
        
        raise Exception(f"Failed to export query to Insights: {res.text}")

async def get_all_dashboards(client_id: str = "DEMO_CLIENT_123"):
    """Fetches a list of all Insights Dashboards available in the system."""
    config = _get_insights_runtime_config(client_id)
    headers = {
        "Authorization": f"token {config['api_key']}:{config['api_secret']}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{config['site_url']}/api/resource/Insights Dashboard v3",
            headers=headers,
            params={
                "fields": '["name", "title"]',
                "limit_page_length": 100,
                "order_by": "creation desc"
            }
        )
        
        if res.status_code == 200:
            return res.json().get("data", [])
        return []

async def export_chart_and_dashboard_to_insights(title: str, sql: str, chart_type: str, dashboard_name: str, x_col: str = None, y_cols: list = None, client_id: str = "DEMO_CLIENT_123"):
    """
    End-to-end export:
    1. Creates a native SQL Query v3 with type:"sql" operations
    2. Creates a Chart v3 linked to the query (query only, NO data_query)
    3. Appends to or creates Dashboard v3
    """
    insights_version = await _get_insights_version(client_id)
    if insights_version != "v3":
        raise Exception(
            "Frappe Insights v3 is required for dashboard export. "
            "Please install or upgrade the Insights app to version 3 on your ERPNext instance."
        )
    config = _get_insights_runtime_config(client_id)
    headers = {
        "Authorization": f"token {config['api_key']}:{config['api_secret']}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    workbook_name = await get_or_create_workbook(client_id=client_id)
    query_name = await export_query_to_insights(title, sql, client_id=client_id)
    if not query_name:
        raise Exception("Failed to create query")
    
    print(f"[DEBUG] Created query: {query_name}")
    
    x_col = None
    y_series_raw = []
    available_columns = []
    
    try:
        from erp_client import run_query as erp_run_query
        introspect_sql = sql.rstrip().rstrip(";")
        sql_lower = introspect_sql.lower()
        if " limit " not in sql_lower:
            introspect_sql += " LIMIT 5"
        
        result_sample = await erp_run_query(introspect_sql, client_id=client_id)
        sample_rows = result_sample.get("message", [])
        if sample_rows and len(sample_rows) > 0:
            available_columns = list(sample_rows[0].keys())
        
        from ai_engine import determine_insights_chart_config
        ai_config = determine_insights_chart_config(sql, sample_rows)
        if ai_config:
            print(f"[DEBUG] AI decided Config: {ai_config}")
            # Validate X column
            if ai_config.get("x_col") in available_columns:
                x_col = ai_config.get("x_col")
            
            # Validate and filter Y series
            for s in ai_config.get("y_series", []):
                if s.get("column") in available_columns:
                    y_series_raw.append(s)
            
            chart_type = ai_config.get("chart_type", chart_type)
    except Exception as e:
        print(f"[DEBUG] AI Config Generation failed: {e}")
        
    # Manual Fallback Introspection if AI failed or returned invalid columns
    if not x_col or not y_series_raw:
        fallback_x = None
        fallback_y_cols = []
        
        try:
            if available_columns and len(sample_rows) > 0:
                row = sample_rows[0]
                print(f"[DEBUG] Introspecting keys: {available_columns}")
                for k in available_columns:
                    v = row[k]
                    # Check if numeric (int, float) and not a common ID/Boolean
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        k_lower = k.lower()
                        # Skip columns that look like identifiers or phone numbers
                        if not any(stop in k_lower for stop in ["mobile", "phone", "id", "idx", "pincode", "zip"]) and k_lower not in ["name", "id", "idx"]:
                            fallback_y_cols.append(k)
                        else:
                            print(f"[DEBUG] Skipping likely identifier column: {k}")
                    elif fallback_x is None:
                        fallback_x = k
            
            if fallback_x and not x_col:
                x_col = fallback_x
                print(f"[DEBUG] Selected fallback X column: {x_col}")
                
            if fallback_y_cols and not y_series_raw:
                for y in fallback_y_cols:
                    y_series_raw.append({"column": y, "aggregation": "sum"})
                print(f"[DEBUG] Selected fallback Y columns: {fallback_y_cols}")
                    
        except Exception as e:
            print(f"[DEBUG] Fallback introspection failed: {e}")
    
    # Static Fallback if still nothing
    if not x_col:
        x_col = available_columns[0] if available_columns else "name"
    if not y_series_raw:
        # Pick the first numeric column we didn't use for X from available_columns
        for k in available_columns:
            if k == x_col: continue
            # Check if likely numeric
            first_val = sample_rows[0].get(k) if sample_rows else None
            if isinstance(first_val, (int, float)) and not isinstance(first_val, bool):
                y_series_raw.append({"column": k, "aggregation": "sum"})
                break
        
        # Absolute fallback if no numeric columns found
        if not y_series_raw:
            # If no numeric columns, use the X column itself with a 'count' aggregation
            y_series_raw = [{"column": x_col, "aggregation": "count"}]
            
    print(f"[DEBUG] Final Chart Columns to export: x_col={x_col}, y_series={y_series_raw}")
    
    frappe_chart_type = "Bar"
    ct = chart_type.lower()
    if "line" in ct:
        frappe_chart_type = "Line"
    elif "pie" in ct:
        frappe_chart_type = "Pie"
    elif "doughnut" in ct or "donut" in ct:
        frappe_chart_type = "Donut"
    elif "number" in ct or "kpi" in ct or "metric" in ct:
        frappe_chart_type = "Number"
    elif "area" in ct:
        frappe_chart_type = "Area"
    
    # Format the y_series for Frappe Insights JSON
    formatted_y_series = []
    for series in y_series_raw:
        agg = series.get("aggregation", "sum")
        col = series.get("column")
        
        # Determine aggregation based on column name if not specified or if sum is too generic
        col_lower = col.lower()
        if "count" in col_lower and agg == "sum":
            agg = "count"
        elif ("avg" in col_lower or "average" in col_lower) and agg == "sum":
            agg = "avg"
            
        formatted_y_series.append({
            "measure": {
                "aggregation": agg,
                "column_name": col,
                "data_type": "Decimal",
                "measure_name": f"{agg}_of_{col}"
            }
        })
    y_series = formatted_y_series
    
    chart_config = {
        "filters": {"filters": [], "logical_operator": "And"},
        "limit": 100,
        "order_by": [],
        "x_axis": {
            "dimension": {
                "column_name": x_col,
                "data_type": "String",
                "dimension_name": x_col,
                "label": x_col,
                "value": x_col
            }
        },
        "y_axis": {
            "series": y_series,
            "stack": True
        }
    }
    
    if frappe_chart_type == "Number":
        chart_config["number"] = {
            "measure": y_series[0]["measure"] if y_series else {}
        }
    
    chart_data = {
        "title": title,
        "workbook": workbook_name,
        "query": query_name,
        "chart_type": frappe_chart_type,
        "config": json.dumps(chart_config)
    }
    
    async with httpx.AsyncClient() as client:
        c_res = await client.post(
            f"{config['site_url']}/api/resource/Insights Chart v3",
            headers=headers,
            json=chart_data
        )
        if c_res.status_code != 200:
            raise Exception(f"Failed to create Chart: {c_res.text}")
            
        created_chart_name = c_res.json().get("data", {}).get("name")
    
    existing_doc_name = None
    async with httpx.AsyncClient() as client:
        dash_list_res = await client.get(
            f"{config['site_url']}/api/resource/Insights Dashboard v3",
            headers=headers,
            params={"limit_page_length": 100}
        )
        if dash_list_res.status_code == 200:
            for dash in dash_list_res.json().get("data", []):
                dash_full = await client.get(
                    f"{config['site_url']}/api/resource/Insights Dashboard v3/{dash['name']}",
                    headers=headers
                )
                if dash_full.status_code == 200:
                    dash_doc = dash_full.json().get("data", {})
                    if dash_doc.get("title") == dashboard_name:
                        existing_doc_name = dash["name"]
                        break
    
    import random, string
    random_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    new_item = {
        "chart": created_chart_name,
        "layout": {
            "i": 1,
            "id": random_id,
            "moved": False,
            "w": 10,
            "h": 6,
            "x": 0,
            "y": 0
        },
        "type": "chart"
    }
    dash_doc_name = None
    
    async with httpx.AsyncClient() as client:
        if existing_doc_name:
            full_res = await client.get(
                f"{config['site_url']}/api/resource/Insights Dashboard v3/{existing_doc_name}",
                headers=headers
            )
            if full_res.status_code == 200:
                full_doc = full_res.json().get("data", {})
                try:
                    items = json.loads(full_doc.get("items") or "[]")
                except Exception:
                    items = []
                
                max_i = max([item.get("layout", {}).get("i", 0) for item in items], default=0)
                max_y = max([item.get("layout", {}).get("y", 0) + item.get("layout", {}).get("h", 6) for item in items], default=0)
                new_item["layout"]["i"] = max_i + 1
                new_item["layout"]["y"] = max_y
                items.append(new_item)
                
                u_res = await client.put(
                    f"{config['site_url']}/api/resource/Insights Dashboard v3/{existing_doc_name}",
                    headers=headers,
                    json={"items": items}
                )
                if u_res.status_code != 200:
                    raise Exception(f"Failed to update Dashboard: {u_res.text}")
            
            dash_doc_name = existing_doc_name
        else:
            d_res = await client.post(
                f"{config['site_url']}/api/resource/Insights Dashboard v3",
                headers=headers,
                json={
                    "title": dashboard_name,
                    "workbook": workbook_name,
                    "items": [new_item]
                }
            )
            if d_res.status_code != 200:
                raise Exception(f"Failed to create new Dashboard: {d_res.text}")
                
            dash_doc_name = d_res.json().get("data", {}).get("name")
    
    return {
        "status": "success",
        "chart_name": created_chart_name,
        "dashboard_name": dash_doc_name,
        "workbook_name": workbook_name,
        "url": f"{config['site_url']}/insights/workbook/{workbook_name}/dashboard/{dash_doc_name}"
    }
