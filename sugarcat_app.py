import streamlit as st
import pandas as pd
import requests
import time
import json
import gspread
from google.oauth2.service_account import Credentials
from PIL import Image
import google.generativeai as genai

# ==========================================
# 0. SETUP & DATENBANK
# ==========================================
st.set_page_config(page_title="SugarCat Calc", page_icon="🐾", layout="centered")

# --- CUSTOM CSS FÜR ECHTES APP-FEELING ---
st.markdown("""
<style>
/* Macht alle Buttons schön groß und daumenfreundlich */
div.stButton > button {
    min-height: 80px;
    font-size: 22px !important;
    border-radius: 15px;
    border: 2px solid #e0e0e0;
}
/* Macht das Kamerabild breiter */
[data-testid="stCameraInput"] video {
    width: 100% !important;
    border-radius: 15px;
}
</style>
""", unsafe_allow_html=True)

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
except Exception as e:
    pass

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
# 1. BERECHNUNG & KI
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

def analyze_image(img):
    valid_models = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                if '1.5' in m.name or 'vision' in m.name:
                    valid_models.append(m.name)
    except Exception as e:
        raise Exception(f"Google API Fehler: {e}")

    if not valid_models:
        raise Exception("Account hat keinen Bilderkennungs-Zugriff.")

    last_error = None
    prompt = """
    Lies das Etikett von diesem Katzenfutter. 
    Suche nach den analytischen Bestandteilen (Rohprotein, Rohfett, Rohasche, Rohfaser, Feuchtigkeit).
    Gib mir NUR ein JSON-Objekt zurück mit den exakten Prozentwerten als Zahlen (ohne %-Zeichen).
    Beispiel: {"protein": 11.0, "fat": 5.5, "ash": 2.0, "fiber": 0.4, "moisture": 80.0}
    Wenn du einen Wert nicht findest, setze ihn auf 0.0. Keinen weiteren Text!
    """
    
    for model_name in valid_models:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content([prompt, img])
            result_text = response.text.replace("```json", "").replace("```", "").strip()
            return json.loads(result_text)
        except Exception as e:
            last_error = e
            continue
            
    raise Exception(f"Alle Modelle fehlgeschlagen. Fehler: {last_error}")

# ==========================================
# 2. SEITEN-ROUTER (NAVIGATION)
# ==========================================
# Lade Daten in den Session State
if 'watchlist' not in st.session_state:
    st.session_state.watchlist = load_watchlist()

if 'ai_values' not in st.session_state:
    st.session_state.ai_values = {"protein": 0.0, "fat": 0.0, "ash": 0.0, "fiber": 0.0, "moisture": 80.0}

# Wir definieren, auf welcher Seite wir uns gerade befinden
if 'page' not in st.session_state:
    st.session_state.page = "home"

def navigate_to(page_name):
    st.session_state.page = page_name

# ==========================================
# 3. DIE VERSCHIEDENEN BILDSCHIRME
# ==========================================

# --- BILDSCHIRM: HAUPTMENÜ ---
if st.session_state.page == "home":
    st.markdown("<h1 style='text-align: center;'>🐾 SugarCat</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Was möchtest du tun?</p>", unsafe_allow_html=True)
    st.write("") # Etwas Abstand
    
    # 2x2 Raster für die großen Buttons
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📸\nScannen", use_container_width=True): 
            navigate_to("scan")
            st.rerun()
        st.write("") # Abstand
        if st.button("🛒\nEinkauf", use_container_width=True): 
            navigate_to("shop")
            st.rerun()
    with col2:
        if st.button("📊\nListe", use_container_width=True): 
            navigate_to("db")
            st.rerun()
        st.write("") # Abstand
        if st.button("⚙️\nSetup", use_container_width=True): 
            navigate_to("setup")
            st.rerun()


# --- BILDSCHIRM: SCANNEN ---
elif st.session_state.page == "scan":
    if st.button("🔙 Zurück zum Hauptmenü", type="primary"):
        navigate_to("home")
        st.rerun()
        
    st.subheader("📸 Neues Futter prüfen")
    col1, col2 = st.columns(2)
    with col1:
        new_supermarket = st.selectbox("Laden", ["DM", "Rossmann", "Lidl", "Aldi", "Fressnapf", "Kaufland", "Edeka", "Sonstige"])
        new_brand = st.text_input("Marke*")
    with col2:
        new_name = st.text_input("Sorte*")
        new_barcode = st.text_input("Barcode (optional)")
        
    st.markdown("---")
    cam_image = st.camera_input("Rückseite fotografieren")
    
    if cam_image is not None:
        if st.button("✨ Bild mit KI auslesen", use_container_width=True):
            with st.spinner("Lese Etikett..."):
                try:
                    img = Image.open(cam_image)
                    ai_data = analyze_image(img)
                    st.session_state.ai_values["protein"] = float(ai_data.get("protein", 0.0))
                    st.session_state.ai_values["fat"] = float(ai_data.get("fat", 0.0))
                    st.session_state.ai_values["ash"] = float(ai_data.get("ash", 0.0))
                    st.session_state.ai_values["fiber"] = float(ai_data.get("fiber", 0.0))
                    moist = float(ai_data.get("moisture", 0.0))
                    st.session_state.ai_values["moisture"] = moist if moist > 0 else 80.0
                    st.success("✅ Erkannt! Bitte unten kontrollieren.")
                except Exception as e:
                    st.error(f"Fehler: {e}")

    with st.form("add_product_form", clear_on_submit=False):
        col3, col4, col5 = st.columns(3)
        with col3:
            man_protein = st.number_input("Protein", min_value=0.0, max_value=100.0, value=st.session_state.ai_values["protein"], step=0.1)
            man_fat = st.number_input("Fett", min_value=0.0, max_value=100.0, value=st.session_state.ai_values["fat"], step=0.1)
        with col4:
            man_ash = st.number_input("Asche", min_value=0.0, max_value=100.0, value=st.session_state.ai_values["ash"], step=0.1)
            man_fiber = st.number_input("Faser", min_value=0.0, max_value=100.0, value=st.session_state.ai_values["fiber"], step=0.1)
        with col5:
            man_moisture = st.number_input("Feuchte", min_value=0.0, max_value=100.0, value=st.session_state.ai_values["moisture"], step=0.1)
            
        if st.form_submit_button("💾 Speichern & Berechnen", use_container_width=True):
            if new_brand and new_name:
                with st.spinner("Speichere..."):
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
                        quelle_val = "📸 KI-Scan" if st.session_state.ai_values["protein"] > 0 else "✍️ Manuell"
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
                    st.session_state.ai_values = {"protein": 0.0, "fat": 0.0, "ash": 0.0, "fiber": 0.0, "moisture": 80.0}
                    st.success("Gespeichert!")
                    time.sleep(1)
                    # Nach dem Speichern automatisch zur Liste zurückkehren
                    navigate_to("db")
                    st.rerun()
            else:
                st.warning("Bitte Marke und Sorte ausfüllen.")


# --- BILDSCHIRM: DATENBANK ---
elif st.session_state.page == "db":
    if st.button("🔙 Zurück zum Hauptmenü", type="primary"):
        navigate_to("home")
        st.rerun()
        
    st.subheader("📊 Alle Futtersorten")
    if st.session_state.watchlist:
        df = pd.DataFrame(st.session_state.watchlist)
        if 'NFE i.Tr. (%)' not in df.columns:
            df['NFE i.Tr. (%)'] = "N/A"
            df['Status'] = "⚠️ Alt"
            df['Quelle'] = "-"

        df_display = df[['Supermarkt', 'brand', 'name', 'NFE i.Tr. (%)', 'Status']]
        df_display.columns = ['Markt', 'Marke', 'Sorte', 'NFE (%)', 'Bewertung']
        
        def color_status(val):
            if 'Top' in str(val): return 'background-color: #a8e6cf; color: black;'
            elif 'Achtung' in str(val): return 'background-color: #ff8b94; color: black;'
            elif 'Keine Daten' in str(val): return 'background-color: #ffe082; color: black;'
            return ''
            
        st.dataframe(df_display.style.map(color_status, subset=['Bewertung']), use_container_width=True, hide_index=True)
    else:
        st.info("Noch kein Futter gespeichert.")


# --- BILDSCHIRM: EINKAUFSLISTE ---
elif st.session_state.page == "shop":
    if st.button("🔙 Zurück zum Hauptmenü", type="primary"):
        navigate_to("home")
        st.rerun()
        
    st.subheader("🛒 Im Supermarkt")
    if st.session_state.watchlist:
        df_shopping = pd.DataFrame(st.session_state.watchlist)
        if 'Status' in df_shopping.columns:
            safe_foods = df_shopping[df_shopping['Status'].str.contains("✅ Top", na=False, case=False)]
            if not safe_foods.empty:
                available_markets = ["Alle Supermärkte"] + sorted(safe_foods['Supermarkt'].unique().tolist())
                selected_market = st.selectbox("Wo bist du gerade?", available_markets)
                if selected_market != "Alle Supermärkte":
                    safe_foods = safe_foods[safe_foods['Supermarkt'] == selected_market]
                
                if not safe_foods.empty:
                    st.write(f"Sicheres Futter bei **{selected_market}**:")
                    for index, row in safe_foods.iterrows():
                        st.markdown(f"- ✅ **{row['brand']}**: {row['name']} *(NFE: {row['NFE i.Tr. (%)']}%)*")
                else:
                    st.info(f"Nichts Sicheres für {selected_market} gefunden.")
            else:
                st.info("Kein sicheres Futter gespeichert.")
        else:
            st.info("Bitte speichere zuerst Futter ab.")
    else:
        st.write("Deine Datenbank ist noch leer.")


# --- BILDSCHIRM: SETUP / EINSTELLUNGEN ---
elif st.session_state.page == "setup":
    if st.button("🔙 Zurück zum Hauptmenü", type="primary"):
        navigate_to("home")
        st.rerun()
        
    st.subheader("⚙️ Setup & Verwaltung")
    st.write("Hier kannst du alte Einträge entfernen.")
    if st.session_state.watchlist:
        options = [f"{i['brand']} - {i['name']}" for i in st.session_state.watchlist]
        selected = st.selectbox("Futter auswählen", options)
        if st.button("🗑️ Unwiderruflich Löschen"):
            idx = options.index(selected)
            deleted = st.session_state.watchlist.pop(idx)
            save_watchlist(st.session_state.watchlist)
            st.success(f"Gelöscht!")
            time.sleep(1)
            st.rerun()
    else:
        st.info("Datenbank ist leer.")
