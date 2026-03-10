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
        # Native Python list — insights_query_v3.get_valid_dict() converts to JSON string internally
        # Sending json.dumps() here causes double-encoding which breaks apply_sql field parsing
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

async def export_chart_and_dashboard_to_insights(title: str, sql: str, chart_type: str, dashboard_name: str, x_col: str = None, y_cols: list = None):
    """
    End-to-end export:
    1. Creates a native SQL Query v3 with type:"sql" operations
    2. Creates a Chart v3 linked to the query (query only, NO data_query)
       - The Insights frontend auto-creates its own data_query wrapper
       - This wrapper correctly references our SQL query (no self-reference)
    3. Appends to or creates Dashboard v3
    """
    headers = {
        "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    workbook_name = await get_or_create_workbook()
    
    # Step 1: Create the SQL Query
    query_name = await export_query_to_insights(title, sql)
    if not query_name:
        raise Exception("Failed to create query")
    
    print(f"[DEBUG] Created query: {query_name}")
    
    # Step 2: Determine chart configuration using AI
    # We will fetch a small sample of data to help the AI
    x_col = None
    y_series = []
    
    try:
        from erp_client import run_query as erp_run_query
        introspect_sql = sql.rstrip().rstrip(";")
        sql_lower = introspect_sql.lower()
        if " limit " not in sql_lower:
            introspect_sql += " LIMIT 5"
        
        result_sample = await erp_run_query(introspect_sql)
        sample_rows = result_sample.get("message", [])
        
        from ai_engine import determine_insights_chart_config
        ai_config = determine_insights_chart_config(sql, sample_rows)
        if ai_config:
            print(f"[DEBUG] AI decided Config: {ai_config}")
            x_col = ai_config.get("x_col")
            y_series = ai_config.get("y_series", [])
            chart_type = ai_config.get("chart_type", chart_type)
    except Exception as e:
        print(f"[DEBUG] AI Config Generation failed: {e}")
        
    ai_x_col = x_col
    ai_y_cols = [s.get("column") for s in y_series] if y_series else y_cols
    
    x_col = None
    y_cols = []
    
    try:
        from erp_client import run_query as erp_run_query
        introspect_sql = sql.rstrip().rstrip(";")
        sql_lower = introspect_sql.lower()
        if " limit " not in sql_lower:
            introspect_sql += " LIMIT 1"
        
        result = await erp_run_query(introspect_sql)
        rows = result.get("message", [])
        
        if rows and isinstance(rows, list) and len(rows) > 0:
            row = rows[0]
            for k, v in row.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    y_cols.append(k)
                elif x_col is None:
                    x_col = k
                    
        print(f"[DEBUG] Introspection: x_col={x_col}, y_cols={y_cols}")
    except Exception as e:
        print(f"[DEBUG] Column introspection failed: {e}")
    
    # Fallback: parse column names from the SQL itself
    # Use the LAST SELECT...FROM match — for CTE queries (WITH...AS), the first SELECT
    # is inside the CTE and returns intermediate columns. The LAST SELECT is the
    # outermost query returning the final result columns.
    if not x_col or not y_cols:
        import re
        all_matches = re.findall(r"SELECT\s+(.+?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
        if all_matches:
            # Use the LAST match (outermost query)
            cols_str = all_matches[-1]
            col_parts = [c.strip() for c in cols_str.split(",")]
            parsed_cols = []
            for part in col_parts:
                alias_match = re.search(r"\bAS\s+(\w+)$", part, re.IGNORECASE)
                if alias_match:
                    parsed_cols.append(alias_match.group(1))
                else:
                    words = re.findall(r"[\w]+", part)
                    if words:
                        parsed_cols.append(words[-1])
            
            print(f"[DEBUG] SQL fallback parsed columns: {parsed_cols}")
            
            for c in parsed_cols:
                c_lower = c.lower()
                if any(kw in c_lower for kw in ["count", "sum", "total", "amount", "qty", "quantity", "revenue", "price", "avg", "predicted", "forecast", "sales"]):
                    if c not in y_cols:
                        y_cols.append(c)
                elif not x_col:
                    x_col = c
    
    # Override with AI provided columns if available
    if ai_x_col:
        x_col = ai_x_col
    if ai_y_cols:
        y_cols = ai_y_cols
        
    if not x_col:
        x_col = "name"
    if not y_cols:
        y_cols = ["total"]
        
    print(f"[DEBUG] Final Chart Columns to export: x_col={x_col}, y_cols={y_cols}")
    
    # Map chart type
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
    
    # Build Y-axis series with aggregation hints from column names if AI didn't provide series
    if not y_series:
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
    else:
        # Reformat AI series to Frappe expected schema
        formatted_series = []
        for series in y_series:
            agg = series.get("aggregation", "sum")
            col = series.get("column", "total")
            formatted_series.append({
                "measure": {
                    "aggregation": agg,
                    "column_name": col,
                    "data_type": "Decimal",
                    "measure_name": f"{agg}_of_{col}"
                }
            })
        y_series = formatted_series
    
    # Build chart config with proper X-axis and Y-axis
    # This is now safe because we do NOT set data_query — the Insights frontend
    # auto-creates its own data_query wrapper internally, so our SQL query's
    # operations stay untouched (no self-referencing overwrite).
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
    
    # Step 3: Create Chart — set ONLY "query", do NOT set "data_query"
    # The Insights frontend auto-creates its own data_query wrapper that
    # correctly sources from our SQL query without self-reference.
    chart_data = {
        "title": title,
        "workbook": workbook_name,
        "query": query_name,
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
    
    # Grid item for the dashboard — send as a native Python list.
    # Frappe's InsightsDashboardv3.get_valid_dict() converts list to JSON internally.
    # DO NOT pre-serialize as json.dumps() — it causes double-encoding.
    # DO NOT manually set linked_charts — Frappe's before_save() calls set_linked_charts()
    # which reads items and auto-populates linked_charts. Setting it manually conflicts.
    #
    # IMPORTANT: The items format MUST match Frappe Insights' internal structure:
    # - Layout properties (w, h, x, y, i, moved) go inside a "layout" sub-object
    # - "i" is a sequential integer (1, 2, 3...), NOT the chart name
    # - "id" is a short random string identifier
    # - "moved" must be set to false
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
                
                # Calculate next sequential "i" and place below existing items
                max_i = max([item.get("layout", {}).get("i", 0) for item in items], default=0)
                max_y = max([item.get("layout", {}).get("y", 0) + item.get("layout", {}).get("h", 6) for item in items], default=0)
                new_item["layout"]["i"] = max_i + 1
                new_item["layout"]["y"] = max_y
                items.append(new_item)
                
                u_res = await client.put(
                    f"{ERP_URL}/api/resource/Insights Dashboard v3/{existing_doc_name}",
                    headers=headers,
                    json={"items": items}   # Native list — Frappe sets linked_charts in before_save
                )
                if u_res.status_code != 200:
                    raise Exception(f"Failed to update Dashboard: {u_res.text}")
            
            dash_doc_name = existing_doc_name
        else:
            d_res = await client.post(
                f"{ERP_URL}/api/resource/Insights Dashboard v3",
                headers=headers,
                json={
                    "title": dashboard_name,
                    "workbook": workbook_name,
                    "items": [new_item]    # Native list — Frappe sets linked_charts in before_save
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
        "url": f"{ERP_URL}/insights/workbook/{workbook_name}/dashboard/{dash_doc_name}"
    }

