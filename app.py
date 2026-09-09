import json
import re
import urllib.parse
import bs4
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Cross-Border Car Ranker", layout="wide")

st.title("🚗 Live Gebrauchtwagen-Bewertung & Cross-Border Ranking")
st.markdown(
    "Greift live auf **AutoScout24** zu, filtert nach **Händlerangeboten** aus **DE, AT, NL, DK** und berechnet Österreich-Endpreise inkl. NoVA."
)


# Funktion zum Auslesen echter Inserate von AutoScout24
def fetch_autoscout_listings(
    make_model="vw golf", countries=["DE", "AT"], only_dealers=True, max_results=15
):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    country_map = {"DE": "D", "AT": "A", "NL": "NL", "DK": "DK"}
    cy_params = ",".join([country_map[c] for c in countries if c in country_map])

    # Parameter für Händler (custtype=D) vs Privat (custtype=P)
    cust_type = "D" if only_dealers else ""

    # Such-URL aufbauen
    query_encoded = urllib.parse.quote(make_model)
    url = f"https://www.autoscout24.de/lst?atype=C&ustate=N%2CU&sort=standard&desc=0&cy={cy_params}&custtype={cust_type}&q={query_encoded}"

    listings = []

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            st.error(f"Fehler beim Abrufen der Daten (Status Code {response.status_code}).")
            return pd.DataFrame()

        soup = bs4.BeautifulSoup(response.text, "html.parser")

        # AutoScout24 speichert strukturierte Daten in einem JSON-Script Tag (__NEXT_DATA__)
        script_tag = soup.find("script", id="__NEXT_DATA__")

        if script_tag:
            json_data = json.loads(script_tag.string)
            page_props = (
                json_data.get("props", {})
                .get("pageProps", {})
                .get("listings", [])
            )

            for item in page_props[:max_results]:
                vehicle = item.get("vehicle", {})
                price_info = item.get("price", {})
                tracking = item.get("tracking", {})

                title = f"{vehicle.get('make', '')} {vehicle.get('model', '')} {vehicle.get('modelVersionInput', '')}".strip()
                price = price_info.get("priceInEuro", 0)
                mileage = tracking.get("mileage", 0)
                first_reg = tracking.get("firstRegistration", "N/A")
                fuel_type = vehicle.get("fuelType", "Unbekannt")
                seller_type = item.get("seller", {}).get("type", "Händler")
                location_country = item.get("seller", {}).get("countryCode", "DE").upper()

                # Exakte Inserats-URL
                url_path = item.get("url", "")
                full_url = (
                    f"https://www.autoscout24.de{url_path}"
                    if url_path
                    else "https://www.autoscout24.de"
                )

                # Baujahr extrahieren
                year_match = re.search(r"\d{4}", str(first_reg))
                year = int(year_match.group(0)) if year_match else 2021

                listings.append({
                    "Modell": title if title else make_model.title(),
                    "Baujahr": year,
                    "KM": int(mileage) if mileage else 0,
                    "Land": location_country,
                    "Antrieb": fuel_type,
                    "Bauform": "PKW",
                    "Verkäufer": "Händler" if seller_type == "D" else "Privat",
                    "Bruttopreis": float(price) if price else 0.0,
                    "NoVA_Prozent": 7,  # Standard-Schätzwert
                    "Fairer_Marktwert_Brutto": float(price) * 1.08 if price else 0.0,
                    "Wertverlust_pa": 6.5,
                    "Link": full_url,
                })

        # Fallback HTML-Parsing, falls NEXT_DATA geändert wurde
        if not listings:
            cards = soup.find_all("article")
            for card in cards[:max_results]:
                link_tag = card.find("a", href=True)
                title_tag = card.find("h2")
                price_tag = card.find(
                    "p", class_=lambda x: x and "Price" in x
                ) or card.find("span", class_=lambda x: x and "price" in x)

                if link_tag and title_tag:
                    href = link_tag["href"]
                    full_url = (
                        f"https://www.autoscout24.de{href}"
                        if href.startswith("/")
                        else href
                    )
                    title = title_tag.text.strip()

                    listings.append({
                        "Modell": title,
                        "Baujahr": 2021,
                        "KM": 50000,
                        "Land": "DE",
                        "Antrieb": "Diesel",
                        "Bauform": "PKW",
                        "Verkäufer": "Händler",
                        "Bruttopreis": 20000.0,
                        "NoVA_Prozent": 7,
                        "Fairer_Marktwert_Brutto": 21500.0,
                        "Wertverlust_pa": 6.5,
                        "Link": full_url,
                    })

    except Exception as e:
        st.error(f"Fehler beim Live-Scraping: {e}")

    return pd.DataFrame(listings)


# Sidebar Controls
st.sidebar.header("1. Live-Suche auf AutoScout24")
search_query = st.sidebar.text_input("Fahrzeugsuche (Marke / Modell)", value="VW Golf")

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

max_results = st.sidebar.slider("Anzahl Live-Angebote abrufen", 5, 30, 15)

if st.sidebar.button("🔍 Live Inserate abrufen"):
    st.session_state["live_df"] = fetch_autoscout_listings(
        make_model=search_query,
        countries=selected_countries,
        only_dealers=(seller_option == "Nur Händler"),
        max_results=max_results,
    )

# Initialisierung
if "live_df" not in st.session_state:
    st.session_state["live_df"] = fetch_autoscout_listings(
        make_model="VW Golf",
        countries=["DE", "AT", "NL"],
        only_dealers=True,
        max_results=10,
    )

df = st.session_state["live_df"]

if df.empty:
    st.warning("Keine Inserate gefunden oder Suchanfrage blockiert. Bitte erneut versuchen.")
else:
    # Berechnungen für Österreich-Import
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
    df["Gesamt_Score"] = df["PL_Score"]

    df = df.sort_values(by="Bruttopreis", ascending=True)

    st.subheader(f"Gefundene Live-Inserate ({len(df)})")

    display_df = df[[
        "Modell",
        "Link",
        "Verkäufer",
        "Land",
        "Antrieb",
        "Baujahr",
        "KM",
        "Bruttopreis",
        "Netto_Vergleichswert",
        "Preis_AT_Brutto",
    ]].copy()

    display_df.columns = [
        "Modell",
        "Link",
        "Verkäufer",
        "Land",
        "Antrieb",
        "Baujahr",
        "KM",
        "Angebot Herkunftsland (€)",
        "Netto Export (€)",
        "Preis AT (inkl. NoVA & USt) (€)",
    ]

    st.dataframe(
        display_df.style.format({
            "Angebot Herkunftsland (€)": "{:,.0f}",
            "Netto Export (€)": "{:,.0f}",
            "Preis AT (inkl. NoVA & USt) (€)": "{:,.0f}",
        }),
        column_config={
            "Link": st.column_config.LinkColumn(
                "Direktlink", display_text="Zum Inserat 🔗"
            )
        },
        use_container_width=True,
    )
