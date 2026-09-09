import streamlit as st
import pandas as pd

st.set_page_config(page_title="Cross-Border Car Ranker", layout="wide")

st.title("🚗 Gebrauchtwagen-Bewertung & Cross-Border Ranking")
st.markdown("Filtert und vergleicht Fahrzeuge aus **DE, AT, NL und DK** nach korrigierten Netto-Preisen, Preis-Leistungs-Verhältnis und prognostiziertem Wertverlust.")

# Sidebar Controls
st.sidebar.header("Filter & Gewichtung")

price_range = st.sidebar.slider("Preisbereich Bruttopreis (€)", min_value=3000, max_value=80000, value=(10000, 35000), step=1000)
selected_countries = st.sidebar.multiselect("Länder einbeziehen", ["DE", "AT", "NL", "DK"], default=["DE", "AT", "NL", "DK"])

weight_focus = st.sidebar.slider(
    "Fokus des Rankings",
    min_value=0.0,
    max_value=1.0,
    value=0.5,
    step=0.1,
    help="0.0 = Maximale Wertstabilität | 1.0 = Bestes Schnäppchen (Preis-Leistung)"
)

# Steuernormalisierung (Netto-Vergleichswert)
def calculate_net_price(price, country):
    if country == "DE":
        return price / 1.19
    elif country == "AT":
        return (price * 0.90) / 1.20  # Bereinigung um Ø NoVA & 20% MwSt
    elif country == "NL":
        return (price * 0.85) / 1.21  # Bereinigung um geschätzte Rest-BPM & 21% MwSt
    elif country == "DK":
        return price / 1.60          # Bereinigung um Registrierungsabgabe
    return price / 1.20

# Datenbestand (Erweiterbares Basis-Datenset)
@st.cache_data
def load_car_data():
    data = [
        {"Modell": "VW Golf VIII 2.0 TDI", "Baujahr": 2021, "KM": 65000, "Land": "DE", "Bruttopreis": 18900, "Fairer_Marktwert_Brutto": 20500, "Wertverlust_pa": 6.5},
        {"Modell": "Toyota Corolla Hybrid", "Baujahr": 2022, "KM": 45000, "Land": "NL", "Bruttopreis": 21500, "Fairer_Marktwert_Brutto": 23000, "Wertverlust_pa": 4.8},
        {"Modell": "BMW 320d (G20)", "Baujahr": 2020, "KM": 85000, "Land": "AT", "Bruttopreis": 25900, "Fairer_Marktwert_Brutto": 26500, "Wertverlust_pa": 8.2},
        {"Modell": "Skoda Octavia Combi 2.0 TDI", "Baujahr": 2021, "KM": 70000, "Land": "DE", "Bruttopreis": 17500, "Fairer_Marktwert_Brutto": 19800, "Wertverlust_pa": 6.1},
        {"Modell": "Audi A4 Avant 40 TDI", "Baujahr": 2020, "KM": 90000, "Land": "DK", "Bruttopreis": 28500, "Fairer_Marktwert_Brutto": 31000, "Wertverlust_pa": 8.9},
        {"Modell": "Mazda CX-5 2.0 Skyactiv", "Baujahr": 2022, "KM": 35000, "Land": "DE", "Bruttopreis": 22900, "Fairer_Marktwert_Brutto": 23500, "Wertverlust_pa": 5.2},
        {"Modell": "Tesla Model 3 Long Range", "Baujahr": 2021, "KM": 55000, "Land": "NL", "Bruttopreis": 29900, "Fairer_Marktwert_Brutto": 32000, "Wertverlust_pa": 9.1},
        {"Modell": "Mercedes C 220 d", "Baujahr": 2021, "KM": 75000, "Land": "AT", "Bruttopreis": 31500, "Fairer_Marktwert_Brutto": 32500, "Wertverlust_pa": 7.8},
    ]
    return pd.DataFrame(data)

df = load_car_data()

# Berechnungen
df["Netto_Vergleichswert"] = df.apply(lambda r: calculate_net_price(r["Bruttopreis"], r["Land"]), axis=1)
df["Fairer_Nettowert"] = df.apply(lambda r: calculate_net_price(r["Fairer_Marktwert_Brutto"], r["Land"]), axis=1)

# PL-Score (Günstiger als Marktwert = Wert > 100)
df["PL_Score"] = (df["Fairer_Nettowert"] / df["Netto_Vergleichswert"]) * 100

# WV-Score (Geringer Wertverlust = Höherer Score)
df["WV_Score"] = 100 - (df["Wertverlust_pa"] * 5)

# Gewichteter Gesamt-Score
df["Gesamt_Score"] = (df["PL_Score"] * weight_focus) + (df["WV_Score"] * (1 - weight_focus))

# Filter anwenden
filtered_df = df[
    (df["Bruttopreis"] >= price_range[0]) & 
    (df["Bruttopreis"] <= price_range[1]) & 
    (df["Land"].isin(selected_countries))
].copy()

filtered_df = filtered_df.sort_values(by="Gesamt_Score", ascending=False)

# Anzeige der Ergebnisse
st.subheader(f"Gefundene Angebote ({len(filtered_df)})")

if not filtered_df.empty:
    top_car = filtered_df.iloc[0]
    st.success(f"🏆 **Top-Empfehlung:** {top_car['Modell']} aus {top_car['Land']} – Angebotspreis: {top_car['Bruttopreis']:,} € (Score: {top_car['Gesamt_Score']:.1f})")

    display_df = filtered_df[[
        "Modell", "Land", "Baujahr", "KM", "Bruttopreis", 
        "Netto_Vergleichswert", "PL_Score", "Wertverlust_pa", "Gesamt_Score"
    ]].copy()
    
    display_df.columns = [
        "Modell", "Land", "Baujahr", "KM", "Brutto (€)", 
        "Netto Vergleicher (€)", "PL-Score", "Wertverlust p.a. (%)", "Gesamt-Score"
    ]

    st.dataframe(
        display_df.style.format({
            "Brutto (€)": "{:,.0f}",
            "Netto Vergleicher (€)": "{:,.0f}",
            "PL-Score": "{:.1f}",
            "Wertverlust p.a. (%)": "{:.1f}%",
            "Gesamt-Score": "{:.1f}"
        }),
        use_container_width=True
    )
else:
    st.warning("Keine Fahrzeuge im gewählten Preisbereich gefunden.")
