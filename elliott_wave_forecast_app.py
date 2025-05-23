import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
import datetime

# ------------------ Data Fetching ------------------
def get_data(ticker, period="6mo", interval="1d"):
    df = yf.download(ticker, period=period, interval=interval)
    df = df.dropna()
    return df

# ------------------ Zigzag Pivot Detection ------------------
def zigzag_detector(prices, threshold=0.035):
    pivots = []
    last = prices[0]
    trend_up = None
    last_index = 0

    for i in range(1, len(prices)):
        change = (prices[i] - last) / last
        if trend_up is None:
            trend_up = change > 0
        if trend_up and change <= -threshold:
            pivots.append((last_index, last))
            trend_up = False
            last = prices[i]
            last_index = i
        elif not trend_up and change >= threshold:
            pivots.append((last_index, last))
            trend_up = True
            last = prices[i]
            last_index = i
    pivots.append((len(prices) - 1, prices[-1]))
    return pivots

# ------------------ Feature Extraction ------------------
def extract_wave_features(prices, pivots):
    waves = []
    for i in range(len(pivots) - 1):
        i1, p1 = pivots[i]
        i2, p2 = pivots[i + 1]
        duration = i2 - i1
        change = (p2 - p1) / p1
        slope = change / duration if duration != 0 else 0
        volatility = np.std(prices[i1:i2]) if duration > 0 else 0
        direction = 1 if change > 0 else 0
        waves.append({
            'Start': i1, 'End': i2,
            'Change': change,
            'Duration': duration,
            'Slope': slope,
            'Volatility': volatility,
            'Direction': direction
        })
    return pd.DataFrame(waves)

# ------------------ Label and Train ------------------
def label_and_prepare(df):
    df['Label'] = ['Wave_' + str(i + 1) if i < 5 else 'Unknown' for i in range(len(df))]
    X, y_class, y_reg = [], [], []
    for i in range(len(df) - 5):
        window = df.iloc[i:i+5]
        features = []
        for j in range(4):
            wave = window.iloc[j]
            features += [wave['Change'], wave['Duration'], wave['Slope'], wave['Volatility'], wave['Direction']]
        X.append(features)
        y_class.append(window.iloc[4]['Label'])
        y_reg.append(window.iloc[4]['Change'])
    return np.array(X), y_class, y_reg

# ------------------ Triangle Pattern Detection ------------------
def detect_triangles(pivots):
    patterns = []
    for i in range(len(pivots) - 4):
        sub = pivots[i:i + 5]
        highs = [p[1] for j, p in enumerate(sub) if j % 2 == 0]
        lows = [p[1] for j, p in enumerate(sub) if j % 2 != 0]
        if all(highs[k] < highs[k-1] for k in range(1, len(highs))) and all(lows[k] > lows[k-1] for k in range(1, len(lows))):
            patterns.append((sub[2][0], "Contracting Triangle"))
        elif highs[-1] > highs[0] and lows[-1] > lows[0]:
            patterns.append((sub[2][0], "Running Triangle"))
        elif highs[-1] == highs[0] or lows[-1] == lows[0]:
            patterns.append((sub[2][0], "Barrier Triangle"))
    return patterns

# ------------------ Forecasting ------------------
def forecast(X, model_class, model_reg, latest_features):
    pred_class = model_class.predict([latest_features])[0]
    pred_change = model_reg.predict([latest_features])[0]
    return pred_class, pred_change

# ------------------ Streamlit UI ------------------
st.set_page_config("Ultimate Elliott Wave AI", layout="wide")
st.title("Ultimate Elliott Wave AI Forecaster")

ticker = st.sidebar.text_input("Ticker Symbol", "AAPL")
period = st.sidebar.selectbox("Data Period", ["1mo", "3mo", "6mo", "1y", "2y"], index=2)
interval = st.sidebar.selectbox("Interval", ["15m", "30m", "1h", "1d", "1wk"], index=3)
threshold = st.sidebar.slider("Zigzag Threshold (%)", 1.0, 10.0, 3.5) / 100

if st.sidebar.button("Run Analysis"):
    df = get_data(ticker, period=period, interval=interval)
    prices = df['Close'].values
    pivots = zigzag_detector(prices, threshold)
    waves_df = extract_wave_features(prices, pivots)
    triangles = detect_triangles(pivots)

    X, y_class, y_reg = label_and_prepare(waves_df)
    if len(X) < 2:
        st.error("Not enough data to train AI. Adjust the period or interval.")
    else:
        model_class = RandomForestClassifier(n_estimators=100)
        model_reg = RandomForestRegressor(n_estimators=100)
        model_class.fit(X, y_class)
        model_reg.fit(X, y_reg)

        latest_input = X[-1]
        label_pred, price_pred = forecast(X, model_class, model_reg, latest_input)

        st.subheader("Forecast Results")
        st.success(f"Predicted Wave Label: {label_pred}")
        st.success(f"Predicted % Price Change: {price_pred * 100:.2f}%")

        # Plot
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index, y=df['Close'], name='Price', line=dict(color='blue')))
        for idx, price in pivots:
            fig.add_trace(go.Scatter(x=[df.index[idx]], y=[price], mode='markers', marker=dict(color='red'), showlegend=False))
        for idx, label in triangles:
            fig.add_trace(go.Scatter(x=[df.index[idx]], y=[df['Close'][idx]], mode='text', text=[label], textposition="top center", showlegend=False))

        forecast_price = prices[pivots[-1][0]] * (1 + price_pred)
        fig.add_shape(type="line",
                      x0=df.index[pivots[-1][0]],
                      y0=prices[pivots[-1][0]],
                      x1=df.index[min(len(df)-1, pivots[-1][0] + 5)],
                      y1=forecast_price,
                      line=dict(color="green", dash="dot"))

        fig.update_layout(title=f"{ticker} - Elliott Wave Forecast", height=600)
        st.plotly_chart(fig, use_container_width=True)

        # Save history
        if "forecast_log" not in st.session_state:
            st.session_state.forecast_log = []
        st.session_state.forecast_log.append({
            "Time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Ticker": ticker,
            "Label": label_pred,
            "Forecast %": round(price_pred * 100, 2)
        })

        st.subheader("Forecast History")
        st.dataframe(pd.DataFrame(st.session_state.forecast_log))
