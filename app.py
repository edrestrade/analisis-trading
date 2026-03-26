import streamlit as st
import pandas as pd
import yfinance as yf
import datetime
from datetime import timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Análisis Maestro v12.3", layout="wide")

st.title("📊 Script de Análisis Maestro v12.3")
st.markdown("---")

# --- BARRA LATERAL (INPUTS) ---
with st.sidebar:
    st.header("🛠️ Configuración")
    ticker_input = st.text_input("Ticker", value="ASNS").upper().strip()
    day_1_input = st.date_input("Fecha Base (Day 1)", value=datetime.date(2026, 3, 4))
    extra_day_opt = st.selectbox("Extra Day", ["SI", "NO"])
    target_val = st.number_input("Target", value=4)
    
    st.markdown("---")
    btn_analizar = st.button("🚀 Iniciar Análisis Maestro")

# --- CONEXIÓN ALPACA (SECRETS) ---
try:
    # Estos valores se configuran en "Advanced Settings" > "Secrets" en Streamlit Cloud
    ALPACA_KEY = st.secrets["ALPACA_KEY"]
    ALPACA_SECRET = st.secrets["ALPACA_SECRET"]
    client = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)
except Exception:
    st.error("❌ Error: Llaves API no encontradas. Configura ALPACA_KEY y ALPACA_SECRET en los Secrets de Streamlit.")
    st.stop()

# --- LÓGICA PRINCIPAL ---
if btn_analizar:
    try:
        with st.spinner(f"Procesando {ticker_input}..."):
            # Procesamiento de fechas
            day_1_req = pd.to_datetime(day_1_input)

            # 1. DESCARGA Y CÁLCULOS TÉCNICOS
            ticker = yf.Ticker(ticker_input)
            df_long = ticker.history(start=day_1_req - timedelta(days=750),
                                    end=day_1_req + timedelta(days=120),
                                    auto_adjust=True,
                                    actions=True).tz_localize(None)

            if df_long.empty:
                st.error(f"❌ No se encontraron datos para {ticker_input} en yfinance.")
                st.stop()

            # Indicadores técnicos
            df_long['TR'] = pd.concat([df_long['High']-df_long['Low'],
                                       abs(df_long['High']-df_long['Close'].shift(1)),
                                       abs(df_long['Low']-df_long['Close'].shift(1))], axis=1).max(axis=1)
            df_long['ATR'] = df_long['TR'].rolling(window=14).mean()
            df_long['EMA50'] = df_long['Close'].ewm(span=50, adjust=False).mean()
            df_long['Vol_Avg_20'] = df_long['Volume'].shift(1).rolling(window=20).mean()

            # Ajustar Day 1 al día bursátil más cercano
            actual_day_1_date = df_long.index[df_long.index >= day_1_req][0]
            idx_1 = df_long.index.get_loc(actual_day_1_date)

            # Secuencia D0-D3
            d0, d1, d2_row = df_long.iloc[idx_1-1], df_long.iloc[idx_1], df_long.iloc[idx_1+1]
            d2_date = df_long.index[idx_1 + 1]
            d3_date = df_long.index[idx_1 + 2]

            # 2. VOLÚMENES ALPACA
            vol_ah_d2, vol_pm_d3 = 0, 0
            
            # AH D2
            req_ah = StockBarsRequest(symbol_or_symbols=ticker_input, timeframe=TimeFrame.Minute,
                                     start=d2_date.replace(hour=16, minute=1), end=d2_date.replace(hour=20, minute=0),
                                     adjustment="split")
            bars_ah = client.get_stock_bars(req_ah)
            if hasattr(bars_ah, 'df'):
                vol_ah_d2 = bars_ah.df['volume'].sum()

            # PM D3
            req_pm = StockBarsRequest(symbol_or_symbols=ticker_input, timeframe=TimeFrame.Minute,
                                     start=d3_date.replace(hour=4, minute=0), end=d3_date.replace(hour=9, minute=29),
                                     adjustment="split")
            bars_pm = client.get_stock_bars(req_pm)
            if hasattr(bars_pm, 'df'):
                vol_pm_d3 = bars_pm.df['volume'].sum()

            # D3 REGULAR (VWAP y Horas)
            req_d3 = StockBarsRequest(symbol_or_symbols=ticker_input, timeframe=TimeFrame.Minute,
                                     start=d3_date.replace(hour=9, minute=30), end=d3_date.replace(hour=16, minute=0),
                                     adjustment="split")
            bars_d3 = client.get_stock_bars(req_d3)
            h_h2, h_h1, vwap_o3, d3_open, d3_high = "N/A", "N/A", 0, 0, 0

            if hasattr(bars_d3, 'df'):
                df_m = bars_d3.df.reset_index()
                df_m['timestamp'] = pd.to_datetime(df_m['timestamp']).dt.tz_convert('America/New_York')
                if not df_m.empty:
                    d3_open, d3_high = df_m.iloc[0]['open'], df_m['high'].max()
                    df_m['tpv'] = ((df_m['high'] + df_m['low'] + df_m['close']) / 3) * df_m['volume']
                    vwap_o3 = df_m['tpv'].sum() / df_m['volume'].sum()
                    h_h2 = df_m[df_m['high'] > d2_row['High']].iloc[0]['timestamp'].strftime('%H:%M') if not df_m[df_m['high'] > d2_row['High']].empty else "N/A"
                    h_h1 = df_m[df_m['high'] > d1['High']].iloc[0]['timestamp'].strftime('%H:%M') if not df_m[df_m['high'] > d1['High']].empty else "N/A"

            # 3. MOMENTUM Y CORRIDAS
            vol_rel_val = d1['Volume'] / d1['Vol_Avg_20'] if d1['Vol_Avg_20'] > 0 else 0
            
            dias_sin_romper, ssr_list, idx_final_corrida = 0, [], idx_1
            for i in range(idx_1, len(df_long)):
                curr = df_long.iloc[i]
                prev_c = df_long.iloc[i-1]['Close']
                if ((curr['Low'] - prev_c) / prev_c) * 100 <= -10: ssr_list.append(f"D{i-idx_1+1}")
                if i > idx_1:
                    if curr['Low'] >= df_long.iloc[i-1]['Low']:
                        dias_sin_romper += 1
                        idx_final_corrida = i
                    else:
                        dia_rompe = f"DÍA {i - idx_1 + 1} (ROMPE MÍNIMOS)"; idx_final_corrida = i; break
            else: dia_rompe = "EN CORRIDA"

            # 4. DÍA ADICIONAL
            info = ticker.info
            ex_vol, ex_atr, ex_atr_ema, ex_oh, ex_ratio = "N/A", "N/A", "N/A", "N/A", "N/A"
            actual_target_extra = target_val if extra_day_opt == "SI" else 0
            if actual_target_extra > 0:
                try:
                    abs_idx = idx_1 + (actual_target_extra - 1)
                    day_t, day_p = df_long.iloc[abs_idx], df_long.iloc[abs_idx - 1]
                    ex_vol, ex_atr = f"{int(day_t['Volume']):,}", f"${day_p['ATR']:.4f}"
                    ex_atr_ema = f"{((day_p['ATR']/day_p['EMA50'])*100):.2f}%"
                    diff = day_t['High'] - day_t['Open']
                    ex_oh = f"${diff:.4f} [{((diff/day_t['Open'])*100):.2f}%]"
                    ex_ratio = round(diff / day_p['ATR'], 2)
                except: pass

            # 5. FORMATEO DE RESULTADOS
            f_c, f_c4, f_n, f_p = lambda v: f"${v:.2f}", lambda v: f"${v:.4f}", lambda v: f"{int(v):,}", lambda v: f"{v*100:.2f}%"
            oh_pct_d3 = ((d3_high - d3_open) / d3_open) * 100 if d3_open > 0 else 0

            # Crear diccionario para mostrar en tabla
            resultados = {
                "PARÁMETRO": ["FECHA", "STOCK", "EXCHANGE", "VOL-REL 20", "VOL 1", "SUMA EXT VOL", "CLOSE D1", "VWAP D3", "O-H D3", "RATIO D3", "CORRIDA TOTAL"],
                "VALOR": [
                    actual_day_1_date.strftime('%Y-%m-%d'), ticker_input, info.get('exchange', 'N/A'),
                    f"x{round(vol_rel_val, 1)}", f_n(d1['Volume']), f_n(vol_ah_d2 + vol_pm_d3),
                    f_c(d1['Close']), "ENCIMA" if d3_open > vwap_o3 else "DEBAJO",
                    f"{f_c4(d3_high - d3_open)} [{oh_pct_d3:.2f}%]",
                    round((d3_high - d3_open) / d2_row['ATR'], 2) if d2_row['ATR'] > 0 else 0,
                    f"L0: ${d0['Low']:.2f} | VAR: {((df_long.iloc[idx_1:idx_final_corrida+1]['High'].max()-d0['Low'])/d0['Low']*100):.2f}%"
                ]
            }

            # MOSTRAR EN PANTALLA
            st.success("✅ Análisis Completado")
            
            # Métricas destacadas
            m1, m2, m3 = st.columns(3)
            m1.metric("Volumen Relativo", f"x{round(vol_rel_val, 1)}")
            m2.metric("Ratio D3", round((d3_high - d3_open) / d2_row['ATR'], 2) if d2_row['ATR'] > 0 else 0)
            m3.metric("SSR Historial", ", ".join(ssr_list) if ssr_list else "INACTIVO")

            # Tabla completa
            st.write("### 📋 Resumen de Datos")
            st.table(pd.DataFrame(resultados))

            # Sección de Día Extra si aplica
            if actual_target_extra > 0:
                st.write(f"### ➕ Datos Día Extra (D{actual_target_extra})")
                st.json({"Vol": ex_vol, "ATR -1D": ex_atr, "O-H": ex_oh, "Ratio": ex_ratio})

    except Exception as e:
        st.error(f"⚠️ Ocurrió un error durante el análisis: {e}")
        st.info("Asegúrate de que la fecha seleccionada tenga datos suficientes (D+2 mínimo).")
