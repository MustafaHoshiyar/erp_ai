import os
import json
import httpx
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
ERP_URL = os.getenv("ERP_URL")
ERP_API_KEY = os.getenv("ERP_API_KEY")
ERP_API_SECRET = os.getenv("ERP_API_SECRET")

WORKBOOK_TITLE = "ERP AI Reports"

async def get_or_create_workbook():
    """Finds or creates the 'ERP AI Reports' workbook in Frappe Insights."""
    headers = {
        "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        # Check if workbook exists
        res = await client.get(
            f"{ERP_URL}/api/resource/Insights Workbook",
            headers=headers,
            params={
                "filters": f'[["title", "=", "{WORKBOOK_TITLE}"]]',
                "fields": '["name"]'
            }
        )
        data = res.json().get("data", [])
        if data:
            return data[0]["name"]
        
        # Create Workbook
        wb_data = {
            "title": WORKBOOK_TITLE
        }
        res_create = await client.post(
            f"{ERP_URL}/api/resource/Insights Workbook",
            headers=headers,
            json=wb_data
        )
        
        if res_create.status_code == 200:
            return res_create.json().get("data", {}).get("name")
            
        raise Exception(f"Failed to create Insights Workbook: {res_create.text}")

async def export_query_to_insights(title: str, sql: str):
    """Creates a new Insights Query v3 record with the provided SQL."""
    workbook_name = await get_or_create_workbook()
    
    # Format the title nicely if none is provided
    if not title:
        title = f"AI Query - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
    headers = {
        "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}",
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
        "operations": json.dumps([
            {
                "type": "sql",
                "raw_sql": sql,
                "name": "Query",
                "data_source": "Site DB"
            }
        ])
    }
    
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{ERP_URL}/api/resource/Insights Query v3",
            headers=headers,
            json=query_data
        )
        
        if res.status_code == 200:
            doc_name = res.json().get("data", {}).get("name")
            return doc_name
        
        raise Exception(f"Failed to export query to Insights: {res.text}")

async def get_all_dashboards():
    """Fetches a list of all Insights Dashboards available in the system."""
    headers = {
        "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        # Only fetch name and title, ordered by recency
        res = await client.get(
            f"{ERP_URL}/api/resource/Insights Dashboard v3",
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

async def export_chart_and_dashboard_to_insights(title: str, sql: str, chart_type: str, dashboard_name: str):
    """
    End-to-end export: 
    1. Creates Query v3
    2. Auto-detects columns by running SQL LIMIT 1
    3. Creates Chart v3 with fully-configured config JSON
    4. Appends to or creates Dashboard v3 with linked_charts
    """
    headers = {
        "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    workbook_name = await get_or_create_workbook()
    
    # 1. Create Query
    query_name = await export_query_to_insights(title, sql)
    
    # 2. Introspect SQL columns by running the actual SQL with LIMIT 1
    x_col = None
    y_cols = []
    
    try:
        from erp_client import run_query as erp_run_query
        introspect_sql = sql.rstrip().rstrip(";")
        # Safely add LIMIT 1 only if not already limited
        sql_lower = introspect_sql.lower()
        if " limit " not in sql_lower:
            introspect_sql += " LIMIT 1"
        
        result = await erp_run_query(introspect_sql)
        # The erp_client returns raw JSON from the Frappe API
        # The Frappe response is {"message": [{...row...}]}
        rows = result.get("message", [])
        
        if rows and isinstance(rows, list) and len(rows) > 0:
            row = rows[0]
            for k, v in row.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    y_cols.append(k)
                elif x_col is None:
                    x_col = k
                    
        print(f"[DEBUG] Introspection found: x_col={x_col}, y_cols={y_cols}")
    except Exception as e:
        print(f"[DEBUG] Column introspection failed: {e}")
    
    # If still no columns found, make smart guesses from the SQL itself
    if not x_col or not y_cols:
        import re
        # Try to extract SELECT-ed column names from the SQL
        select_match = re.search(r"SELECT\s+(.+?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
        if select_match:
            cols_str = select_match.group(1)
            col_parts = [c.strip() for c in cols_str.split(",")]
            parsed_cols = []
            for part in col_parts:
                # Handle "expr AS alias" and "expr alias"
                alias_match = re.search(r"\bAS\s+(\w+)$", part, re.IGNORECASE)
                if alias_match:
                    parsed_cols.append(alias_match.group(1))
                else:
                    # Just use last word
                    words = re.findall(r"[\w]+", part)
                    if words:
                        parsed_cols.append(words[-1])
            
            for c in parsed_cols:
                c_lower = c.lower()
                if any(num_word in c_lower for num_word in ["count", "sum", "total", "amount", "qty", "quantity", "revenue", "price"]):
                    if c not in y_cols:
                        y_cols.append(c)
                elif not x_col:
                    x_col = c
    
    # Absolute last resort defaults
    if not x_col:
        x_col = "name"
    if not y_cols:
        y_cols = ["total"]
    
    # Map chart type from Chart.js / AI labels to Frappe's supported types
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
    
    # Build y-axis series list — auto-detect aggregation from column name hints
    y_series = []
    for y in y_cols:
        y_lower = y.lower()
        if "count" in y_lower:
            agg = "count"
        elif "avg" in y_lower or "average" in y_lower:
            agg = "avg"
        else:
            agg = "sum"
            
        y_series.append({
            "measure": {
                "aggregation": agg,
                "column_name": y,
                "data_type": "Decimal",
                "measure_name": f"{agg}_of_{y}"
            }
        })
    
    # Build the full config object matching Frappe Insights' exact schema
    chart_config = {
        "filters": {
            "filters": [],
            "logical_operator": "And"
        },
        "limit": 100,
        "order_by": [],
        "x_axis": {
            "dimension": {
                "column_name": x_col,
                "data_type": "String",
                "dimension_name": x_col,
                "label": x_col,
                "value": x_col
            },
            "label_rotation": 0
        },
        "y_axis": {
            "series": y_series,
            "stack": True
        }
    }
    
    # For Number/KPI charts also set number config
    if frappe_chart_type == "Number":
        chart_config["number"] = {
            "measure": y_series[0]["measure"] if y_series else {}
        }
    
    # 3. Create Chart
    chart_data = {
        "title": title,
        "workbook": workbook_name,
        "query": query_name,
        "data_query": query_name,
        "chart_type": frappe_chart_type,
        "config": json.dumps(chart_config)
    }
    
    async with httpx.AsyncClient() as client:
        c_res = await client.post(
            f"{ERP_URL}/api/resource/Insights Chart v3",
            headers=headers,
            json=chart_data
        )
        if c_res.status_code != 200:
            raise Exception(f"Failed to create Chart: {c_res.text}")
            
        created_chart_name = c_res.json().get("data", {}).get("name")
    
    # 4. Handle Dashboard (Append or Create)
    # Fetch all dashboards and find matching by title
    existing_doc_name = None
    async with httpx.AsyncClient() as client:
        dash_list_res = await client.get(
            f"{ERP_URL}/api/resource/Insights Dashboard v3",
            headers=headers,
            params={"limit_page_length": 100}
        )
        if dash_list_res.status_code == 200:
            for dash in dash_list_res.json().get("data", []):
                dash_full = await client.get(
                    f"{ERP_URL}/api/resource/Insights Dashboard v3/{dash['name']}",
                    headers=headers
                )
                if dash_full.status_code == 200:
                    dash_doc = dash_full.json().get("data", {})
                    if dash_doc.get("title") == dashboard_name:
                        existing_doc_name = dash["name"]
                        break
    
    # Grid item for the dashboard — key ORDER matters for VueGridLayout!
    # Must match exact format of manually-created dashboards:
    # {"type": "chart", "chart": "...", "w": 6, "h": 4, "x": 0, "y": 0, "i": "..."}
    new_item = {
        "type": "chart",
        "chart": created_chart_name,
        "w": 6,
        "h": 4,
        "x": 0,
        "y": 0,
        "i": created_chart_name
    }
    # The linked_charts child row MUST include full Frappe child table doctype metadata
    # otherwise Frappe silently drops the row on save
    linked_chart_entry = {
        "chart": created_chart_name,
        "doctype": "Insights Dashboard Chart v3",
        "parenttype": "Insights Dashboard v3",
        "parentfield": "linked_charts"
    }
    dash_doc_name = None
    
    async with httpx.AsyncClient() as client:
        if existing_doc_name:
            # Fetch current dashboard to get existing items
            full_res = await client.get(
                f"{ERP_URL}/api/resource/Insights Dashboard v3/{existing_doc_name}",
                headers=headers
            )
            if full_res.status_code == 200:
                full_doc = full_res.json().get("data", {})
                try:
                    items = json.loads(full_doc.get("items") or "[]")
                except Exception:
                    items = []
                
                max_y = max([item.get("y", 0) + item.get("h", 4) for item in items], default=0)
                new_item["y"] = max_y
                items.append(new_item)
                
                existing_linked = full_doc.get("linked_charts", [])
                existing_linked.append(linked_chart_entry)
                
                # Serialize items as compact JSON string — this is how Frappe natively stores it
                items_json = json.dumps(items, separators=(',', ':'))
                
                u_res = await client.put(
                    f"{ERP_URL}/api/resource/Insights Dashboard v3/{existing_doc_name}",
                    headers=headers,
                    json={
                        "items": items_json,
                        "linked_charts": existing_linked
                    }
                )
                if u_res.status_code != 200:
                    raise Exception(f"Failed to update Dashboard: {u_res.text}")
            
            dash_doc_name = existing_doc_name
        else:
            d_data = {
                "title": dashboard_name,
                "workbook": workbook_name,
                # Compact JSON string — matches Frappe's native dashboard items storage format
                "items": json.dumps([new_item], separators=(',', ':')),
                "linked_charts": [linked_chart_entry]
            }
            d_res = await client.post(
                f"{ERP_URL}/api/resource/Insights Dashboard v3",
                headers=headers,
                json=d_data
            )
            if d_res.status_code != 200:
                raise Exception(f"Failed to create new Dashboard: {d_res.text}")
                
            dash_doc_name = d_res.json().get("data", {}).get("name")
    
    return {
        "status": "success",
        "chart_name": created_chart_name,
        "dashboard_name": dash_doc_name,
        "workbook_name": workbook_name,
        "url": f"{ERP_URL}/insights/workbook/{workbook_name}/dashboard/{dash_doc_name}"
    }

