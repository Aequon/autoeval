import json
import re
import urllib.parse
import bs4
import cloudscraper
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Cross-Border Car Ranker", layout="wide")

st.title("🚗 Live Gebrauchtwagen-Bewertung & Cross-Border Ranking")
st.markdown(
    "Greift live auf **AutoScout24** zu, filtert nach Händlern aus **DE, AT, NL, DK** und berechnet Österreich-Endpreise inkl. NoVA & Ranking-Scores."
)


# Robuster Scraper für AutoScout24
def fetch_autoscout_listings(
    make_model="VW Golf",
    countries=["DE", "AT"],
    only_dealers=True,
    max_results=20,
):
    scraper = cloudscraper.create_scraper()
    country_map = {"DE": "D", "AT": "A", "NL": "NL", "DK": "DK"}
    cy_params = ",".join(
        [country_map[c] for c in countries if c in country_map]
    )
    cust_type = "D" if only_dealers else ""

    query_encoded = urllib.parse.quote(make_model)
    url = f"https://www.autoscout24.de/lst?atype=C&ustate=N%2CU&sort=standard&desc=0&cy={cy_params}&custtype={cust_type}&q={query_encoded}"

    listings = []

    try:
        response = scraper.get(url, timeout=12)
        if response.status_code != 200:
            st.error(
                f"Fehler beim Abrufen (Status Code {response.status_code})."
            )
            return pd.DataFrame()

        soup = bs4.BeautifulSoup(response.text, "html.parser")
        script_tag = soup.find("script", id="__NEXT_DATA__")

        if script_tag:
            json_data = json.loads(script_tag.string)
            page_props = json_data.get("props", {}).get("pageProps", {})

            # Pfad-Fallback für AutoScout JSON-Struktur
            raw_listings = page_props.get("listings", []) or page_props.get(
                "searchResult", {}
            ).get("listings", [])

            for item in raw_listings[:max_results]:
                vehicle = item.get("vehicle", {})
                price_info = item.get("price", {})
                tracking = item.get("tracking", {})
                seller = item.get("seller", {})

                # Modell & Titel
                make = vehicle.get("make", "")
                model = vehicle.get("model", "")
                variant = vehicle.get("modelVersionInput", "")
                title = f"{make} {model} {variant}".strip()

                # Preis
                price = (
                    price_info.get("priceInEuro")
                    or price_info.get("raw")
                    or 0.0
                )
                try:
                    price = float(price)
                except (ValueError, TypeError):
                    price = 0.0

                # KM & Erstzulassung
                mileage = tracking.get("mileage", 0)
                try:
                    mileage = int(mileage)
                except (ValueError, TypeError):
                    mileage = 0

                first_reg = tracking.get("firstRegistration", "")
                year_match = re.search(r"\d{4}", str(first_reg))
                year = int(year_match.group(0)) if year_match else 2021

                # Details
                fuel_type = vehicle.get("fuelType", "Benzin/Diesel")
                body_type = vehicle.get("bodyType", "PKW")
                seller_type_code = seller.get("type", "D")
                seller_label = (
                    "Händler" if seller_type_code == "D" else "Privat"
                )
                country_code = seller.get("countryCode", "DE").upper()

                # URL
                url_path = item.get("url", "")
                full_url = (
                    f"https://www.autoscout24.de{url_path}"
                    if url_path
                    else "https://www.autoscout24.de"
                )

                if price > 0:
                    listings.append({
                        "Modell": title if title else make_model.title(),
                        "Baujahr": year,
                        "KM": mileage,
                        "Land": country_code,
                        "Antrieb": fuel_type,
                        "Bauform": body_type,
                        "Verkäufer": seller_label,
                        "Bruttopreis": price,
                        "Neupreis_Effektiv": round(price * 1.35, -2),
                        "Fairer_Marktwert_Brutto": round(price * 1.07, -2),
                        "NoVA_Prozent": 7,
                        "Wertverlust_pa": 6.5,
                        "Link": full_url,
                    })

    except Exception as e:
        st.error(f"Fehler beim Live-Scraping: {e}")

    return pd.DataFrame(listings)


# --- SIDEBAR CONTROLS ---
st.sidebar.header("1. Live-Suche auf AutoScout24")
search_query = st.sidebar.text_input(
    "Fahrzeugsuche (Marke / Modell)", value="VW Golf"
)

selected_countries = st.sidebar.multiselect(
    "Länder einbeziehen",
    ["DE", "AT", "NL", "DK"],
    default=["DE", "AT", "NL"],
)

seller_option = st.sidebar.radio(
    "Verkäufertyp",
    ["Nur Händler", "Alle Angebote"],
    index=0,
)

max_results = st.sidebar.slider("Anzahl Inserate abrufen", 5, 50, 20)

if st.sidebar.button("🔍 Live Inserate abrufen"):
    st.session_state["live_df"] = fetch_autoscout_listings(
        make_model=search_query,
        countries=selected_countries,
        only_dealers=(seller_option == "Nur Händler"),
        max_results=max_results,
    )

# Initialer Abruf
if "live_df" not in st.session_state:
    st.session_state["live_df"] = fetch_autoscout_listings(
        make_model="VW Golf",
        countries=["DE", "AT", "NL"],
        only_dealers=True,
        max_results=20,
    )

df = st.session_state["live_df"]

if df.empty:
    st.warning(
        "Keine Live-Angebote gefunden. Bitte Prüfen Sie die Sucheingabe oder klicken Sie erneut auf 'Live Inserate abrufen'."
    )
else:
    # --- SIDEBAR FILTER & GEWICHTUNG ---
    st.sidebar.header("2. Filter & Ranking")

    min_p = int(df["Bruttopreis"].min())
    max_p = int(df["Bruttopreis"].max())

    price_range = st.sidebar.slider(
        "Preisbereich Herkunftsland (€)",
        min_value=0,
        max_value=max(max_p + 5000, 50000),
        value=(min_p, max_p),
        step=500,
    )

    all_antriebe = sorted(df["Antrieb"].dropna().unique().tolist())
    selected_antrieb = st.sidebar.multiselect(
        "Antriebsart", all_antriebe, default=all_antriebe
    )

    weight_focus = st.sidebar.slider(
        "Fokus des Rankings",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        step=0.1,
        help="0.0 = Maximale Wertstabilität | 1.0 = Bestes Schnäppchen (Preis-Leistung)",
    )

    # --- BERECHNUNGEN ---
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

    df["Netto_Vergleichswert"] = df.apply(calculate_net_price, axis=1)
    df["Preis_AT_Brutto"] = df["Netto_Vergleichswert"] * 1.20 * (
        1 + (df["NoVA_Prozent"] / 100.0)
    )

    df["PL_Score"] = (df["Fairer_Marktwert_Brutto"] / df["Bruttopreis"]) * 100
    df["WV_Score"] = 100 - (df["Wertverlust_pa"] * 5)
    df["Gesamt_Score"] = (df["PL_Score"] * weight_focus) + (
        df["WV_Score"] * (1 - weight_focus)
    )

    # Filter anwenden
    filtered_df = df[
        (df["Bruttopreis"] >= price_range[0])
        & (df["Bruttopreis"] <= price_range[1])
        & (df["Antrieb"].isin(selected_antrieb))
    ].copy()

    filtered_df = filtered_df.sort_values(by="Gesamt_Score", ascending=False)

    # --- ANZEIGE ---
    st.subheader(f"Gefundene Live-Inserate ({len(filtered_df)})")

    if not filtered_df.empty:
        top_car = filtered_df.iloc[0]
        st.success(
            f"🏆 **Top-Empfehlung:** {top_car['Modell']} ({top_car['Land']} | {top_car['Verkäufer']} | {top_car['Antrieb']}) – "
            f"Endpreis AT: **{top_car['Preis_AT_Brutto']:,.0f} €** "
            f"(Angebot Herkunftsland: {top_car['Bruttopreis']:,.0f} € | Score: {top_car['Gesamt_Score']:.1f})"
        )

        display_df = filtered_df[[
            "Modell",
            "Link",
            "Verkäufer",
            "Land",
            "Antrieb",
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
            "Baujahr",
            "KM",
            "Neupreis (geschätzt) (€)",
            "Angebot Herkunftsland (€)",
            "Netto Export (€)",
            "Preis AT (inkl. NoVA & USt) (€)",
            "PL-Score",
            "Wertverlust p.a. (%)",
            "Gesamt-Score",
        ]

        st.dataframe(
            display_df.style.format({
                "Neupreis (geschätzt) (€)": "{:,.0f}",
                "Angebot Herkunftsland (€)": "{:,.0f}",
                "Netto Export (€)": "{:,.0f}",
                "Preis AT (inkl. NoVA & USt) (€)": "{:,.0f}",
                "PL-Score": "{:.1f}",
                "Wertverlust p.a. (%)": "{:.1f}%",
                "Gesamt-Score": "{:.1f}",
            }),
            column_config={
                "Link": st.column_config.LinkColumn(
                    "Direktlink", display_text="Zum Inserat 🔗"
                )
            },
            use_container_width=True,
        )
    else:
        st.warning("Keine Fahrzeuge für die gewählten Filterkriterien gefunden.")
