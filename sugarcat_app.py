import streamlit as st
import pandas as pd
import requests
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 0. SPEICHER-LOGIK (GOOGLE SHEETS)
# ==========================================
def get_gsheet_client():
    credentials_dict = dict(st.secrets["gcp_service_account"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
    return gspread.authorize(creds)

def load_watchlist():
    try:
        client = get_gsheet_client()
        sheet = client.open("SugarCat_Datenbank").sheet1
        records = sheet.get_all_records()
        return records if records else []
    except Exception as e:
        st.error("Konnte Google Sheets nicht laden. Bitte Secrets prüfen!")
        return []

def save_watchlist(watchlist):
    try:
        client = get_gsheet_client()
        sheet = client.open("SugarCat_Datenbank").sheet1
        sheet.clear()
        if watchlist:
            df = pd.DataFrame(watchlist)
            sheet.update(values=[df.columns.values.tolist()] + df.values.tolist(), range_name='A1')
    except Exception as e:
        st.error(f"Fehler beim Speichern: {e}")

# ==========================================
# 1. BACKEND-LOGIK (BERECHNUNG & API)
# ==========================================
def calculate_nfe_dm(protein, fat, ash, fiber, moisture):
    try:
        nfe_as_is = 100 - (protein + fat + ash + fiber + moisture)
        nfe_dm = (nfe_as_is / (100 - moisture)) * 100
        return round(nfe_dm, 2), nfe_dm < 10.0
    except (ZeroDivisionError, TypeError):
        return None, False

def fetch_from_api(barcode):
    if not barcode: return None
    url = f"https://world.openpetfoodfacts.org/api/v0/product/{barcode}.json"
    headers = {'User-Agent': 'SugarCatCalcApp/1.0'}
    try:
        response = requests.get(url, headers=headers, timeout=5).json()
        if response.get('status') == 1:
            nutriments = response.get('product', {}).get('nutriments', {})
            protein = nutriments.get('proteins_100g')
            fat = nutriments.get('fat_100g')
            if protein is None or fat is None: return None
            return {
                "protein": float(protein), "fat": float(fat),
                "ash": float(nutriments.get('ash_100g', 2.0)), 
                "fiber": float(nutriments.get('fiber_100g', 0.5)),
                "moisture": float(nutriments.get('moisture_100g', 80.0)),
                "source": "🌐 Live-API"
            }
        return None
    except: return None

# ==========================================
# 2. BENUTZEROBERFLÄCHE (UI)
# ==========================================
st.set_page_config(page_title="SugarCat Calc", page_icon="🐾", layout="centered")
st.title("🐾 SugarCat Calc")
st.markdown("Der smarte **NFE-Rechner** für Diabetiker-Katzen.")

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = load_watchlist()

with st.expander("➕ Neues Futter hinzufügen & scannen", expanded=True):
    with st.form("add_product_form", clear_on_submit=True):
        st.markdown("**1. Allgemeine Infos**")
        col1, col2 = st.columns(2)
        with col1:
            new_supermarket = st.selectbox("Supermarkt", ["DM", "Rossmann", "Lidl", "Aldi", "Fressnapf", "Sonstige"])
            new_brand = st.text_input("Marke (z.B. Winston)*")
        with col2:
            new_name = st.text_input("Sorte (z.B. Pâté Rind)*")
            new_barcode = st.text_input("Barcode (für Auto-Suche)")
            
        st.markdown("---")
        st.markdown("**2. Manuelle Eingabe (Optional, falls Barcode unbekannt)**")
        st.caption("Tippe hier die %-Werte von der Dose ab, wenn die API das Futter nicht kennt.")
        
        col3, col4, col5 = st.columns(3)
        with col3:
            man_protein = st.number_input("Rohprotein (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
            man_fat = st.number_input("Rohfett (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
        with col4:
            man_ash = st.number_input("Rohasche (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
            man_fiber = st.number_input("Rohfaser (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
        with col5:
            man_moisture = st.number_input("Feuchtigkeit (%)", min_value=0.0, max_value=100.0, value=80.0, step=0.1)
            
        if st.form_submit_button("Speichern & Berechnen"):
            if new_brand and new_name:
                with st.spinner("Prüfe Daten..."):
                    # 1. Versuche API (falls Barcode vorhanden)
                    api_data = fetch_from_api(new_barcode)
                    
                    # 2. Entscheide, womit gerechnet wird
                    if api_data:
                        # Priorität 1: API hat was gefunden!
                        nfe_dm, is_safe = calculate_nfe_dm(api_data['protein'], api_data['fat'], api_data['ash'], api_data['fiber'], api_data['moisture'])
                        nfe_val = nfe_dm
                        status_val = "✅ Top" if is_safe else "❌ Achtung"
                        quelle_val = api_data['source']
                    elif man_protein > 0 and man_fat > 0:
                        # Priorität 2: API hat nichts, aber User hat manuell was eingetippt!
                        nfe_dm, is_safe = calculate_nfe_dm(man_protein, man_fat, man_ash, man_fiber, man_moisture)
                        nfe_val = nfe_dm
                        status_val = "✅ Top" if is_safe else "❌ Achtung"
                        quelle_val = "✍️ Manuell"
                    else:
                        # Priorität 3: Weder API noch manuelle Daten
                        nfe_val = "N/A"
                        status_val = "⚠️ Keine Daten"
                        quelle_val = "Fehlen"
                    
                    # 3. Speichern
                    new_entry = {
                        "Supermarkt": new_supermarket, "brand": new_brand, "name": new_name,
                        "store_type": new_supermarket.lower(), "barcode": new_barcode,
                        "NFE i.Tr. (%)": nfe_val, "Status": status_val, "Quelle": quelle_val
                    }
                    
                    st.session_state.watchlist.append(new_entry)
                    save_watchlist(st.session_state.watchlist)
                    st.success("Erfolgreich in der Datenbank gespeichert!")
                    time.sleep(1) # Kurze Pause, damit der User die grüne Box sieht
                    st.rerun()
            else:
                st.warning("Bitte mindestens Marke und Sorte (oben mit *) ausfüllen.")

with st.expander("🗑️ Futter löschen"):
    if st.session_state.watchlist:
        options = [f"{i['brand']} - {i['name']}" for i in st.session_state.watchlist]
        selected = st.selectbox("Welches Futter entfernen?", options)
        if st.button("Löschen"):
            idx = options.index(selected)
            deleted = st.session_state.watchlist.pop(idx)
            save_watchlist(st.session_state.watchlist)
            st.success(f"{deleted['brand']} gelöscht!")
            st.rerun()

st.subheader("🛒 Dein Supermarkt-Register")

if st.session_state.watchlist:
    df = pd.DataFrame(st.session_state.watchlist)
    if 'NFE i.Tr. (%)' not in df.columns:
        df['NFE i.Tr. (%)'] = "N/A"
        df['Status'] = "⚠️ Alt"
        df['Quelle'] = "-"

    df_display = df[['Supermarkt', 'brand', 'name', 'NFE i.Tr. (%)', 'Status', 'Quelle']]
    df_display.columns = ['Markt', 'Marke', 'Sorte', 'NFE (%)', 'Bewertung', 'Quelle']
    
    def color_status(val):
        if 'Top' in str(val): return 'background-color: #a8e6cf'
        elif 'Achtung' in str(val): return 'background-color: #ff8b94'
        elif 'Keine Daten' in str(val): return 'background-color: #ffe082'
        return ''
        
    st.dataframe(df_display.style.map(color_status, subset=['Bewertung']), use_container_width=True, hide_index=True)
else:
    st.info("Noch kein Futter gespeichert.")
