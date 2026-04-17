import pandas as pd
import numpy as np
from statsmodels.tsa.holtwinters import ExponentialSmoothing

def generate_forecast(data: list[dict], date_col: str, target_col: str, periods: int = 6) -> list[dict]:
    """
    Generates a forecast for the given time-series data using Holt-Winters Exponential Smoothing.
    
    Args:
        data: List of dictionaries representing rows of data.
        date_col: The name of the column containing dates (e.g., 'Month', 'Date').
        target_col: The name of the column containing the value to forecast (e.g., 'Total', 'Sales').
        periods: Number of future periods to forecast.
        
    Returns:
        List of dictionaries containing the original data and the forecasted data.
    """
    if not data or len(data) < 3:
        # Not enough data for exponential smoothing
        return data

    try:
        df = pd.DataFrame(data)
        
        # Convert to datetime and set as index
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.set_index(date_col)
        
        # Ensure target column is numeric
        df[target_col] = pd.to_numeric(df[target_col], errors='coerce').fillna(0)
        
        # Determine frequency (usually MS for Month Start)
        df = df.resample('MS').sum().fillna(0) # Fill missing months with 0
        
        values = df[target_col].values
        
        # If all zeros or very little data, return original
        if np.all(values == 0) or len(values) < 3:
            return data
            
        # Fit Holt-Winters model. 
        # Since business data often has trends but might not have strict seasonality with few data points,
        # we try with trend. If it fails (e.g., negative values), we fallback to simple smoothing.
        try:
            model = ExponentialSmoothing(values, trend='add', seasonal=None, initialization_method="estimated")
            fit_model = model.fit()
            forecast = fit_model.forecast(periods)
        except Exception as e:
            # Fallback to simple exponential smoothing if additive trend fails
            print(f"[Forecaster] Warning: Additive trend failed ({e}), falling back to simple smoothing.")
            model = ExponentialSmoothing(values, initialization_method="estimated")
            fit_model = model.fit()
            forecast = fit_model.forecast(periods)

        # Generate future dates
        last_date = df.index[-1]
        future_dates = pd.date_range(start=last_date + pd.DateOffset(months=1), periods=periods, freq='MS')
        
        # Build result list
        result = []
        
        # Add historical data
        for date, row in df.iterrows():
            result.append({
                date_col: date.strftime('%Y-%m'),
                target_col: float(row[target_col]),
                'Type': 'Actual'
            })
            
        # Add forecasted data
        for i, date in enumerate(future_dates):
            val = float(forecast[i])
            # Prevent negative forecasts for sales/revenue
            if val < 0: val = 0.0
            
            result.append({
                date_col: date.strftime('%Y-%m'),
                target_col: round(val, 2),
                'Type': 'Forecast'
            })
            
        return result
        
    except Exception as e:
        print(f"[Forecaster] Error generating forecast: {e}")
        return data # Return original data on failure

if __name__ == '__main__':
    # Test
    test_data = [
        {'Month': '2023-01', 'Sales': 100},
        {'Month': '2023-02', 'Sales': 120},
        {'Month': '2023-03', 'Sales': 130},
        {'Month': '2023-05', 'Sales': 150}, # Missing april
    ]
    res = generate_forecast(test_data, 'Month', 'Sales', periods=3)
    for r in res:
        print(r)
