import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

try:
    from forecaster import generate_forecast
    print("Import successful")
    
    test_data = [
        {'Month': '2025-10', 'Total Sales': 58002},
        {'Month': '2025-11', 'Total Sales': 15328},
        {'Month': '2025-12', 'Total Sales': 12020},
        {'Month': '2026-01', 'Total Sales': 7724},
    ]
    
    res = generate_forecast(test_data, 'Month', 'Total Sales', 6)
    print(f"Forecast successful, generated {len(res)} rows")
    for r in res[-2:]:
        print(r)
        
except Exception as e:
    import traceback
    traceback.print_exc()
