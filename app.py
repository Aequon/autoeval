import pandas as pd
import streamlit as st

st.set_page_config(page_title="Cross-Border Car Ranker", layout="wide")

st.title("🚗 Gebrauchtwagen-Bewertung & Cross-Border Ranking")
st.markdown(
    "Filtert und vergleicht Fahrzeuge aus **DE, AT, NL und DK** nach Netto-Preisen, Österreich-Endpreisen (inkl. NoVA & USt), Neupreisen sowie Preis-Leistungs-Verhältnis."
)


# Datenbestand mit Verkäufertyp und direkten Inserat-Links
def load_car_data():
    data = [
        {
            "Modell": "VW Golf VIII 2.0 TDI",
            "Baujahr": 2021,
            "KM": 65000,
            "Land": "DE",
            "Antrieb": "Diesel",
            "Bauform": "Hatchback",
            "Verkäufer": "Händler",
            "Neupreis_Effektiv": 32500,
            "Bruttopreis": 18900,
            "NoVA_Prozent": 7,
            "Fairer_Marktwert_Brutto": 20500,
            "Wertverlust_pa": 6.5,
            "Link": "https://www.autoscout24.de/angebote/volkswagen-golf-viii-2-0-tdi-aut-life-diesel-grau-12345678",
        },
        {
            "Modell": "Toyota Corolla Hybrid",
            "Baujahr": 2022,
            "KM": 45000,
            "Land": "NL",
            "Antrieb": "Hybrid",
            "Bauform": "Kombi",
            "Verkäufer": "Händler",
            "Neupreis_Effektiv": 31000,
            "Bruttopreis": 21500,
            "NoVA_Prozent": 4,
            "Fairer_Marktwert_Brutto": 23000,
            "Wertverlust_pa": 4.8,
            "Link": "https://www.autoscout24.nl/aanbod/toyota-corolla-1-8-hybrid-touring-sports-benzine-wit-23456789",
        },
        {
            "Modell": "BMW 320d (G20)",
            "Baujahr": 2020,
            "KM": 85000,
            "Land": "AT",
            "Antrieb": "Diesel",
            "Bauform": "Limousine",
            "Verkäufer": "Privat",
            "Neupreis_Effektiv": 49000,
            "Bruttopreis": 25900,
            "NoVA_Prozent": 9,
            "Fairer_Marktwert_Brutto": 26500,
            "Wertverlust_pa": 8.2,
            "Link": "https://www.autoscout24.at/angebote/bmw-320-d-aut-m-sport-diesel-blau-34567890",
        },
        {
            "Modell": "Skoda Octavia Combi 2.0 TDI",
            "Baujahr": 2021,
            "KM": 70000,
            "Land": "DE",
            "Antrieb": "Diesel",
            "Bauform": "Kombi",
            "Verkäufer": "Händler",
            "Neupreis_Effektiv": 34000,
            "Bruttopreis": 17500,
            "NoVA_Prozent": 6,
            "Fairer_Marktwert_Brutto": 19800,
            "Wertverlust_pa": 6.1,
            "Link": "https://www.autoscout24.de/angebote/skoda-octavia-combi-2-0-tdi-ambition-diesel-schwarz-45678901",
        },
        {
            "Modell": "Audi A4 Avant 40 TDI",
            "Baujahr": 2020,
            "KM": 90000,
            "Land": "DK",
            "Antrieb": "Diesel",
            "Bauform": "Kombi",
            "Verkäufer": "Händler",
            "Neupreis_Effektiv": 51000,
            "Bruttopreis": 28500,
            "NoVA_Prozent": 10,
            "Fairer_Marktwert_Brutto": 31000,
            "Wertverlust_pa": 8.9,
            "Link": "https://www.autoscout24.dk/angebote/audi-a4-avant-40-tdi-s-line-diesel-silber-56789012",
        },
        {
            "Modell": "Mazda CX-5 2.0 Skyactiv",
            "Baujahr": 2022,
            "KM": 35000,
            "Land": "DE",
            "Antrieb": "Benzin",
            "Bauform": "SUV",
            "Verkäufer": "Privat",
            "Neupreis_Effektiv": 36500,
            "Bruttopreis": 22900,
            "NoVA_Prozent": 8,
            "Fairer_Marktwert_Brutto": 23500,
            "Wertverlust_pa": 5.2,
            "Link": "https://www.autoscout24.de/angebote/mazda-cx-5-2-0-skyactiv-g-165-benzin-rot-67890123",
        },
        {
            "Modell": "Tesla Model 3 Long Range",
            "Baujahr": 2021,
            "KM": 55000,
            "Land": "NL",
            "Antrieb": "Elektro",
            "Bauform": "Limousine",
            "Verkäufer": "Händler",
            "Neupreis_Effektiv": 52000,
            "Bruttopreis": 29900,
            "NoVA_Prozent": 0,
            "Fairer_Marktwert_Brutto": 32000,
            "Wertverlust_pa": 9.1,
            "Link": "https://www.autoscout24.nl/aanbod/tesla-model-3-long-range-awd-elektrisch-zwart-78901234",
        },
        {
            "Modell": "Mercedes C 220 d",
            "Baujahr": 2021,
            "KM": 75000,
            "Land": "AT",
            "Antrieb": "Diesel",
            "Bauform": "Limousine",
            "Verkäufer": "Händler",
            "Neupreis_Effektiv": 54000,
            "Bruttopreis": 31500,
            "NoVA_Prozent": 8,
            "Fairer_Marktwert_Brutto": 32500,
            "Wertverlust_pa": 7.8,
            "Link": "https://www.autoscout24.at/angebote/mercedes-benz-c-220-d-9g-tronic-diesel-silber-89012345",
        },
    ]
    return pd.DataFrame(data)


df = load_car_data()

# Option-Listen dynamisch aus den Daten erzeugen
all_antriebe = sorted(df["Antrieb"].unique().tolist())
all_bauformen = sorted(df["Bauform"].unique().tolist())

# Sidebar Controls
st.sidebar.header("Filter & Gewichtung")

seller_filter = st.sidebar.radio(
    "Verkäufertyp",
    ["Nur Händler", "Nur Privat", "Alle Angebote"],
    index=0,
)

price_range = st.sidebar.slider(
    "Preisbereich Bruttopreis Herkunftsland (€)",
    min_value=3000,
    max_value=80000,
    value=(10000, 40000),
    step=1000,
)
selected_countries = st.sidebar.multiselect(
    "Länder einbeziehen",
    ["DE", "AT", "NL", "DK"],
    default=["DE", "AT", "NL", "DK"],
)
selected_antrieb = st.sidebar.multiselect(
    "Antriebsart", all_antriebe, default=all_antriebe
)
selected_bauform = st.sidebar.multiselect(
    "Bauform / Karosserie", all_bauformen, default=all_bauformen
)

weight_focus = st.sidebar.slider(
    "Fokus des Rankings",
    min_value=0.0,
    max_value=1.0,
    value=0.5,
    step=0.1,
    help="0.0 = Maximale Wertstabilität | 1.0 = Bestes Schnäppchen (Preis-Leistung)",
)


# Netto-Berechnung (Export-Netto)
def calculate_net_price(row):
    price = row["Bruttopreis"]
    country = row["Land"]
    nova_pct = row["NoVA_Prozent"] / 100.0

    if country == "DE":
        return price / 1.19
    elif country == "AT":
        return price / (1.20 * (1 + nova_pct))
    elif country == "NL":
        return (price * 0.85) / 1.21
    elif country == "DK":
        return price / 1.60
    return price / 1.20


# Fairen Nettowert berechnen
def calculate_fair_net(row):
    price = row["Fairer_Marktwert_Brutto"]
    country = row["Land"]
    nova_pct = row["NoVA_Prozent"] / 100.0

    if country == "DE":
        return price / 1.19
    elif country == "AT":
        return price / (1.20 * (1 + nova_pct))
    elif country == "NL":
        return (price * 0.85) / 1.21
    elif country == "DK":
        return price / 1.60
    return price / 1.20


# Berechnungen
df["Netto_Vergleichswert"] = df.apply(calculate_net_price, axis=1)
df["Fairer_Nettowert"] = df.apply(calculate_fair_net, axis=1)
df["Preis_AT_Brutto"] = df["Netto_Vergleichswert"] * 1.20 * (
    1 + (df["NoVA_Prozent"] / 100.0)
)

df["PL_Score"] = (df["Fairer_Nettowert"] / df["Netto_Vergleichswert"]) * 100
df["WV_Score"] = 100 - (df["Wertverlust_pa"] * 5)
df["Gesamt_Score"] = (df["PL_Score"] * weight_focus) + (
    df["WV_Score"] * (1 - weight_focus)
)

# Filter anwenden
filtered_df = df[
    (df["Bruttopreis"] >= price_range[0])
    & (df["Bruttopreis"] <= price_range[1])
    & (df["Land"].isin(selected_countries))
    & (df["Antrieb"].isin(selected_antrieb))
    & (df["Bauform"].isin(selected_bauform))
].copy()

# Verkäufer-Filter
if seller_filter == "Nur Händler":
    filtered_df = filtered_df[filtered_df["Verkäufer"] == "Händler"]
elif seller_filter == "Nur Privat":
    filtered_df = filtered_df[filtered_df["Verkäufer"] == "Privat"]

filtered_df = filtered_df.sort_values(by="Gesamt_Score", ascending=False)

# Anzeige
st.subheader(f"Gefundene Angebote ({len(filtered_df)})")

if not filtered_df.empty:
    top_car = filtered_df.iloc[0]
    st.success(
        f"🏆 **Top-Empfehlung:** {top_car['Modell']} ({top_car['Land']} | {top_car['Verkäufer']} | {top_car['Antrieb']} | {top_car['Bauform']}) – "
        f"Endpreis AT: **{top_car['Preis_AT_Brutto']:,.0f} €** "
        f"(Angebot Herkunftsland: {top_car['Bruttopreis']:,} € | Score: {top_car['Gesamt_Score']:.1f})"
    )

    display_df = filtered_df[[
        "Modell",
        "Link",
        "Verkäufer",
        "Land",
        "Antrieb",
        "Bauform",
        "Baujahr",
        "KM",
        "Neupreis_Effektiv",
        "Bruttopreis",
        "Netto_Vergleichswert",
        "Preis_AT_Brutto",
        "PL_Score",
        "Wertverlust_pa",
        "Gesamt_Score",
    ]].copy()

    display_df.columns = [
        "Modell",
        "Link",
        "Verkäufer",
        "Land",
        "Antrieb",
        "Bauform",
        "Baujahr",
        "KM",
        "Neupreis (rabattiert) (€)",
        "Angebot Herkunftsland (€)",
        "Netto Export (€)",
        "Preis AT (inkl. NoVA & USt) (€)",
        "PL-Score",
        "Wertverlust p.a. (%)",
        "Gesamt-Score",
    ]

    st.dataframe(
        display_df.style.format({
            "Neupreis (rabattiert) (€)": "{:,.0f}",
            "Angebot Herkunftsland (€)": "{:,.0f}",
            "Netto Export (€)": "{:,.0f}",
            "Preis AT (inkl. NoVA & USt) (€)": "{:,.0f}",
            "PL-Score": "{:.1f}",
            "Wertverlust p.a. (%)": "{:.1f}%",
            "Gesamt-Score": "{:.1f}",
        }),
        column_config={
            "Link": st.column_config.LinkColumn(
                "Inserat", display_text="Zum Inserat 🔗"
            )
        },
        use_container_width=True,
    )
else:
    st.warning("Keine Fahrzeuge für die gewählten Filterkriterien gefunden.")
