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
    # Configura estos en Settings > Secrets de Streamlit Cloud
    ALPACA_KEY = st.secrets["ALPACA_KEY"]
    ALPACA_SECRET = st.secrets["ALPACA_SECRET"]
    client = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)
except Exception:
    st.error("❌ Error: Llaves API no encontradas. Configura ALPACA_KEY y ALPACA_SECRET en los Secrets.")
    st.stop()

# --- LÓGICA PRINCIPAL ---
if btn_analizar:
    try:
        with st.spinner(f"Procesando {ticker_input}..."):
            # 1. PROCESAMIENTO DE FECHAS
            day_1_req = pd.to_datetime(day_1_input)

            # 2. DESCARGA Y CÁLCULOS TÉCNICOS
            ticker = yf.Ticker(ticker_input)
            df_long = ticker.history(start=day_1_req - timedelta(days=750),
                                    end=day_1_req + timedelta(days=120),
                                    auto_adjust=True,
                                    actions=True).tz_localize(None)

            if df_long.empty:
                st.error(f"❌ No se encontraron datos para {ticker_input}.")
                st.stop()

            # Indicadores técnicos
            df_long['TR'] = pd.concat([df_long['High']-df_long['Low'],
                                       abs(df_long['High']-df_long['Close'].shift(1)),
                                       abs(df_long['Low']-df_long['Close'].shift(1))], axis=1).max(axis=1)
            df_long['ATR'] = df_long['TR'].rolling(window=14).mean()
            df_long['EMA50'] = df_long['Close'].ewm(span=50, adjust=False).mean()
            df_long['Vol_Avg_20'] = df_long['Volume'].shift(1).rolling(window=20).mean()

            # Ajustar Day 1
            actual_day_1_date = df_long.index[df_long.index >= day_1_req][0]
            idx_1 = df_long.index.get_loc(actual_day_1_date)

            # Secuencia D0-D3
            d0, d1, d2_row = df_long.iloc[idx_1-1], df_long.iloc[idx_1], df_long.iloc[idx_1+1]
            d2_date, d3_date = df_long.index[idx_1 + 1], df_long.index[idx_1 + 2]

            # 3. VOLÚMENES ALPACA
            vol_ah_d2, vol_pm_d3 = 0, 0
            try:
                # AH D2
                req_ah = StockBarsRequest(symbol_or_symbols=ticker_input, timeframe=TimeFrame.Minute,
                                         start=d2_date.replace(hour=16, minute=1), end=d2_date.replace(hour=20, minute=0),
                                         adjustment="split")
                bars_ah = client.get_stock_bars(req_ah)
                if hasattr(bars_ah, 'df'): vol_ah_d2 = bars_ah.df['volume'].sum()

                # PM D3
                req_pm = StockBarsRequest(symbol_or_symbols=ticker_input, timeframe=TimeFrame.Minute,
                                         start=d3_date.replace(hour=4, minute=0), end=d3_date.replace(hour=9, minute=29),
                                         adjustment="split")
                bars_pm = client.get_stock_bars(req_pm)
                if hasattr(bars_pm, 'df'): vol_pm_d3 = bars_pm.df['volume'].sum()
            except: pass

            # D3 REGULAR
            h_h2, h_h1, vwap_o3, d3_open, d3_high = "N/A", "N/A", 0, 0, 0
            try:
                req_d3 = StockBarsRequest(symbol_or_symbols=ticker_input, timeframe=TimeFrame.Minute,
                                         start=d3_date.replace(hour=9, minute=30), end=d3_date.replace(hour=16, minute=0),
                                         adjustment="split")
                bars_d3 = client.get_stock_bars(req_d3)
                if hasattr(bars_d3, 'df'):
                    df_m = bars_d3.df.reset_index()
                    df_m['timestamp'] = pd.to_datetime(df_m['timestamp']).dt.tz_convert('America/New_York')
                    if not df_m.empty:
                        d3_open, d3_high = df_m.iloc[0]['open'], df_m['high'].max()
                        df_m['tpv'] = ((df_m['high'] + df_m['low'] + df_m['close']) / 3) * df_m['volume']
                        vwap_o3 = df_m['tpv'].sum() / df_m['volume'].sum()
                        h_h2 = df_m[df_m['high'] > d2_row['High']].iloc[0]['timestamp'].strftime('%H:%M') if not df_m[df_m['high'] > d2_row['High']].empty else "N/A"
                        h_h1 = df_m[df_m['high'] > d1['High']].iloc[0]['timestamp'].strftime('%H:%M') if not df_m[df_m['high'] > d1['High']].empty else "N/A"
            except: pass

            # 4. MOMENTUM Y CORRIDAS
            vol_rel_val = d1['Volume'] / d1['Vol_Avg_20'] if d1['Vol_Avg_20'] > 0 else 0
            dias_sin_romper, ssr_list, idx_final_corrida = 0, [], idx_1
            for i in range(idx_1, len(df_long)):
                curr, prev_c = df_long.iloc[i], df_long.iloc[i-1]['Close']
                if ((curr['Low'] - prev_c) / prev_c) * 100 <= -10: ssr_list.append(f"D{i-idx_1+1}")
                if i > idx_1:
                    if curr['Low'] >= df_long.iloc[i-1]['Low']:
                        dias_sin_romper += 1; idx_final_corrida = i
                    else:
                        dia_rompe = f"D{i - idx_1 + 1} (ROMPE)"; idx_final_corrida = i; break
            else: dia_rompe = "EN CORRIDA"

            corrida_res = f"D{dias_sin_romper + 1} (SIN ROMPER) - {dia_rompe}"
            ssr_final_str = ", ".join(ssr_list) if ssr_list else "INACTIVO"

            # 5. NUEVOS HIGHS
            nuevos_high_list, max_ref, ref_label = [], d2_row['High'], "D2"
            for i in range(idx_1 + 2, idx_final_corrida + 1):
                if df_long.iloc[i]['High'] > max_ref:
                    nuevos_high_list.append(f"D{i-idx_1+1}(R.{ref_label})")
                    max_ref, ref_label = df_long.iloc[i]['High'], f"D{i-idx_1+1}"
            nuevos_high_res = ", ".join(nuevos_high_list) if nuevos_high_list else "NINGUNO"

            # 6. DÍA EXTRA
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

            # 7. FORMATEO DE TODOS LOS CRITERIOS (47 CAMPOS)
            f_c, f_c4, f_n, f_p = lambda v: f"${v:.2f}", lambda v: f"${v:.4f}", lambda v: f"{int(v):,}", lambda v: f"{v*100:.2f}%"
            oh_pct_d3 = ((d3_high - d3_open) / d3_open) * 100 if d3_open > 0 else 0
            oh_d3_final = f"{f_c4(d3_high - d3_open)} [{oh_pct_d3:.2f}%]"

            cols = ["FECHA", "STOCK", "EXCHANGE", "COUNTRY", "SECTOR", "INDUSTRY", "NOTICIA", "MESES CASH", "MARKET CAP", "FLOAT", "INST.", "INSIDERS", "SHORT", "VOL-REL 20", "VOL 1", "VOL AH D2", "VOL PM D3", "SUMA EXT VOL", "LOW D0", "HIGH D1", "CLOSE D1", "C/O D1", "%LOWD0-CLOSED1", "% 0-1 H", "% 0-2 H", "% 0-3 O", "% 3-2 H", "% 3-1 H", "VWAP D3", "OVERHEAD", "HORA H2", "HORA H1", "SSR HISTORIAL", "INSIDE", "CORRIDA", "NUEVOS HIGH", "CORRIDA TOTAL", "ATR D2", "ATR% EMA", "O-H D3", "RATIO D3", "DÍA+", "VOL DÍA+", "ATR -1D+", "ATR% EMA -1D+", "O-H D+", "RATIO D+"]
            
            fila = [
                actual_day_1_date.strftime('%Y-%m-%d'), ticker_input, info.get('exchange', 'N/A'), info.get('country', 'N/A'),
                info.get('sector', 'N/A'), info.get('industry', 'N/A'), "N/A", "N/A",
                f_n(info.get('marketCap', 0)), f_n(info.get('floatShares', 0)),
                f_p(info.get('heldPercentInstitutions', 0)), f_p(info.get('heldPercentInsiders', 0)),
                f_p(info.get('shortPercentOfFloat', 0)), f"x{round(vol_rel_val, 1)}", f_n(d1['Volume']),
                f_n(vol_ah_d2), f_n(vol_pm_d3), f_n(vol_ah_d2 + vol_pm_d3),
                f_c(d0['Low']), f_c(d1['High']), f_c(d1['Close']),
                f"{((d1['Close']-d1['Open'])/d1['Open']*100):.2f}%", f"{((d1['Close']-d0['Low'])/d0['Low'])*100:.2f}%",
                f"{((d1['High']-d0['Low'])/d0['Low'])*100:.2f}%", f"{((d2_row['High']-d0['Low'])/d0['Low'])*100:.2f}%",
                f"{((d3_open-d0['Low'])/d0['Low'])*100:.2f}%", f"{((d2_row['High']-d3_open)/d3_open)*100:.2f}%",
                f"{((d1['High']-d3_open)/d3_open)*100:.2f}%", "ENCIMA" if d3_open > vwap_o3 else "DEBAJO", "LIMPIO", 
                h_h2, h_h1, ssr_final_str, f"D2: {'SÍ' if d3_high > d2_row['High'] else 'NO'}", 
                corrida_res, nuevos_high_res, f"L0: ${d0['Low']:.2f} | VAR: {((df_long.iloc[idx_1:idx_final_corrida+1]['High'].max()-d0['Low'])/d0['Low']*100):.2f}%",
                f_c4(d2_row['ATR']), f"{((d2_row['ATR']/d2_row['EMA50'])*100):.2f}%", oh_d3_final, round((d3_high - d3_open) / d2_row['ATR'], 2) if d2_row['ATR'] > 0 else 0,
                str(actual_target_extra), ex_vol, ex_atr, ex_atr_ema, ex_oh, ex_ratio
            ]

            # --- MOSTRAR RESULTADOS EN STREAMLIT ---
            st.success("✅ Análisis Maestro Finalizado")
            
            # 1. Métricas clave (Highlight)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Volumen Relativo", f"x{round(vol_rel_val, 1)}")
            m2.metric("Ratio D3", round((d3_high - d3_open) / d2_row['ATR'], 2) if d2_row['ATR'] > 0 else 0)
            m3.metric("SSR", ssr_final_str if len(ssr_list) < 3 else "MÚLTIPLE")
            m4.metric("VWAP D3", "ENCIMA" if d3_open > vwap_o3 else "DEBAJO")

            st.markdown("### 📋 Ficha Técnica de Análisis")
            
            # 2. Tabla resumida vertical (Ficha)
            df_final = pd.DataFrame({"CRITERIO": cols, "VALOR": fila})
            
            col_tabla_1, col_tabla_2 = st.columns(2)
            mitad = len(df_final) // 2
            
            with col_tabla_1:
                st.table(df_final.iloc[:mitad].set_index("CRITERIO"))
            with col_tabla_2:
                st.table(df_final.iloc[mitad:].set_index("CRITERIO"))

            # 3. Botón para descargar CSV (Opcional pero útil)
            csv = df_final.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Descargar Reporte CSV", csv, f"Analisis_{ticker_input}_{Day1}.csv", "text/csv")

    except Exception as e:
        st.error(f"⚠️ Error en el procesamiento: {e}")
