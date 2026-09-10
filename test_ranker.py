"""Smoke-Test: Steuerlogik + Marktwertmodell ohne Streamlit/Netzwerk."""
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

import autoscout_ranker as r  # noqa: E402

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
p2 = r.params_aus_url("https://www.autoscout24.de/lst?cy=D%2CA&fuel=E&page=3&fregfrom=2021")
check(p2 == {"cy": "D,A", "fuel": "E", "fregfrom": "2021"}, "URL-Parser", str(p2))
u = r.baue_url({"cy": "D,A", "fuel": "E"}, 2)
check("page=2" in u and "cy=D,A" in u and "atype=C" in u, "URL-Bau", u)

print("\n" + ("ALLE TESTS BESTANDEN" if ok else "ES GAB FEHLER"))
sys.exit(0 if ok else 1)
