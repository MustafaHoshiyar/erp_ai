import json
import os
import sys
from datetime import datetime

import requests


def main():
    base_url = os.getenv("ERP_AI_BASE_URL", "http://127.0.0.1:8000")
    client_id = sys.argv[1] if len(sys.argv) > 1 else None

    params = {}
    if client_id:
        params["client_id"] = client_id

    response = requests.get(f"{base_url}/api/metrics/baseline", params=params, timeout=15)
    response.raise_for_status()
    payload = response.json()

    print(json.dumps(payload, indent=2))

    output_dir = os.path.join(os.path.dirname(__file__), "phase1_eval_assets")
    os.makedirs(output_dir, exist_ok=True)
    scope_label = client_id or "all_clients"
    output_path = os.path.join(
        output_dir,
        f"baseline_metrics_{scope_label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"\nSaved baseline snapshot to: {output_path}")


if __name__ == "__main__":
    main()
