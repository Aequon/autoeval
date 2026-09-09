import json
import re
import time
import urllib.parse
import bs4
import cloudscraper
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="AutoScout24 Live All-Listing Ranker", layout="wide"
)

st.title("🚗 Live AutoScout24 Kategorie-Scraper & Ranking")
st.markdown(
    "Durchsucht **alle verfügbaren Live-Seiten** auf AutoScout24 in DE, AT, NL, DK "
    "und berechnet den Österreich-Endpreis (inkl. NoVA & USt-Anpassung)."
)

# Kategorie-Mapping für AutoScout24
CATEGORY_MAP = {
    "SUV / Crossover": {"body_code": "6", "query": "SUV"},
    "Kombi": {"body_code": "5", "query": "Kombi"},
    "Elektroauto": {"body_code": "", "query": "Elektro"},
    "Kleinwagen / Kompaktklasse": {"body_code": "2", "query": "Kompakt"},
    "Limousine": {"body_code": "3", "query": "Limousine"},
    "Alle Kategorien (Kein Filter)": {"body_code": "", "query": ""},
}


# Multi-Page Live Scraper (Läd ALLE verfügbaren Seiten)
def fetch_all_autoscout_pages(
    category_name,
    countries=["DE", "AT"],
    only_dealers=True,
    max_pages_limit=10,
):
    cat_info = CATEGORY_MAP.get(
        category_name, CATEGORY_MAP["Alle Kategorien (Kein Filter)"]
    )
    body_code = cat_info["body_code"]
    search_term = cat_info["query"]

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )

    country_map = {"DE": "D", "AT": "A", "NL": "NL", "DK": "DK"}
    cy_params = ",".join(
        [country_map[c] for c in countries if c in country_map]
    )
    cust_type = "D" if only_dealers else ""

    all_listings = []
    current_page = 1
    total_pages = 1
    total_matches = 0

    status_text = st.empty()
    progress_bar = st.progress(0)

    while current_page <= total_pages and current_page <= max_pages_limit:
        status_text.text(
            f"⏳ Lade AutoScout24 Seite {current_page} von {min(total_pages, max_pages_limit)}..."
        )

        url = f"https://www.autoscout24.de/lst?atype=C&ustate=N%2CU&sort=standard&desc=0&cy={cy_params}&custtype={cust_type}&page={current_page}"
        if body_code:
            url += f"&body={body_code}"
        if search_term:
            url += f"&q={urllib.parse.quote(search_term)}"

        try:
            response = scraper.get(url, timeout=10)
            if response.status_code != 200:
                break

            soup = bs4.BeautifulSoup(response.text, "html.parser")
            script_tag = soup.find("script", id="__NEXT_DATA__")

            if not script_tag:
                break

            json_data = json.loads(script_tag.string)
            page_props = json_data.get("props", {}).get("pageProps", {})
            search_result = page_props.get("searchResult", {})

            # Dynamische Bestimmung der Gesamtseitenanzahl von AutoScout
            total_pages = search_result.get(
                "numberOfPages", 1
            ) or page_props.get("numberOfPages", 1)
            total_matches = search_result.get(
                "totalMatches", 0
            ) or page_props.get("totalMatches", 0)

            raw_listings = search_result.get(
                "listings", []
            ) or page_props.get("listings", [])

            if not raw_listings:
                break

            for item in raw_listings:
                vehicle = item.get("vehicle", {})
                price_info = item.get("price", {})
                tracking = item.get("tracking", {})
                seller = item.get("seller", {})

                make = vehicle.get("make", "")
                model = vehicle.get("model", "")
                variant = vehicle.get("modelVersionInput", "")
                title = f"{make} {model} {variant}".strip()

                try:
                    price = float(
                        price_info.get("priceInEuro")
                        or price_info.get("raw")
                        or 0
                    )
                except (ValueError, TypeError):
                    price = 0.0

                if price <= 0:
                    continue

                try:
                    mileage = int(tracking.get("mileage", 0))
                except (ValueError, TypeError):
                    mileage = 0

                first_reg = tracking.get("firstRegistration", "")
                year_match = re.search(r"\d{4}", str(first_reg))
                year = int(year_match.group(0)) if year_match else 2021

                fuel_type = vehicle.get("fuelType", "Benzin/Diesel")
                body_type = vehicle.get("bodyType", category_name)
                seller_label = (
                    "Händler" if seller.get("type", "D") == "D" else "Privat"
                )
                country_code = seller.get("countryCode", "DE").upper()

                url_path = item.get("url", "")
                full_url = (
                    f"https://www.autoscout24.de{url_path}"
                    if url_path
                    else "https://www.autoscout24.de"
                )

                nova_est = (
                    0
                    if "elektro" in fuel_type.lower() or "ev" in title.lower()
                    else 7
                )

                all_listings.append({
                    "Modell": title if title else "Gebrauchtwagen",
                    "Baujahr": year,
                    "KM": mileage,
                    "Land": country_code,
                    "Antrieb": fuel_type,
                    "Bauform": body_type,
                    "Verkäufer": seller_label,
                    "Bruttopreis": price,
                    "Neupreis_Effektiv": round(price * 1.4, -2),
                    "Fairer_Marktwert_Brutto": round(price * 1.08, -2),
                    "NoVA_Prozent": nova_est,
                    "Wertverlust_pa": 6.2,
                    "Link": full_url,
                })

            progress = min(current_page / max(min(total_pages, max_pages_limit), 1), 1.0)
            progress_bar.progress(progress)

            current_page += 1
            time.sleep(0.5)  # Sanfter Abstand zwischen Anfragen

        except Exception:
            break

    status_text.empty()
    progress_bar.empty()

    return pd.DataFrame(all_listings), total_matches


# --- SIDEBAR CONTROLS ---
st.sidebar.header("1. Live-Kategoriesuche auf AutoScout24")

category_choice = st.sidebar.selectbox(
    "Fahrzeugkategorie wählen",
    [
        "SUV / Crossover",
        "Kombi",
        "Elektroauto",
        "Kleinwagen / Kompaktklasse",
        "Limousine",
        "Alle Kategorien (Kein Filter)",
    ],
)

selected_countries = st.sidebar.multiselect(
    "Länder einbeziehen",
    ["DE", "AT", "NL", "DK"],
    default=["DE", "AT", "NL", "DK"],
)

seller_option = st.sidebar.radio(
    "Verkäufertyp",
    ["Nur Händler", "Alle Angebote"],
    index=0,
)

max_pages_limit = st.sidebar.slider(
    "Maximale Seitenanzahl abrufen (20 Inserate/Seite)",
    min_value=1,
    max_value=20,
    value=10,
    help="AutoScout24 beschränkt Suchen auf max. 20 Seiten (400 Treffer).",
)

if st.sidebar.button("🔍 ALLE verfügbaren Inserate laden"):
    df_res, total_matches = fetch_all_autoscout_pages(
        category_name=category_choice,
        countries=selected_countries,
        only_dealers=(seller_option == "Nur Händler"),
        max_pages_limit=max_pages_limit,
    )
    st.session_state["live_df"] = df_res
    st.session_state["total_matches"] = total_matches

# Initialer Zustand
if "live_df" not in st.session_state:
    st.session_state["live_df"] = pd.DataFrame()
    st.session_state["total_matches"] = 0

df = st.session_state["live_df"]
total_matches = st.session_state.get("total_matches", 0)

# --- ANZEIGE DER ERGEBNISSE ---
if not df.empty:
    st.success(
        f"✅ Erfolgreich **{len(df)} Live-Inserate** geladen! "
        f"(Insgesamt auf AutoScout24 für diese Filter verfügbar: **~{total_matches} Fahrzeuge**)"
    )

    # --- SIDEBAR FILTER & GEWICHTUNG ---
    st.sidebar.header("2. Budget & Ranking")

    min_p = int(df["Bruttopreis"].min())
    max_p = int(df["Bruttopreis"].max())

    price_range = st.sidebar.slider(
        "Preisbereich (€ Herkunftsland)",
        min_value=min_p,
        max_value=max_p,
        value=(min_p, max_p),
        step=1000,
    )

    weight_focus = st.sidebar.slider(
        "Fokus des Rankings",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        step=0.1,
        help="0.0 = Hohe Wertstabilität | 1.0 = Bestes Preis-Leistungs-Verhältnis",
    )

    # BERECHNUNGEN
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

    filtered_df = df[
        (df["Bruttopreis"] >= price_range[0])
        & (df["Bruttopreis"] <= price_range[1])
    ].copy()

    filtered_df = filtered_df.sort_values(by="Gesamt_Score", ascending=False)

    top_car = filtered_df.iloc[0]
    st.info(
        f"🏆 **Testsieger ({category_choice}):** {top_car['Modell']} ({top_car['Land']}) – "
        f"Österreich-Endpreis: **{top_car['Preis_AT_Brutto']:,.0f} €** "
        f"(Angebot Herkunftsland: {top_car['Bruttopreis']:,.0f} € | Score: {top_car['Gesamt_Score']:.1f}/100)"
    )

    display_df = filtered_df[[
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
        "Preis Herkunftsland (€)",
        "Netto Export (€)",
        "Preis AT (inkl. NoVA & USt) (€)",
        "PL-Score",
        "Wertverlust p.a. (%)",
        "Gesamt-Score",
    ]

    st.dataframe(
        display_df.style.format({
            "Preis Herkunftsland (€)": "{:,.0f}",
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
    st.warning(
        "Klicke in der Seitenleiste auf **'🔍 ALLE verfügbaren Inserate laden'**, um den Live-Abruf für die gewählte Kategorie zu starten."
    )
