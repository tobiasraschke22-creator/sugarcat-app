import streamlit as st
import pandas as pd
import requests
import time
import json
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
from PIL import Image

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
st.title("🐾 SugarCat Calc (AI Edition)")
st.markdown("Der smarte **NFE-Rechner** mit KI-Erkennung für Diabetiker-Katzen.")

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = load_watchlist()

# Initialisiere die manuellen Eingabewerte, damit die KI sie später überschreiben kann
if 'man_protein' not in st.session_state: st.session_state['man_protein'] = 0.0
if 'man_fat' not in st.session_state: st.session_state['man_fat'] = 0.0
if 'man_ash' not in st.session_state: st.session_state['man_ash'] = 0.0
if 'man_fiber' not in st.session_state: st.session_state['man_fiber'] = 0.0
if 'man_moisture' not in st.session_state: st.session_state['man_moisture'] = 80.0

# --- BEREICH: NEUES FUTTER ---
with st.expander("➕ Neues Futter scannen & hinzufügen", expanded=True):
    st.markdown("**1. Allgemeine Infos**")
    new_supermarket = st.selectbox("Supermarkt", ["DM", "Rossmann", "Lidl", "Aldi", "Fressnapf", "Kaufland", "Edeka", "Sonstige"])
    col1, col2 = st.columns(2)
    with col1:
        new_brand = st.text_input("Marke (z.B. Winston)*")
    with col2:
        new_name = st.text_input("Sorte (z.B. Pâté Rind)*")
    new_barcode = st.text_input("Barcode (Optional für Live-API)")
        
    st.markdown("---")
    st.markdown("**2. 📸 Smarte KI-Erkennung (Etikett fotografieren)**")
    
    # Kamera-Input
    picture = st.camera_input("Fotografiere die 'Analytischen Bestandteile' auf der Dose")
    
    if picture:
        if st.button("✨ Bild mit KI auslesen"):
            with st.spinner("KI liest das Etikett... Bitte warten."):
                try:
                    # KI konfigurieren
                    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    img = Image.open(picture)
                    
                    # Anweisung an die KI
                    prompt = 'Finde die "Analytischen Bestandteile" auf diesem Katzenfutter. Extrahiere die Prozentwerte für Rohprotein, Rohfett, Rohasche, Rohfaser und Feuchtigkeit. Antworte AUSSCHLIESSLICH im JSON Format ohne Markdown. Beispiel: {"protein": 10.5, "fat": 5.5, "ash": 2.0, "fiber": 0.5, "moisture": 80.0}. Wenn ein Wert fehlt, setze ihn auf 0.0 (außer Feuchtigkeit, dann setze 80.0).'
                    
                    response = model.generate_content([prompt, img])
                    
                    # Antwort bereinigen und lesen
                    cleaned_text = response.text.replace('```json', '').replace('```', '').strip()
                    data = json.loads(cleaned_text)
                    
                    # Regler automatisch verschieben
                    st.session_state['man_protein'] = float(data.get('protein', 0.0))
                    st.session_state['man_fat'] = float(data.get('fat', 0.0))
                    st.session_state['man_ash'] = float(data.get('ash', 0.0))
                    st.session_state['man_fiber'] = float(data.get('fiber', 0.0))
                    st.session_state['man_moisture'] = float(data.get('moisture', 80.0))
                    
                    st.success("✅ Werte erfolgreich gelesen! Bitte überprüfe die Regler unten.")
                except Exception as e:
                    st.error(f"KI konnte das Bild nicht richtig lesen (Versuch es vielleicht mit besserem Licht). Fehler: {e}")

    st.markdown("---")
    st.markdown("**3. Werte (werden von KI ausgefüllt oder manuell)**")
    
    with st.form("add_product_form", clear_on_submit=True):
        col3, col4, col5 = st.columns(3)
        with col3:
            man_protein = st.number_input("Rohprotein (%)", min_value=0.0, max_value=100.0, step=0.1, key="man_protein")
            man_fat = st.number_input("Rohfett (%)", min_value=0.0, max_value=100.0, step=0.1, key="man_fat")
        with col4:
            man_ash = st.number_input("Rohasche (%)", min_value=0.0, max_value=100.0, step=0.1, key="man_ash")
            man_fiber = st.number_input("Rohfaser (%)", min_value=0.0, max_value=100.0, step=0.1, key="man_fiber")
        with col5:
            man_moisture = st.number_input("Feuchtigkeit (%)", min_value=0.0, max_value=100.0, step=0.1, key="man_moisture")
            
        if st.form_submit_button("Speichern & Berechnen"):
            if new_brand and new_name:
                with st.spinner("Wird gespeichert..."):
                    api_data = fetch_from_api(new_barcode)
                    
                    if api_data:
                        nfe_dm, is_safe = calculate_nfe_dm(api_data['protein'], api_data['fat'], api_data['ash'], api_data['fiber'], api_data['moisture'])
                        nfe_val = nfe_dm
                        status_val = "✅ Top" if is_safe else "❌ Achtung"
                        quelle_val = api_data['source']
                    elif man_protein > 0 and man_fat > 0:
                        nfe_dm, is_safe = calculate_nfe_dm(man_protein, man_fat, man_ash, man_fiber, man_moisture)
                        nfe_val = nfe_dm
                        status_val = "✅ Top" if is_safe else "❌ Achtung"
                        quelle_val = "📸 KI / Manuell"
                    else:
                        nfe_val = "N/A"
                        status_val = "⚠️ Keine Daten"
                        quelle_val = "Fehlen"
                    
                    new_entry = {
                        "Supermarkt": new_supermarket, "brand": new_brand, "name": new_name,
                        "store_type": new_supermarket.lower(), "barcode": new_barcode,
                        "NFE i.Tr. (%)": nfe_val, "Status": status_val, "Quelle": quelle_val
                    }
                    
                    st.session_state.watchlist.append(new_entry)
                    save_watchlist(st.session_state.watchlist)
                    
                    # Werte nach Speichern wieder auf null setzen
                    st.session_state['man_protein'] = 0.0
                    st.session_state['man_fat'] = 0.0
                    st.session_state['man_ash'] = 0.0
                    st.session_state['man_fiber'] = 0.0
                    st.session_state['man_moisture'] = 80.0
                    
                    st.success("Erfolgreich gespeichert!")
                    time.sleep(1)
                    st.rerun()
            else:
                st.warning("Bitte mindestens Marke und Sorte (oben mit *) ausfüllen.")

# --- BEREICH: SMARTE EINKAUFSLISTE ---
with st.expander("📝 Smarte Einkaufsliste", expanded=False):
    if st.session_state.watchlist:
        df_shopping = pd.DataFrame(st.session_state.watchlist)
        if 'Status' in df_shopping.columns:
            safe_foods = df_shopping[df_shopping['Status'].str.contains("✅ Top", na=False, case=False)]
            if not safe_foods.empty:
                available_markets = ["Alle Supermärkte"] + sorted(safe_foods['Supermarkt'].unique().tolist())
                selected_market = st.selectbox("In welchem Laden stehst du gerade?", available_markets)
                if selected_market != "Alle Supermärkte":
                    safe_foods = safe_foods[safe_foods['Supermarkt'] == selected_market]
                if not safe_foods.empty:
                    st.success(f"**Sichere Sorten für {selected_market}:**")
                    for index, row in safe_foods.iterrows():
                        st.markdown(f"- 🛒 **{row['brand']}**: {row['name']} *(NFE: {row['NFE i.Tr. (%)']}%)*")
                else:
                    st.info(f"Für {selected_market} noch keine sicheren Sorten gefunden.")
            else:
                st.info("Noch keine sicheren Sorten (Unter 10%) gespeichert.")
    else:
        st.write("Datenbank ist leer.")

# --- BEREICH: LÖSCHEN ---
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

# --- BEREICH: GESAMTE TABELLE ---
st.subheader("🛒 Deine komplette Datenbank")

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
