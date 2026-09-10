"""Smoke-Test: Steuerlogik + Marktwertmodell ohne Streamlit/Netzwerk."""
import re
import sys, types
import numpy as np
import pandas as pd

# --- Streamlit stubben, damit das Modul importierbar ist ---------------------
stub = types.ModuleType("streamlit")


class _Any:
    def __getattr__(self, name):
        return _Any()

    def __call__(self, *a, **k):
        return _Any()


for name in ("set_page_config", "title", "caption", "sidebar", "progress",
             "empty", "spinner", "session_state", "columns", "metric",
             "dataframe", "download_button", "expander", "markdown", "info",
             "warning", "success", "text", "column_config", "button"):
    setattr(stub, name, _Any())
sys.modules["streamlit"] = stub

import app as r  # noqa: E402

ok = True


def check(bedingung, label, detail=""):
    global ok
    ok = ok and bool(bedingung)
    print(("PASS  " if bedingung else "FAIL  ") + label + ("  " + detail if detail else ""))


# --- 1. NoVA -----------------------------------------------------------------
print("\n== NoVA ==")
check(r.nova_satz(148, 2026) == 11, "2026: (148-91)/5 = 11 %", str(r.nova_satz(148, 2026)))
check(r.nova_satz(80, 2026) == 0, "unter Grenzwert -> 0 %")
check(r.nova_satz(600, 2024) == 80, "Deckel bei 80 %")
betrag, satz = r.nova_betrag(29917, 148, 2026, 0.0, False)
check(abs(betrag - (29917 * 0.11 - 350)) < 1, "Beispiel 29.917 € netto / 148 g", f"{betrag:.0f} €")
check(r.nova_betrag(30000, 0, 2023, 3, True) == (0.0, 0.0), "E-Auto: 0 €")
check(np.isnan(r.nova_betrag(30000, float('nan'), 2023, 3, False)[0]), "CO2 unbekannt -> NaN")
alt, _ = r.nova_betrag(20000, 200, 2022, 4.0, False)   # mit Malus (>185 g)
jung, _ = r.nova_betrag(20000, 200, 2022, 0.0, False)
check(alt < jung, "Achtelung senkt den Malus mit dem Fahrzeugalter",
      f"4 J: {alt:.0f} € vs neu: {jung:.0f} €")
alt2, _ = r.nova_betrag(20000, 150, 2022, 4.0, False)  # ohne Malus
jung2, _ = r.nova_betrag(20000, 150, 2022, 0.0, False)
check(alt2 > jung2, "ohne Malus: Abzugsposten schrumpft -> NoVA steigt leicht",
      f"4 J: {alt2:.0f} € vs neu: {jung2:.0f} €")
acht, _ = r.nova_betrag(20000, 200, 2022, 9.0, False)
check(abs(acht - 20000 * 0.19) < 1, "nach 8 Jahren: weder Malus noch Abzugsposten")

# --- 2. Endpreis -------------------------------------------------------------
print("\n== Endpreis AT ==")
profil_privat = r.Kaufprofil(unternehmer_vorsteuer=False, nebenkosten=600)
profil_firma = r.Kaufprofil(unternehmer_vorsteuer=True, nebenkosten=600)

ev_de = pd.Series({"Bruttopreis": 30000, "Land": "DE", "CO2": 0, "Elektro": True,
                   "Baujahr": 2023, "KM": 40000, "USt_Satz": 1.19,
                   "MwSt_ausweisbar": True})
p = r.endpreis_at(ev_de, profil_privat)
check(abs(p["Endpreis_AT"] - 30600) < 1, "E-Auto DE privat = Brutto + NK", f"{p['Endpreis_AT']:.0f}")
f = r.endpreis_at(ev_de, profil_firma)
check(abs(f["Endpreis_AT"] - (30000 / 1.19 + 600)) < 1,
      "E-Auto DE Firma m. MwSt = netto + NK", f"{f['Endpreis_AT']:.0f}")
check(f["Endpreis_AT"] < p["Endpreis_AT"] * 0.87, "Vorsteuer bringt ~16 %")

ev_diff = ev_de.copy(); ev_diff["MwSt_ausweisbar"] = False
check(abs(r.endpreis_at(ev_diff, profil_firma)["Endpreis_AT"] - 30600) < 1,
      "differenzbesteuert: kein Vorsteuerabzug")

diesel = pd.Series({"Bruttopreis": 25000, "Land": "DE", "CO2": 150, "Elektro": False,
                    "Baujahr": 2022, "KM": 90000, "USt_Satz": 1.19,
                    "MwSt_ausweisbar": False})
d = r.endpreis_at(diesel, profil_privat)
check(d["NoVA_EUR"] > 1000, "Diesel 150 g: NoVA faellt an", f"{d['NoVA_EUR']:.0f} €")
check(d["Endpreis_AT"] > 25000, "NoVA erhoeht Endpreis")

neu = pd.Series({"Bruttopreis": 30000, "Land": "DE", "CO2": 0, "Elektro": True,
                 "Baujahr": 2026, "KM": 1500, "USt_Satz": 1.19,
                 "MwSt_ausweisbar": False})
n = r.endpreis_at(neu, profil_privat)
check(n["Endpreis_AT"] > 30600, "Neufahrzeug (<6000 km): AT-Erwerbsteuer 20 %",
      f"{n['Endpreis_AT']:.0f}")

at_auto = pd.Series({"Bruttopreis": 32000, "Land": "AT", "CO2": 0, "Elektro": True,
                     "Baujahr": 2023, "KM": 40000, "USt_Satz": 1.20,
                     "MwSt_ausweisbar": True})
a = r.endpreis_at(at_auto, profil_privat)
check(a["NoVA_EUR"] == 0 and a["Endpreis_AT"] <= 32150, "AT-Angebot: keine NoVA, kaum NK")

# --- 3. Marktwertmodell ------------------------------------------------------
print("\n== Marktwertmodell ==")
rng = np.random.default_rng(42)
zeilen = []
for i in range(120):
    jahr = int(rng.integers(2019, 2026))
    km = float(rng.integers(10_000, 150_000))
    kw = float(rng.choice([100, 150, 200]))
    fair = 55_000 * np.exp(-0.16 * (2026.5 - jahr)) * np.exp(-0.0000025 * km) * (kw / 150) ** 0.3
    preis = fair * float(rng.normal(1.0, 0.05))
    zeilen.append({"ID": f"x{i}", "Marke": "Tesla", "Modell": "Model 3",
                   "Bezeichnung": "Tesla Model 3", "Baujahr": jahr, "KM": km,
                   "kW": kw, "CO2": 0.0, "Elektro": True, "Land": "DE",
                   "Kraftstoff": "Elektro", "USt_Satz": 1.19,
                   "MwSt_ausweisbar": True, "Verkäufer": "Händler",
                   "Bruttopreis": round(preis), "Link": ""})
# ein echtes Schnaeppchen und ein Ueberpreis einbauen
zeilen[0]["Bruttopreis"] = round(zeilen[0]["Bruttopreis"] * 0.75)
zeilen[1]["Bruttopreis"] = round(zeilen[1]["Bruttopreis"] * 1.30)

df = pd.DataFrame(zeilen)
df, verworfen = r.saeubern(df)
steuern = df.apply(lambda z: r.endpreis_at(z, profil_privat), axis=1)
df = pd.concat([df, steuern], axis=1)
res = r.marktwert_modell(df)

check(verworfen == 0, "keine plausiblen Zeilen faelschlich verworfen")
check(res["Vergleichsgruppe"].iloc[0] == "Tesla Model 3", "Modellgruppe erkannt")
check(res["Preisvorteil_Pct"].std() > 3, "Scores streuen (alter Bug: konstant 108)",
      f"sd={res['Preisvorteil_Pct'].std():.1f}")
bester = res.sort_values("Score", ascending=False).iloc[0]
check(bester["ID"] == "x0", "Schnaeppchen landet auf Platz 1", bester["ID"])
schlechtester = res.sort_values("Score").iloc[0]
check(schlechtester["ID"] == "x1", "Ueberpreis landet auf letztem Platz", schlechtester["ID"])
check(abs(res.loc[res.ID == "x0", "Preisvorteil_Pct"].iloc[0] - 25) < 6,
      "Rabatt korrekt geschaetzt (~25 %)",
      f"{res.loc[res.ID=='x0','Preisvorteil_Pct'].iloc[0]:.1f} %")
check((res["Warnung"] != "").sum() >= 0, "Warnspalte vorhanden")

# kleine Gruppe -> Shrinkage
klein = pd.concat([df.head(6).assign(Marke="Exot", Modell="Rar", ID=lambda x: x.ID + "k"), df])
klein = klein.reset_index(drop=True)
res2 = r.marktwert_modell(klein)
check(res2.loc[res2.Marke == "Exot", "Konfidenz"].max() <= 1.0, "Konfidenz <= 1")

# --- 4. Parser ---------------------------------------------------------------
print("\n== Parser ==")
roh = {"id": "abc", "vehicle": {"make": "VW", "model": "ID.4",
                                "modelVersionInput": "Pro Performance",
                                "firstRegistrationDateRaw": "2023-04-01",
                                "rawPowerInKw": 150, "fuelCategory": {"formatted": "Elektro"}},
       "price": {"priceInEuro": 28900, "vatDeductible": True},
       "tracking": {"mileage": 42000}, "seller": {"type": "D", "countryCode": "de"},
       "url": "/angebote/vw-id4-123"}
z = r.parse_inserat(roh)
check(z is not None and z["Marke"] == "VW" and z["Baujahr"] == 2023, "Felder gelesen")
check(z["Elektro"] and z["CO2"] == 0.0, "Elektro erkannt -> CO2 0")
check(z["MwSt_ausweisbar"] is True, "MwSt-Flag gelesen")
check(z["Link"].startswith("https://www.autoscout24.de/angebote"), "Link gebaut")
check(r.parse_inserat({"price": {}}) is None, "Inserat ohne Preis verworfen")
check(r.hole({"a": {"b": 1}}, "x.y", "a.b") == 1, "Fallback-Pfade")
s1 = r.suche_aus_url("https://www.autoscout24.de/lst?cy=D%2CA&fuel=E&page=3&fregfrom=2021")
check(s1.params == {"cy": "D,A", "fuel": "E", "fregfrom": "2021"}, "URL-Parser", str(s1.params))
check(s1.pfad == "/lst", "ohne Modell -> /lst")

# Der eigentliche Bug: Marke/Modell stehen im Pfad, nicht in den Params
s2 = r.suche_aus_url(
    "https://www.autoscout24.de/lst/audi/e-tron?sort=standard&desc=0"
    "&ustate=N%2CU&cy=D&ocs_listing=include&damaged_listing=exclude"
    "&atype=C&source=homepage_search-mask")
check(s2.pfad == "/lst/audi/e-tron", "Marke/Modell aus dem Pfad uebernommen", s2.pfad)
check("source" not in s2.params, "source-Parameter entfernt")
u2 = r.baue_url(s2, 2)
check("/lst/audi/e-tron?" in u2 and "page=2" in u2, "URL-Bau mit Modellpfad", u2)
check(r.baue_url(r.Suche(), 1).startswith("https://www.autoscout24.de/lst?"), "Default-Pfad")
check(r.suche_aus_url("https://boese.example/evil?x=1").pfad == "/lst", "fremder Pfad verworfen")

# Kraftstoff-Codes
check(r._kraftstoff_klartext("e") == "Elektro", "Code 'e' -> Elektro")
check(r._kraftstoff_klartext("d") == "Diesel", "Code 'd' -> Diesel")
check(r._kraftstoff_klartext("2").startswith("Hybrid"), "Code '2' -> Hybrid")
check(r._kraftstoff_klartext("Elektro") == "Elektro", "Klartext bleibt")

z_e = r.parse_inserat({"price": {"priceInEuro": 30000},
                       "vehicle": {"make": "Polestar", "model": "2",
                                   "fuelType": "e",
                                   "firstRegistrationDateRaw": "2023-01-01"},
                       "tracking": {"mileage": 50000}, "url": "/x"})
check(z_e["Elektro"] and z_e["Kraftstoff"] == "Elektro", "Code-Auto als Elektro erkannt")

# Tiefensuche: kW/CO2 unter unbekannten Schluesseln
tief = {"price": {"priceInEuro": 25000}, "vehicle": {"make": "VW", "model": "Golf",
        "firstRegistrationDateRaw": "2021-06-01"},
        "irgendwo": {"tief": {"enginePower": 110, "co2Value": 132}},
        "tracking": {"mileage": 60000}, "url": "/y"}
zt = r.parse_inserat(tief)
check(abs(zt["kW"] - 110) < 1, "kW per Tiefensuche gefunden", str(zt["kW"]))
check(abs(zt["CO2"] - 132) < 1, "CO2 per Tiefensuche gefunden", str(zt["CO2"]))
akku = {"price": {"priceInEuro": 25000}, "vehicle": {"make": "X", "model": "Y",
        "firstRegistrationDateRaw": "2022-01-01", "batteryCapacityInKWh": 78},
        "tracking": {"mileage": 10000}, "url": "/z"}
za = r.parse_inserat(akku)
check(not (70 <= (za["kW"] if za["kW"] == za["kW"] else 0) <= 80),
      "Akku-kWh nicht als Motorleistung missverstanden", str(za["kW"]))

# --- 5. Variantentrennung ---------------------------------------------------
print("\n== Variantenmerkmale ==")
check(r._tokens("Sportback 50 quattro LED Navi") == {"sportback", "50"},
      "Tokens: Motorisierung bleibt, Ausstattung faellt raus",
      str(sorted(r._tokens("Sportback 50 quattro LED Navi"))))

# Zwei Motorisierungen mit echtem Preisunterschied im selben Modell
rng2 = np.random.default_rng(7)
zeilen2 = []
for i in range(160):
    stark = i % 2 == 0
    jahr = int(rng2.integers(2020, 2024))
    km = float(rng2.integers(20_000, 140_000))
    fair = (46_000 if stark else 32_000) * np.exp(-0.15 * (2026.5 - jahr)) \
        * np.exp(-0.0000022 * km)
    zeilen2.append({"ID": f"v{i}", "Marke": "Audi", "Modell": "e-tron",
                    "Variante": "55 quattro advanced" if stark else "50 quattro advanced",
                    "Bezeichnung": "Audi e-tron", "Baujahr": jahr, "KM": km,
                    "kW": 100.0, "CO2": 0.0, "Elektro": True, "Land": "DE",
                    "Kraftstoff": "Elektro", "USt_Satz": 1.19,
                    "MwSt_ausweisbar": False, "Verkäufer": "Händler",
                    "Bruttopreis": round(fair * float(rng2.normal(1.0, 0.04))),
                    "Link": ""})
df2 = pd.DataFrame(zeilen2)
df2, _ = r.saeubern(df2)
df2 = pd.concat([df2, df2.apply(lambda z: r.endpreis_at(z, profil_privat), axis=1)], axis=1)
res3 = r.marktwert_modell(df2)

schwach = res3[res3["Variante"].str.startswith("50")]["Preisvorteil_Pct"].mean()
stark_m = res3[res3["Variante"].str.startswith("55")]["Preisvorteil_Pct"].mean()
check(abs(schwach - stark_m) < 6,
      "schwache Variante gilt nicht pauschal als Schnaeppchen",
      f"50er {schwach:+.1f} % vs 55er {stark_m:+.1f} %")
check("50" in res3.attrs["variantenmerkmale"].get("Audi e-tron", []),
      "Motorisierung als Merkmal erkannt",
      str(res3.attrs["variantenmerkmale"].get("Audi e-tron")))

# Gegenprobe: ohne Merkmale waere die Verzerrung gross
X_basis = np.column_stack([np.ones(len(df2)),
                           np.log(2026.5 - df2["Baujahr"].to_numpy(float)),
                           np.log(df2["KM"].to_numpy(float) / 10_000),
                           np.log(np.maximum(30, df2["kW"].to_numpy(float)))])
b = r._fit_robust(X_basis, np.log(df2["Endpreis_AT"].to_numpy(float)))
naiv = (np.exp(X_basis @ b) - df2["Endpreis_AT"]) / np.exp(X_basis @ b) * 100
luecke_naiv = abs(naiv[df2["Variante"].str.startswith("50")].mean()
                  - naiv[df2["Variante"].str.startswith("55")].mean())
check(luecke_naiv > 10, "ohne Variantenmerkmale entstuende ein Scheinvorteil",
      f"{luecke_naiv:.0f} Prozentpunkte")

# --- 6. Feinabstimmung / Overrides ------------------------------------------
print("\n== Overrides ==")
basis = r.suche_aus_url(
    "https://www.autoscout24.de/lst/audi/e-tron?cy=D&custtype=D&atype=C")
o1 = basis.mit(custtype="P")
check(o1.params["custtype"] == "P", "Verkaeufertyp ueberschrieben")
check(o1.pfad == "/lst/audi/e-tron", "Modellpfad bleibt beim Ueberschreiben")
check(basis.params["custtype"] == "D", "Basissuche wird nicht mutiert")
o2 = basis.mit(custtype="")
check("custtype=" not in r.baue_url(o2, 1), "leerer Wert entfernt den Filter",
      r.baue_url(o2, 1))
o3 = basis.mit(cy="D,A,NL")
check("cy=D,A,NL" in r.baue_url(o3, 1) and "custtype=D" in r.baue_url(o3, 1),
      "nicht angefasste Filter bleiben erhalten")

# --- 7. UI-Funktionen vorhanden ---------------------------------------------
# Faengt Bearbeitungsfehler ab, bei denen eine def-Zeile verlorengeht und der
# Rumpf still an der Funktion darueber haengenbleibt.
print("\n== Modulstruktur ==")
import inspect  # noqa: E402
for name in ("_sidebar_filter", "_sidebar_feinabstimmung", "_sidebar_profil",
             "main", "scrape", "scrape_mit_preisbaendern", "marktwert_modell",
             "endpreis_at", "saeubern", "parse_inserat", "baue_url",
             "suche_aus_url"):
    check(callable(getattr(r, name, None)), f"{name}() definiert")

import ast  # noqa: E402

baum = ast.parse(open(r.__file__, encoding="utf-8").read())
tot = []
for knoten in ast.walk(baum):
    if isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for k, anweisung in enumerate(knoten.body[:-1]):
            if isinstance(anweisung, ast.Return):
                tot.append(f"{knoten.name} (ab Zeile {knoten.body[k+1].lineno})")
                break
check(not tot, "kein unerreichbarer Code nach einem return", "; ".join(tot))

print("\n" + ("ALLE TESTS BESTANDEN" if ok else "ES GAB FEHLER"))
sys.exit(0 if ok else 1)
