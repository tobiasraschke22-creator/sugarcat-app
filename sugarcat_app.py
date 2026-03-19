import streamlit as st
import pandas as pd
import requests
import time
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
        
        if not records:
            default_list = [{"Supermarkt": "DM", "brand": "Dein Bestes", "name": "Klassisch Rind", "store_type": "dm", "barcode": "4058172322587"}]
            save_watchlist(default_list)
            return default_list
        return records
    except Exception as e:
        st.error("Konnte Google Sheets nicht laden. Bitte Secrets prüfen!")
        return []

def save_watchlist(watchlist):
    try:
        client = get_gsheet_client()
        sheet = client.open("SugarCat_Datenbank").sheet1
        sheet.clear()
        
        df = pd.DataFrame(watchlist)
        # Sende die aktualisierten Daten an Google Sheets
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

def refresh_database(product_list):
    updated_register = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    for idx, item in enumerate(product_list):
        status_text.text(f"🔍 Suche Live-Daten für: {item['brand']}...")
        data = fetch_from_api(item.get('barcode', ''))
        
        updated_item = item.copy()
        if data:
            nfe_dm, is_safe = calculate_nfe_dm(data['protein'], data['fat'], data['ash'], data['fiber'], data['moisture'])
            updated_item.update({"NFE i.Tr. (%)": nfe_dm, "Status": "✅ Top" if is_safe else "❌ Achtung", "Quelle": data['source']})
        else:
            updated_item.update({"NFE i.Tr. (%)": "N/A", "Status": "⚠️ Keine Daten", "Quelle": "Nicht gefunden"})
            
        updated_register.append(updated_item)
        progress_bar.progress((idx + 1) / len(product_list))
        time.sleep(0.5)
        
    status_text.text("✅ Abgleich beendet!")
    time.sleep(1)
    status_text.empty()
    progress_bar.empty()
    return updated_register

# ==========================================
# 2. BENUTZEROBERFLÄCHE (UI)
# ==========================================
st.set_page_config(page_title="SugarCat Calc", page_icon="🐾", layout="centered")
st.title("🐾 SugarCat Calc")
st.markdown("Der smarte **NFE-Rechner** für Diabetiker-Katzen.")

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = load_watchlist()
if 'register_data' not in st.session_state:
    st.session_state.register_data = []

with st.expander("➕ Neues Futter hinzufügen"):
    with st.form("add_product_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            new_supermarket = st.selectbox("Supermarkt", ["DM", "Rossmann", "Lidl", "Aldi", "Fressnapf", "Sonstige"])
            new_brand = st.text_input("Marke (z.B. Winston)")
        with col2:
            new_name = st.text_input("Sorte (z.B. Pâté Rind)")
            new_barcode = st.text_input("Barcode (Pflicht für API!)")
            
        if st.form_submit_button("Speichern") and new_brand and new_name:
            st.session_state.watchlist.append({
                "Supermarkt": new_supermarket, "brand": new_brand, "name": new_name,
                "store_type": new_supermarket.lower(), "barcode": new_barcode
            })
            save_watchlist(st.session_state.watchlist)
            st.success("Gespeichert in Google Sheets!")

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
if st.button("🔄 Live-Daten abrufen", use_container_width=True):
    with st.spinner('Verbinde mit Servern...'):
        st.session_state.register_data = refresh_database(st.session_state.watchlist)

if st.session_state.register_data:
    df = pd.DataFrame(st.session_state.register_data)
    df_display = df[['Supermarkt', 'brand', 'name', 'NFE i.Tr. (%)', 'Status', 'Quelle']]
    df_display.columns = ['Markt', 'Marke', 'Sorte', 'NFE (%)', 'Bewertung', 'Quelle']
    
    def color_status(val):
        if 'Top' in str(val): return 'background-color: #a8e6cf'
        elif 'Achtung' in str(val): return 'background-color: #ff8b94'
        elif 'Keine Daten' in str(val): return 'background-color: #ffe082'
        return ''
        
    st.dataframe(df_display.style.map(color_status, subset=['Bewertung']), use_container_width=True, hide_index=True)
else:
    st.info("Klicke auf 'Live-Daten abrufen', um die Werte zu berechnen.")