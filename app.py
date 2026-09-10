"""
AutoScout24 Import-Ranker (AT)
==============================

Scrapt AutoScout24-Inserate und rankt sie nach *echtem* Preisvorteil:
Endpreis in Österreich (inkl. NoVA / USt-Logik / Nebenkosten) gegen einen
aus den Daten selbst geschätzten Marktwert desselben Modells.

Start:  streamlit run autoscout_ranker.py

Alle Steuerparameter stehen oben in KONSTANTEN und sind im UI überschreibbar.
Keine Steuerberatung – NoVA-Tarife vor 2024 bitte gegenprüfen.
"""

from __future__ import annotations

import io
import json
import math
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd
import streamlit as st

# =============================================================================
# KONSTANTEN / STEUERPARAMETER
# =============================================================================

AKTUELLES_JAHR = 2026

# NoVA-Tarif nach Jahr der ERSTZULASSUNG im EU-Raum (maßgeblich ist der Tarif
# zum Zeitpunkt des erstmaligen Inverkehrbringens, nicht der Importzeitpunkt).
# 2024–2026 recherchiert; 2021–2023 mit dem Steuerberater gegenprüfen.
NOVA_TARIF: dict[int, dict[str, float]] = {
    2021: {"abzug": 112, "malus_ab": 200, "malus_satz": 50},
    2022: {"abzug": 107, "malus_ab": 185, "malus_satz": 60},
    2023: {"abzug": 102, "malus_ab": 170, "malus_satz": 70},
    2024: {"abzug": 97, "malus_ab": 155, "malus_satz": 80},
    2025: {"abzug": 94, "malus_ab": 155, "malus_satz": 80},
    2026: {"abzug": 91, "malus_ab": 155, "malus_satz": 80},
}
NOVA_MAX_SATZ = 80.0          # Höchststeuersatz M1 in %
NOVA_ABZUGSPOSTEN = 350.0     # € Abzugsposten, wird aliquotiert (Achtelung)
UST_AT = 0.20
LUXUSTANGENTE_BRUTTO = 40_000.0   # Angemessenheitsgrenze E-Pkw
VORSTEUER_DECKEL = LUXUSTANGENTE_BRUTTO / 1.20 * 0.20   # 6.666,67 €

# AutoScout24-Marktplätze (DK gibt es dort nicht – bewusst nicht in der Liste).
LAENDER = {
    "DE": "D", "AT": "A", "BE": "B", "ES": "E",
    "FR": "F", "IT": "I", "LU": "L", "NL": "NL",
}

KRAFTSTOFF = {
    "Elektro": "E",
    "Benzin": "B",
    "Diesel": "D",
    "Hybrid (Benzin/Elektro)": "2",
    "Hybrid (Diesel/Elektro)": "3",
    "Egal": "",
}

MAX_SEITEN_AS24 = 20          # harte Grenze der Suche: 20 Seiten × 20 = 400
TREFFER_PRO_SEITE = 20
BASIS_URL = "https://www.autoscout24.de/lst"


# =============================================================================
# 1. STEUER- UND KOSTENLOGIK
# =============================================================================

@dataclass
class Kaufprofil:
    """Wer kauft, und wie wirkt sich das auf den Endpreis aus."""
    unternehmer_vorsteuer: bool = False   # E-Pkw, überwiegend betrieblich
    nebenkosten: float = 600.0            # Überstellung, Typisierung, Anmeldung
    km_pauschale_pro_100km: float = 0.0   # optional: Abholkosten
    entfernung_km: float = 0.0


def nova_tarif(jahr: int) -> dict[str, float]:
    if jahr in NOVA_TARIF:
        return NOVA_TARIF[jahr]
    if jahr < min(NOVA_TARIF):
        return NOVA_TARIF[min(NOVA_TARIF)]
    # Fortschreibung: Abzugsposten sinkt um 3 g/Jahr
    letztes = max(NOVA_TARIF)
    t = dict(NOVA_TARIF[letztes])
    t["abzug"] = max(0, t["abzug"] - 3 * (jahr - letztes))
    return t


def nova_satz(co2: float, erstzulassung_jahr: int) -> float:
    """NoVA-Steuersatz in Prozent (ohne Malus)."""
    t = nova_tarif(erstzulassung_jahr)
    satz = round((co2 - t["abzug"]) / 5.0)
    return float(min(max(satz, 0.0), NOVA_MAX_SATZ))


def nova_betrag(
    bemessung_netto: float,
    co2: float,
    erstzulassung_jahr: int,
    alter_jahre: float,
    ist_elektro: bool,
) -> tuple[float, float]:
    """
    Liefert (NoVA in €, angewandter Satz in %).

    Malus und Abzugsposten werden über die Achtelung aliquotiert
    (1/8 pro vollem Jahr seit Erstzulassung, nach 8 Jahren = 0).
    """
    if ist_elektro:
        return 0.0, 0.0
    if co2 is None or (isinstance(co2, float) and math.isnan(co2)) or co2 <= 0:
        return float("nan"), float("nan")   # CO2 unbekannt -> nicht raten

    t = nova_tarif(erstzulassung_jahr)
    satz = nova_satz(co2, erstzulassung_jahr)
    achtel = max(0.0, 1.0 - math.floor(max(alter_jahre, 0)) / 8.0)

    grund = bemessung_netto * satz / 100.0
    malus = max(0.0, co2 - t["malus_ab"]) * t["malus_satz"] * achtel
    abzug = NOVA_ABZUGSPOSTEN * achtel
    return max(0.0, grund + malus - abzug), satz


def endpreis_at(zeile: pd.Series, profil: Kaufprofil) -> pd.Series:
    """
    Rechnet ein Inserat auf den effektiven Endpreis in Österreich um.

    Entscheidend sind drei Dinge, die das alte Skript ignoriert hat:

    1) Gebrauchtwagen-Import (>6 Monate UND >6.000 km) löst KEINE
       österreichische Erwerbsteuer aus. Ein Privatkäufer zahlt den
       Bruttopreis des Verkäuferlandes – nicht "netto + 20 % AT-USt".
    2) Differenzbesteuert vs. Regelbesteuert ("MwSt. ausweisbar"):
       Nur bei Regelbesteuerung kann ein vorsteuerabzugsberechtigter
       Unternehmer die USt zurückholen. Das sind ~17 % Unterschied.
    3) NoVA fällt beim Import auch auf Gebrauchte an, bemessen am
       gemeinen Wert (netto, also ohne NoVA und ohne fiktive 20 % USt).
    """
    brutto = float(zeile["Bruttopreis"])
    land = str(zeile["Land"])
    co2 = float(zeile.get("CO2", float("nan")))
    ist_elektro = bool(zeile["Elektro"])
    jahr = int(zeile["Baujahr"])
    alter = max(0.0, AKTUELLES_JAHR + 0.5 - jahr)
    ust_satz = 1.20 if land == "AT" else float(zeile.get("USt_Satz", 1.19))
    regelbesteuert = bool(zeile.get("MwSt_ausweisbar", False))
    neufahrzeug = (alter <= 0.5) or (float(zeile["KM"]) <= 6000)

    # --- Inländisches Angebot: NoVA ist bereits enthalten -------------------
    if land == "AT":
        nova = 0.0
        satz = 0.0
        if profil.unternehmer_vorsteuer and regelbesteuert:
            effektiv = brutto / 1.20
        else:
            effektiv = brutto
    else:
        # Bemessungsgrundlage NoVA: Bruttopreis herausgerechnet um
        # fiktive 20 % USt und die NoVA selbst.
        satz_vorab = 0.0 if ist_elektro else (
            nova_satz(co2, jahr) if co2 and co2 > 0 else 0.0
        )
        gemeiner_wert = brutto / (1.0 + UST_AT + satz_vorab / 100.0)
        nova, satz = nova_betrag(gemeiner_wert, co2, jahr, alter, ist_elektro)

        if profil.unternehmer_vorsteuer and regelbesteuert:
            # Netto einkaufen (ig. Lieferung), Erwerbsteuer neutralisiert sich
            netto = brutto / ust_satz
            effektiv = netto + (0.0 if pd.isna(nova) else nova)
            # Deckel Luxustangente: über 40k brutto nur begrenzter Abzug
            brutto_at = netto * 1.20 + (0.0 if pd.isna(nova) else nova)
            if brutto_at > LUXUSTANGENTE_BRUTTO:
                effektiv = brutto_at - VORSTEUER_DECKEL
        elif neufahrzeug:
            # "Neufahrzeug" i.S.d. UStG: netto kaufen, 20 % AT-Erwerbsteuer
            netto = brutto / ust_satz
            effektiv = netto * 1.20 + (0.0 if pd.isna(nova) else nova)
        else:
            effektiv = brutto + (0.0 if pd.isna(nova) else nova)

    nebenkosten = profil.nebenkosten + (
        profil.entfernung_km / 100.0 * profil.km_pauschale_pro_100km
    )
    if land == "AT":
        nebenkosten = min(nebenkosten, 150.0)

    return pd.Series({
        "NoVA_EUR": nova,
        "NoVA_Satz": satz,
        "Nebenkosten": nebenkosten,
        "Endpreis_AT": effektiv + nebenkosten,
    })


# =============================================================================
# 2. SCRAPER
# =============================================================================

def _pfad(obj: Any, pfad: str) -> Any:
    cur = obj
    for key in pfad.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        elif isinstance(cur, list) and key.isdigit() and int(key) < len(cur):
            cur = cur[int(key)]
        else:
            return None
    return cur


def hole(obj: Any, *pfade: str, default: Any = None) -> Any:
    """Erster Pfad, der einen nicht-leeren Wert liefert (schemastabil)."""
    for p in pfade:
        val = _pfad(obj, p)
        if val not in (None, "", [], {}):
            return val
    return default


def _zahl(wert: Any) -> float:
    if wert is None:
        return float("nan")
    if isinstance(wert, (int, float)):
        return float(wert)
    treffer = re.sub(r"[^\d,.\-]", "", str(wert)).replace(".", "").replace(",", ".")
    try:
        return float(treffer)
    except ValueError:
        return float("nan")


def _tiefensuche(obj: Any, muster: str, pruef: Callable[[Any], bool],
                 tiefe: int = 0) -> Any:
    """
    Sucht rekursiv nach einem Schlüssel, dessen Name zum Muster passt und
    dessen Wert plausibel ist. Nötig, weil AutoScout die JSON-Struktur
    regelmäßig umbaut und feste Pfade dann still ins Leere laufen –
    genau das war die Ursache für "kW = 100 bei jedem Auto".
    """
    if tiefe > 6:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if re.search(muster, k, re.I) and pruef(v):
                return v
        for v in obj.values():
            if isinstance(v, (dict, list)):
                treffer = _tiefensuche(v, muster, pruef, tiefe + 1)
                if treffer is not None:
                    return treffer
    elif isinstance(obj, list):
        for v in obj[:25]:
            if isinstance(v, (dict, list)):
                treffer = _tiefensuche(v, muster, pruef, tiefe + 1)
                if treffer is not None:
                    return treffer
    return None


def _numerisch(unten: float, oben: float) -> Callable[[Any], bool]:
    def pruef(v: Any) -> bool:
        z = _zahl(v)
        return bool(np.isfinite(z) and unten <= z <= oben)
    return pruef


# AutoScout liefert Kraftstoff teils als Einbuchstaben-Code statt als Text.
KRAFTSTOFF_CODES = {
    "b": "Benzin", "d": "Diesel", "e": "Elektro", "l": "Autogas (LPG)",
    "c": "Erdgas (CNG)", "m": "Ethanol", "h": "Wasserstoff",
    "2": "Hybrid (Benzin/Elektro)", "3": "Hybrid (Diesel/Elektro)",
    "o": "Sonstige",
}


def _kraftstoff_klartext(roh: str) -> str:
    schluessel = str(roh).strip().lower()
    if schluessel in KRAFTSTOFF_CODES:
        return KRAFTSTOFF_CODES[schluessel]
    return str(roh).strip() or "unbekannt"


def parse_inserat(item: dict) -> dict | None:
    """Ein Roh-Inserat in eine flache Zeile übersetzen. None = unbrauchbar."""
    preis = _zahl(hole(
        item,
        "price.priceInEuro", "price.raw", "price.amountInEuro",
        "prices.public.amountInEuroCents", "tracking.price",
        "price.priceFormatted",
    ))
    if not np.isfinite(preis) or preis <= 0:
        return None
    if preis > 1_000_000:      # Cent-Feld erwischt
        preis /= 100.0

    marke = str(hole(item, "vehicle.make", "tracking.make", default="")).strip()
    modell = str(hole(item, "vehicle.model", "tracking.model", default="")).strip()
    variante = str(hole(
        item, "vehicle.modelVersionInput", "vehicle.subtitle", default=""
    )).strip()

    erstzul = str(hole(
        item,
        "vehicle.firstRegistrationDateRaw", "vehicle.firstRegistrationDate",
        "tracking.firstRegistration", default="",
    ))
    jahr_treffer = re.search(r"(19|20)\d{2}", erstzul)
    jahr = int(jahr_treffer.group(0)) if jahr_treffer else 0

    km = _zahl(hole(
        item, "tracking.mileage", "vehicle.mileageInKmRaw", "vehicle.mileage",
    ))
    if not np.isfinite(km):
        km = _zahl(_tiefensuche(item, r"mileage|kilometer|^km$",
                                _numerisch(0, 600_000)))

    kw = _zahl(hole(
        item, "tracking.powerInKW", "vehicle.rawPowerInKw", "vehicle.powerInKw",
    ))
    if not np.isfinite(kw) or kw <= 0:
        # "power" zuerst; "kw" nur als Notnagel und ohne kWh-Akkuangaben
        kw = _zahl(_tiefensuche(item, r"power(?!.*hp)", _numerisch(20, 1200)))
        if not np.isfinite(kw):
            ps = _zahl(_tiefensuche(item, r"\bhp\b|horsepower|^ps$",
                                    _numerisch(30, 1600)))
            kw = ps / 1.36 if np.isfinite(ps) else float("nan")

    co2 = _zahl(hole(
        item,
        "tracking.co2Emission", "vehicle.co2EmissionInGramPerKm",
        "vehicle.emissionClass.co2", "vehicle.co2Emissions",
    ))
    if not np.isfinite(co2):
        co2 = _zahl(_tiefensuche(item, r"co2", _numerisch(0, 600)))

    kraftstoff_roh = str(hole(
        item, "vehicle.fuelCategory.formatted", "vehicle.fuelType",
        "tracking.fuelType", "vehicle.fuelCategory", default="",
    ))
    kraftstoff = _kraftstoff_klartext(kraftstoff_roh)
    ist_elektro = bool(re.search(r"elektro|electric|\bev\b", kraftstoff, re.I))
    if ist_elektro:
        co2 = 0.0

    # MwSt.-Ausweisbarkeit: entscheidet über Vorsteuerabzug.
    mwst_flag = hole(
        item, "price.vatDeductible", "price.vatReclaimable",
        "tracking.vatReclaimable", "price.vatRate", "vehicle.vatDeductible",
    )
    if isinstance(mwst_flag, bool):
        mwst_ausweisbar = mwst_flag
    elif isinstance(mwst_flag, (int, float)):
        mwst_ausweisbar = mwst_flag > 0
    elif isinstance(mwst_flag, str):
        mwst_ausweisbar = bool(re.search(r"ausweis|deduct|reclaim|19|20", mwst_flag))
    else:
        mwst_ausweisbar = False       # konservativ: differenzbesteuert annehmen

    land = str(hole(
        item, "seller.countryCode", "location.countryCode",
        "tracking.sellerCountry", default="DE",
    )).upper()[:2]
    ust_saetze = {"DE": 1.19, "AT": 1.20, "NL": 1.21, "BE": 1.21,
                  "FR": 1.20, "IT": 1.22, "ES": 1.21, "LU": 1.17}

    pfad_url = str(hole(item, "url", "detailPageUrl", default=""))
    link = pfad_url if pfad_url.startswith("http") else (
        f"https://www.autoscout24.de{pfad_url}" if pfad_url else ""
    )

    return {
        "ID": str(hole(item, "id", "guid", default=link)),
        "Marke": marke or "?",
        "Modell": modell or "?",
        "Variante": variante,
        "Bezeichnung": f"{marke} {modell} {variante}".strip() or "Gebrauchtwagen",
        "Baujahr": jahr,
        "KM": km,
        "kW": kw,
        "CO2": co2,
        "Kraftstoff": kraftstoff,
        "Elektro": ist_elektro,
        "Land": land,
        "USt_Satz": ust_saetze.get(land, 1.20),
        "MwSt_ausweisbar": mwst_ausweisbar,
        "Verkäufer": "Händler" if str(hole(
            item, "seller.type", default="D")).upper().startswith("D") else "Privat",
        "Bruttopreis": preis,
        "Link": link,
    }


@dataclass
class Suche:
    """Eine AutoScout24-Suche: Pfad (Marke/Modell) + Query-Filter.

    Wichtig: AutoScout kodiert Marke und Modell im PFAD (/lst/audi/e-tron),
    nicht als Query-Parameter. Wer nur den Teil nach dem "?" übernimmt,
    sucht plötzlich den ganzen Markt ab.
    """
    pfad: str = "/lst"
    params: dict[str, str] = field(default_factory=dict)

    def mit(self, **extra: str) -> "Suche":
        return Suche(self.pfad, dict(self.params, **extra))


def baue_url(suche: Suche, seite: int) -> str:
    params = {k: v for k, v in suche.params.items() if v not in ("", None)}
    params["page"] = str(seite)
    params.setdefault("atype", "C")
    params.setdefault("ustate", "N,U")
    params.setdefault("size", str(TREFFER_PRO_SEITE))
    pfad = suche.pfad if suche.pfad.startswith("/") else "/" + suche.pfad
    return (f"https://www.autoscout24.de{pfad}"
            f"?{urllib.parse.urlencode(params, safe=',')}")


def suche_aus_url(url: str) -> Suche:
    """Fertige Suche im Browser bauen, URL hier einfügen – inkl. Pfad."""
    zerlegt = urllib.parse.urlparse(url)
    params = {k: v[0] for k, v in urllib.parse.parse_qs(zerlegt.query).items()}
    for weg in ("page", "search_id", "source", "sort_id"):
        params.pop(weg, None)
    pfad = zerlegt.path or "/lst"
    if not pfad.startswith("/lst"):
        pfad = "/lst"
    return Suche(pfad.rstrip("/"), params)


def _extrahiere_json(html: str) -> dict | None:
    import bs4
    suppe = bs4.BeautifulSoup(html, "html.parser")
    tag = suppe.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except json.JSONDecodeError:
            pass
    # Fallback, falls AutoScout die ID ändert: größten JSON-Block suchen
    for m in re.finditer(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
                         html, re.S):
        try:
            daten = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(daten, dict) and "listings" in json.dumps(daten)[:200_000]:
            return daten
    return None


def _finde_listings(daten: dict) -> tuple[list, int, int]:
    props = hole(daten, "props.pageProps", default={}) or {}
    such = hole(props, "searchResult", "listings.searchResult", default={}) or {}
    listings = (hole(such, "listings") or hole(props, "listings")
                or hole(daten, "listings") or [])
    seiten = int(_zahl(hole(such, "numberOfPages",
                            default=hole(props, "numberOfPages", default=1))) or 1)
    treffer = int(_zahl(hole(such, "totalMatches", "numberOfResults",
                             default=hole(props, "totalMatches", default=0))) or 0)
    if not treffer:
        treffer = int(_zahl(_tiefensuche(
            props, r"totalMatches|numberOfResults|resultCount|totalCount",
            _numerisch(1, 5_000_000))) or 0)
    return listings, seiten, treffer


@dataclass
class Abrufbericht:
    seiten_geladen: int = 0
    treffer_gesamt: int = 0
    fehler: list[str] = field(default_factory=list)
    roh_beispiel: dict | None = None   # erstes Rohinserat, fuer die Diagnose


def scrape(
    suche: Suche,
    max_seiten: int,
    bericht: Abrufbericht,
    fortschritt: Callable[[float, str], None] | None = None,
) -> list[dict]:
    """Lädt bis max_seiten Seiten einer Suche. Fehler landen im Bericht."""
    import cloudscraper

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )
    zeilen: list[dict] = []
    seite, seiten_gesamt = 1, 1

    while seite <= min(seiten_gesamt, max_seiten, MAX_SEITEN_AS24):
        url = baue_url(suche, seite)
        html = None
        for versuch in range(3):
            try:
                antwort = scraper.get(url, timeout=20)
                if antwort.status_code == 200:
                    html = antwort.text
                    break
                bericht.fehler.append(f"Seite {seite}: HTTP {antwort.status_code}")
            except Exception as exc:                       # noqa: BLE001
                bericht.fehler.append(f"Seite {seite}: {type(exc).__name__}: {exc}")
            time.sleep(1.5 * (versuch + 1))
        if html is None:
            break

        daten = _extrahiere_json(html)
        if daten is None:
            bericht.fehler.append(
                f"Seite {seite}: kein __NEXT_DATA__ gefunden "
                "(Seitenstruktur geändert oder Bot-Schutz aktiv)."
            )
            break

        roh, seiten_gesamt, treffer = _finde_listings(daten)
        bericht.treffer_gesamt = max(bericht.treffer_gesamt, treffer)
        if not roh:
            break

        if bericht.roh_beispiel is None and roh:
            bericht.roh_beispiel = roh[0]

        for item in roh:
            zeile = parse_inserat(item)
            if zeile:
                zeilen.append(zeile)

        bericht.seiten_geladen += 1
        if fortschritt:
            obergrenze = max(1, min(seiten_gesamt, max_seiten, MAX_SEITEN_AS24))
            fortschritt(min(seite / obergrenze, 1.0),
                        f"Seite {seite}/{obergrenze} – {len(zeilen)} Inserate")
        seite += 1
        time.sleep(0.6)

    return zeilen


def scrape_mit_preisbaendern(
    suche: Suche,
    preis_von: int,
    preis_bis: int,
    max_seiten: int,
    fortschritt: Callable[[float, str], None] | None = None,
) -> tuple[pd.DataFrame, Abrufbericht]:
    """
    Umgeht das 400-Treffer-Limit: Wenn die Suche mehr Treffer hat als
    abrufbar sind, wird sie in Preisbänder zerlegt und jedes Band separat
    geladen. Aus max. 400 werden so schnell 2.000+ Inserate.
    """
    bericht = Abrufbericht()

    sonde = suche.mit(pricefrom=str(preis_von), priceto=str(preis_bis))
    erste = scrape(sonde, 1, bericht)
    gesamt = bericht.treffer_gesamt or len(erste)

    kapazitaet = min(max_seiten, MAX_SEITEN_AS24) * TREFFER_PRO_SEITE
    n_baender = 1 if gesamt <= kapazitaet else min(
        12, math.ceil(gesamt / max(kapazitaet * 0.8, 1))
    )

    # geometrische Bandgrenzen: unten sind die Inserate dichter
    grenzen = np.unique(np.round(np.geomspace(
        max(preis_von, 500), max(preis_bis, preis_von + 1000), n_baender + 1
    )).astype(int))

    alle: list[dict] = []
    for i in range(len(grenzen) - 1):
        von = grenzen[i] + (1 if i else 0)
        bis = grenzen[i + 1]
        band = suche.mit(pricefrom=str(von), priceto=str(bis))

        def melde(p: float, txt: str, i=i, von=von, bis=bis) -> None:
            if fortschritt:
                fortschritt((i + p) / max(len(grenzen) - 1, 1),
                            f"Preisband {von:,}–{bis:,} € · {txt}".replace(",", "."))

        alle.extend(scrape(band, max_seiten, bericht, melde))

    df = pd.DataFrame(alle)
    if not df.empty:
        df = df.drop_duplicates(subset="ID").reset_index(drop=True)
    return df, bericht


# =============================================================================
# 3. PLAUSIBILITÄT & MARKTWERTMODELL
# =============================================================================

def saeubern(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Unplausible Zeilen raus – sonst verzerren sie das Preismodell."""
    if df.empty:
        return df, 0
    vorher = len(df)
    d = df.copy()
    d["KM"] = pd.to_numeric(d["KM"], errors="coerce")
    d["kW"] = pd.to_numeric(d["kW"], errors="coerce")
    d = d[
        d["Bruttopreis"].between(800, 400_000)
        & d["Baujahr"].between(1990, AKTUELLES_JAHR + 1)
        & (d["KM"].fillna(0) <= 600_000)
    ]
    # kW fehlend -> Median der Modellgruppe, aber sichtbar markiert
    d["kW_geschaetzt"] = d["kW"].isna()
    d["kW"] = d.groupby(["Marke", "Modell"])["kW"].transform(
        lambda s: s.fillna(s.median())
    )
    d["kW"] = d["kW"].fillna(d["kW"].median()).fillna(100.0)
    d["KM"] = d["KM"].fillna(d["KM"].median()).fillna(50_000)
    return d.reset_index(drop=True), vorher - len(d)


def _designmatrix(g: pd.DataFrame) -> np.ndarray:
    alter = np.maximum(0.25, AKTUELLES_JAHR + 0.5 - g["Baujahr"].to_numpy(float))
    km = np.maximum(100.0, g["KM"].to_numpy(float))
    kw = np.maximum(30.0, g["kW"].to_numpy(float))
    return np.column_stack([
        np.ones(len(g)), np.log(alter), np.log(km / 10_000.0), np.log(kw)
    ])


def _fit_robust(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """OLS auf log-Preis, danach einmal getrimmt nachfitten (Ausreißer raus)."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    mad = np.median(np.abs(resid - np.median(resid))) * 1.4826
    if mad > 1e-6:
        behalten = np.abs(resid) <= 2.5 * mad
        if behalten.sum() >= X.shape[1] + 3:
            beta, *_ = np.linalg.lstsq(X[behalten], y[behalten], rcond=None)
    return beta


def marktwert_modell(
    df: pd.DataFrame,
    zielspalte: str = "Endpreis_AT",
    min_modell: int = 8,
    min_marke: int = 15,
) -> pd.DataFrame:
    """
    Schätzt für jedes Inserat den erwarteten Marktpreis aus vergleichbaren
    Inseraten desselben Modells (Alter, Laufleistung, Leistung).

    Das ist der Kern: Ranking = wie weit liegt ein Angebot unter dem, was
    dieses Modell in diesem Zustand tatsächlich kostet. Das alte
    `Marktwert = Preis * 1.08` ergab für jedes Auto denselben Score.
    """
    d = df.copy()
    d["Erwartungspreis"] = np.nan
    d["Vergleichsgruppe"] = "—"
    d["n_Vergleiche"] = 0

    y_alle = np.log(d[zielspalte].to_numpy(float))

    def anwenden(idx: pd.Index, label: str) -> None:
        g = d.loc[idx]
        X = _designmatrix(g)
        y = y_alle[d.index.get_indexer(idx)]
        beta = _fit_robust(X, y)
        d.loc[idx, "Erwartungspreis"] = np.exp(X @ beta)
        d.loc[idx, "Vergleichsgruppe"] = label
        d.loc[idx, "n_Vergleiche"] = len(idx)

    offen = set(d.index)

    modellgruppen = {k: v for k, v in d.groupby(["Marke", "Modell"], sort=False).groups.items()}
    for (marke, modell), idx in modellgruppen.items():
        if len(idx) >= min_modell:
            anwenden(idx, f"{marke} {modell}")
            offen -= set(idx)

    markengruppen = {
        k: pd.Index([i for i in v if i in offen])
        for k, v in d.groupby("Marke", sort=False).groups.items()
    }
    for marke, idx in markengruppen.items():
        if len(idx) >= min_marke:
            anwenden(idx, f"{marke} (Markenschnitt)")
            offen -= set(idx)

    if offen and len(d) >= 25:
        anwenden(pd.Index(sorted(offen)), "Gesamtmarkt (grob)")

    d["Preisvorteil_EUR"] = d["Erwartungspreis"] - d[zielspalte]
    d["Preisvorteil_Pct"] = d["Preisvorteil_EUR"] / d["Erwartungspreis"] * 100
    # Shrinkage: kleine Gruppen dürfen nicht das Ranking gewinnen
    d["Konfidenz"] = d["n_Vergleiche"] / (d["n_Vergleiche"] + 6.0)
    d["Score"] = d["Preisvorteil_Pct"] * d["Konfidenz"]
    d["Warnung"] = np.where(
        d["Preisvorteil_Pct"] > 35,
        "⚠︎ >35 % unter Markt – Unfall/Export/Motorschaden prüfen", ""
    )
    return d


# =============================================================================
# 4. UI
# =============================================================================

def _sidebar_filter() -> tuple[Suche, int, int, int]:
    st.sidebar.header("1 \u00b7 Suche")

    modus = st.sidebar.radio(
        "Filter definieren \u00fcber",
        ["Eigene AutoScout24-URL", "Formular"],
        help="Am robustesten: Suche im Browser zusammenklicken, URL kopieren, "
             "hier einf\u00fcgen. Marke und Modell stecken bei AutoScout im Pfad "
             "(/lst/audi/e-tron) und werden mit \u00fcbernommen.",
    )

    if modus == "Eigene AutoScout24-URL":
        url = st.sidebar.text_area(
            "URL einf\u00fcgen", height=90,
            placeholder="https://www.autoscout24.de/lst/audi/e-tron?...",
        )
        suche = suche_aus_url(url) if url.strip() else Suche()
        if url.strip():
            if suche.pfad != "/lst":
                st.sidebar.caption(f"Modellfilter erkannt: `{suche.pfad}`")
            else:
                st.sidebar.warning(
                    "Kein Marke/Modell im Pfad \u2013 die Suche l\u00e4uft \u00fcber den "
                    "gesamten Markt. F\u00fcr ein brauchbares Ranking besser ein "
                    "konkretes Modell w\u00e4hlen."
                )
    else:
        laender = st.sidebar.multiselect(
            "L\u00e4nder", list(LAENDER), default=["DE", "AT"],
            help="D\u00e4nemark ist kein AutoScout24-Markt und daher nicht w\u00e4hlbar.",
        )
        marke = st.sidebar.text_input(
            "Marke", value="", placeholder="audi",
            help="Kleinschreibung wie in der AS24-URL, z.\u202fB. audi, bmw, vw.",
        ).strip().lower()
        modell = st.sidebar.text_input(
            "Modell", value="", placeholder="e-tron",
        ).strip().lower()
        kraftstoff = st.sidebar.selectbox("Antrieb", list(KRAFTSTOFF), index=0)
        nur_haendler = st.sidebar.checkbox("Nur H\u00e4ndler", value=True)
        bj_von, bj_bis = st.sidebar.select_slider(
            "Erstzulassung", options=list(range(2010, AKTUELLES_JAHR + 1)),
            value=(2021, AKTUELLES_JAHR),
        )
        km_max = st.sidebar.number_input("km max.", 0, 500_000, 120_000, 10_000)

        pfad = "/lst"
        if marke:
            pfad += "/" + urllib.parse.quote(marke)
            if modell:
                pfad += "/" + urllib.parse.quote(modell)
        suche = Suche(pfad, {
            "cy": ",".join(LAENDER[c] for c in laender),
            "fuel": KRAFTSTOFF[kraftstoff],
            "custtype": "D" if nur_haendler else "",
            "fregfrom": str(bj_von), "fregto": str(bj_bis),
            "kmto": str(int(km_max)),
            "damaged_listing": "exclude",
            "sort": "standard", "desc": "0",
        })

    preis_von, preis_bis = st.sidebar.slider(
        "Preisbereich im Herkunftsland (\u20ac)",
        2_000, 120_000, (20_000, 38_000), step=1_000,
    )
    max_seiten = st.sidebar.slider(
        "Seiten je Preisband", 1, MAX_SEITEN_AS24, 8,
        help="20 Inserate/Seite. Bei vielen Treffern wird die Suche automatisch "
             "in Preisb\u00e4nder zerlegt, um das 400-Treffer-Limit zu umgehen.",
    )
    st.sidebar.caption("Abgerufen wird:")
    st.sidebar.code(baue_url(suche, 1), language=None)
    return suche, preis_von, preis_bis, max_seiten


def _sidebar_profil() -> Kaufprofil:
    st.sidebar.header("2 · Kaufprofil (Steuerlogik)")
    unternehmer = st.sidebar.checkbox(
        "Vorsteuerabzugsberechtigt (E-Pkw, betrieblich)",
        value=False,
        help="Nur bei reinen E-Pkw und nur bei Angeboten mit ausweisbarer "
             "MwSt. Bis 40.000 € brutto voller Abzug, darüber gedeckelt.",
    )
    nebenkosten = st.sidebar.number_input(
        "Nebenkosten Import (€)", 0, 5_000, 600, 50,
        help="Überstellungskennzeichen, §57a/Typisierung, NoVA-Anmeldung.",
    )
    entfernung = st.sidebar.number_input("Abholentfernung (km)", 0, 3_000, 0, 50)
    satz = st.sidebar.number_input("Kosten je 100 km (€)", 0, 100, 25, 5)
    return Kaufprofil(unternehmer, float(nebenkosten), float(satz), float(entfernung))


def main() -> None:
    st.set_page_config(page_title="AutoScout24 Import-Ranker", layout="wide")
    st.title("🚗 AutoScout24 Import-Ranker (Österreich)")
    st.caption(
        "Rankt Inserate nach echtem Preisvorteil: Endpreis in AT inkl. NoVA "
        "und USt-Logik gegen einen aus den Daten geschätzten Marktwert."
    )

    suche, preis_von, preis_bis, max_seiten = _sidebar_filter()
    profil = _sidebar_profil()

    if st.sidebar.button("🔍 Inserate laden", type="primary"):
        balken = st.progress(0.0)
        text = st.empty()

        def fortschritt(p: float, msg: str) -> None:
            balken.progress(min(max(p, 0.0), 1.0))
            text.text(f"⏳ {msg}")

        with st.spinner("Lade AutoScout24 …"):
            df, bericht = scrape_mit_preisbaendern(
                suche, preis_von, preis_bis, max_seiten, fortschritt
            )
        balken.empty()
        text.empty()
        st.session_state["df"] = df
        st.session_state["bericht"] = bericht

    df: pd.DataFrame = st.session_state.get("df", pd.DataFrame())
    bericht: Abrufbericht = st.session_state.get("bericht", Abrufbericht())

    if df.empty:
        st.info(
            "Links Filter setzen und **Inserate laden** klicken. "
            "Tipp: eng gefasste Suchen liefern bessere Vergleichsgruppen als "
            "„alle Kategorien“ – das Preismodell braucht ≥8 Inserate pro Modell."
        )
        if bericht.fehler:
            with st.expander("Diagnose"):
                for f in bericht.fehler:
                    st.text(f)
        return

    df, verworfen = saeubern(df)
    steuern = df.apply(lambda z: endpreis_at(z, profil), axis=1)
    df = pd.concat([df, steuern], axis=1)
    ohne_co2 = int(df["NoVA_EUR"].isna().sum())
    df["NoVA_EUR"] = df["NoVA_EUR"].fillna(0.0)
    df["Endpreis_AT"] = df["Endpreis_AT"].fillna(df["Bruttopreis"])

    df = marktwert_modell(df)
    df = df.dropna(subset=["Erwartungspreis"])

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Inserate", f"{len(df):,}".replace(",", "."))
    k2.metric("Auf AS24 gesamt", f"~{bericht.treffer_gesamt:,}".replace(",", "."))
    k3.metric("Seiten geladen", bericht.seiten_geladen)
    k4.metric("Ø Endpreis AT", f"{df['Endpreis_AT'].mean():,.0f} €".replace(",", "."))

    if verworfen or ohne_co2:
        st.caption(
            f"{verworfen} unplausible Zeilen entfernt · "
            f"{ohne_co2} Inserate ohne CO₂-Wert (NoVA dort mit 0 angesetzt – "
            "vor dem Kauf prüfen)."
        )

    st.sidebar.header("3 · Ranking")
    min_vorteil = st.sidebar.slider("Mind. Preisvorteil (%)", -10, 40, 0)
    nur_mit_mwst = st.sidebar.checkbox(
        "Nur Angebote mit ausweisbarer MwSt.",
        value=profil.unternehmer_vorsteuer,
    )
    budget = st.sidebar.number_input(
        "Budget Endpreis AT (€)", 0, 200_000, 35_000, 1_000
    )

    gefiltert = df[
        (df["Preisvorteil_Pct"] >= min_vorteil)
        & (df["Endpreis_AT"] <= budget)
    ]
    if nur_mit_mwst:
        gefiltert = gefiltert[gefiltert["MwSt_ausweisbar"]]
    gefiltert = gefiltert.sort_values("Score", ascending=False)

    if gefiltert.empty:
        st.warning("Keine Treffer nach Filterung – Budget oder Mindestvorteil lockern.")
        return

    top = gefiltert.iloc[0]
    st.success(
        f"🏆 **{top['Bezeichnung']}** ({top['Land']}, EZ {top['Baujahr']}, "
        f"{top['KM']:,.0f} km) – Endpreis AT **{top['Endpreis_AT']:,.0f} €** "
        f"gegen erwartete {top['Erwartungspreis']:,.0f} € → "
        f"**{top['Preisvorteil_Pct']:.1f} % unter Markt** "
        f"(Vergleichsgruppe: {top['Vergleichsgruppe']}, "
        f"n={int(top['n_Vergleiche'])})".replace(",", ".")
    )

    spalten = [
        "Bezeichnung", "Link", "Land", "Verkäufer", "Baujahr", "KM", "kW",
        "Kraftstoff", "MwSt_ausweisbar", "Bruttopreis", "NoVA_EUR",
        "Endpreis_AT", "Erwartungspreis", "Preisvorteil_EUR",
        "Preisvorteil_Pct", "Vergleichsgruppe", "n_Vergleiche", "Warnung",
    ]
    anzeige = gefiltert[spalten].rename(columns={
        "MwSt_ausweisbar": "MwSt. ausweisbar",
        "Bruttopreis": "Preis Herkunftsland",
        "NoVA_EUR": "NoVA",
        "Endpreis_AT": "Endpreis AT",
        "Preisvorteil_EUR": "Vorteil €",
        "Preisvorteil_Pct": "Vorteil %",
        "n_Vergleiche": "n",
    })

    st.dataframe(
        anzeige.style.format({
            "KM": "{:,.0f}", "kW": "{:.0f}",
            "Preis Herkunftsland": "{:,.0f} €", "NoVA": "{:,.0f} €",
            "Endpreis AT": "{:,.0f} €", "Erwartungspreis": "{:,.0f} €",
            "Vorteil €": "{:+,.0f} €", "Vorteil %": "{:+.1f} %",
        }),
        column_config={
            "Link": st.column_config.LinkColumn("Inserat", display_text="öffnen ↗"),
        },
        hide_index=True,
        height=560,
    )

    puffer = io.StringIO()
    gefiltert.to_csv(puffer, index=False)
    st.download_button(
        "⬇︎ Ergebnis als CSV", puffer.getvalue(),
        file_name="autoscout_ranking.csv", mime="text/csv",
    )

    with st.expander("Preisvorteil nach Modell"):
        uebersicht = (
            gefiltert.groupby("Vergleichsgruppe")
            .agg(Inserate=("ID", "count"),
                 Median_Endpreis=("Endpreis_AT", "median"),
                 Bester_Vorteil=("Preisvorteil_Pct", "max"))
            .sort_values("Bester_Vorteil", ascending=False)
        )
        st.dataframe(uebersicht.style.format({
            "Median_Endpreis": "{:,.0f} €", "Bester_Vorteil": "{:+.1f} %",
        }))

    with st.expander("Rechenannahmen & Diagnose"):
        st.markdown(
            f"""
- **NoVA** nach Tarif des Erstzulassungsjahres, Malus und Abzugsposten
  ({NOVA_ABZUGSPOSTEN:.0f} €) über die Achtelung aliquotiert. E-Pkw: 0 €.
  Tarif 2026: (CO₂ − 91)/5, Malus 80 €/g über 155 g/km.
- **Gebrauchtimport** (>6 Monate *und* >6.000 km) löst keine österreichische
  Erwerbsteuer aus – privat zahlst du den Bruttopreis des Herkunftslandes
  plus NoVA, nicht „netto + 20 %“.
- **Vorsteuerabzug** nur bei ausweisbarer MwSt.; bis 40.000 € brutto voll,
  darüber auf {VORSTEUER_DECKEL:,.0f} € gedeckelt.
- **Marktwert** = robuste log-lineare Regression auf Alter, Laufleistung und
  Leistung innerhalb der Modellgruppe, Ausreißer getrimmt.
- Ohne Gewähr, keine Steuerberatung.
""".replace(",", ".")
        )
        st.caption("Abgerufene URL (Seite 1):")
        st.code(baue_url(suche, 1), language=None)
        for f in bericht.fehler[:20]:
            st.text(f)
        if bericht.roh_beispiel is not None:
            st.caption(
                "Rohdaten des ersten Inserats \u2013 hier siehst du, unter welchen "
                "Schl\u00fcsseln AutoScout aktuell kW und CO\u2082 liefert:"
            )
            st.json(bericht.roh_beispiel, expanded=False)


if __name__ == "__main__":
    main()
