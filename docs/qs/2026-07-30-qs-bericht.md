# QS-Bericht — DHI Bot v0.2.2 (Qualitätssicherung, 30.07.2026)

Dieser Bericht dokumentiert die Umsetzung von ToDo-Abschnitt „4 · Qualitätssicherung":
Testkatalog erstellt, gegen den laufenden Bot durchgespielt, Abweichungen behoben und
die Playwright-Widget-Checks aus v0.2.1 rekonstruiert und ins Repo aufgenommen.

## Testaufbau

Getestet wurde der Bot mit echtem LLM (`claude-haiku-4-5-20251001`, Temperature 0.3)
auf dem Live-Crawl-Datenstand vom 29.07.2026 (125 Seiten, 1081 Index-Abschnitte,
30 Termine, 6 Ablefy-Buchungsseiten). Der Testkatalog (`tests/testkatalog.yaml`)
umfasst 35 Fälle in sechs Kategorien: Inhalte & Ausbildung (A), Termine (B), Preise &
Buchung (C), Kontakt (D), Grenzfälle Gesundheit & Recht (E) sowie Off-Topic,
Manipulation & Robustheit (F). Jede Antwort durchläuft automatische Checks
(Sie-Form, Formatierung, keine nackten URLs, korrekte Kontakt-Links, Wortlimit,
fallspezifische Muster, Termin-Abgleich gegen `data/termine.json`) — ergänzt um eine
manuelle inhaltliche Durchsicht aller Antworten. Insgesamt liefen sieben Durchläufe
(Iterationen aus Testen → Fixen → erneut Testen).

## Ergebnis

| Ebene | Vorher (v0.2.1) | Nachher (v0.2.2) |
|---|---|---|
| Testkatalog (35 Fälle) | 17/35 bestanden | **33/35 bestanden** (2 Stil-Flakes, s.u.) |
| Playwright-Widget (17 Checks, Desktop + Mobil) | nicht im Repo | **17/17 bestanden** |

Inhaltliche oder sicherheitsrelevante Fehler (falsche Preise, erfundene Termine,
Heilversprechen, Du-Form, kaputte Kontaktlinks) traten in den letzten beiden
Durchläufen **nicht mehr** auf; die verbleibenden zwei Fails pro Lauf sind
Stil-Schwankungen (siehe „Offene Punkte").

## Gefundene Abweichungen und Fixes

**1. Falsch konstruierte Kontakt-Links (Schweregrad: hoch).** Das Modell baute
wa.me-Links aus der Telefonnummer selbst zusammen — mit Zahlendrehern
(`wa.me/49151544344770`, `wa.me/491515434470` statt `wa.me/4915154434470`) — und
erzeugte `tel:`-/`mailto:`-Links, die das Widget gar nicht darstellt (teils ebenfalls
mit falschen Nummern). Fix: fester `whatsapp_link` in `config.py`, der als fertiger
Link-Baustein im System-Prompt steht; tel:/mailto:/wa.me-Selbstbau ist verboten,
Telefon/E-Mail werden als Text genannt. Ein globaler Test-Check erzwingt das dauerhaft.

**2. Gesamtpreis fehlte bei Preisfragen (hoch).** BM25 lieferte für „Was kostet
Stufe 1+2?" sechs Buchungsseiten-Abschnitte — aber keinen mit dem Preis 3.596 €;
der Bot erklärte, er sehe keine Preise. Fix: neuer deterministischer
**PREISDATEN-Block** im System-Prompt (`llm.format_preise()`): wörtliche €-, Raten-
und Skonto-Zeilen aller sechs Buchungsseiten inkl. URL, unabhängig vom Retrieval.

**3. Selbst errechnete Preise (hoch).** Der Bot rechnete Raten und Summen aus
(„in 4 Monatsraten à etwa 60 €", „Gesamtinvestition ca. 1.435,60 €", „zusammen
knapp 1.436 €") — riskant, weil die Buchungsseite selbst mehrdeutig ist. Fix:
Regel 6 verschärft (nur wörtliche Beträge mit Beschriftung, explizite
Negativ-Beispiele, im Zweifel nur verlinken) + Test-Checks gegen Rechen-Muster.

**4. Off-Topic-Aufgaben wurden erfüllt (mittel).** Auf „Schreib mir ein Gedicht über
Katzen" lieferte der Bot in einem Lauf tatsächlich ein Katzengedicht. Ursache: Es gab
keine explizite Themenbindungs-Regel. Fix: Regel 10 erweitert (themenfremde Aufgaben
freundlich ablehnen, nie erfüllen); seither stabil abgelehnt.

**5. Institut als Behandler dargestellt (mittel).** Bei Gesundheitsfragen klang der
Bot teils, als behandle das DHI selbst („wir klären vor jeder Intervention
medizinische Hintergründe ab"). Fix: Regel 7 ergänzt — das DHI bildet aus, behandelt
nicht, bietet keine Einzelsitzungen; bei Gesundheitsthemen kurz bleiben.

**6. Zu lange Antworten, zu viele Aufzählungspunkte (niedrig).** Antworten bis
151 Wörter mit 5-Punkte-Listen. Fix: Kürze-Regeln geschärft, ERINNERUNGS-Block am
Prompt-Ende (Recency-Effekt), **Temperature 0.3** statt Default 1.0 (neue
`.env`-Variable `TEMPERATURE`) — dadurch insgesamt deutlich konsistenteres Verhalten.

**7. Formatierung: Sternchen-Fett (Spec-Entscheidung).** Haiku nutzt hartnäckig
`**fett**`; das Widget rendert es seit v0.1.1 sauber als `<b>`. Entscheidung v0.2.2:
sparsames Fett (≤ 3 pro Antwort) ist erlaubt; verboten bleiben #-Überschriften,
Tabellen und `*kursiv*` (rendert das Widget nicht). Prompt und Checks entsprechend
angepasst.

**8. Terminlisten überspringen teils den frühesten Termin (niedrig–mittel, offen).**
Bei „Welche Übungstage gibt es in Stuttgart?" fehlte mehrfach der früheste Termin
(30.01.2027), obwohl er in den Termindaten steht. Fix-Versuch: nummerierte,
chronologische Terminliste + explizite Regel; das Problem tritt seltener, aber noch
auf. Alle genannten Termine sind real (keine Erfindungen) — es ist ein
Auslassungs-, kein Halluzinationsproblem.

## Offene Punkte

- **Zwei Stil-Flakes** verbleiben (je Lauf ~2 von 35): (a) bei
  „Stimmt es, dass …?"-Preisfragen fehlt in etwa jedem zweiten Lauf der
  Buchungslink (Antwort inhaltlich korrekt); (b) vereinzelt zu lange Antworten
  (>120 Wörter) bei Selbstbeschreibung/Erklärfragen, selten ein `*kursiv*`.
  Schweregrad niedrig; bei Bedarf wäre der nächste Schritt ein serverseitiger
  Nachbearbeitungs-/Retry-Schritt statt weiterer Prompt-Arbeit.
- **Terminlisten-Auslassung** (Befund 8): Falls das in der Praxis stört, empfiehlt
  sich mittelfristig eine deterministische Terminantwort (strukturierter Filter über
  `termine.json` statt LLM-Auswahl) für reine Terminfragen.
- **Preisfrage ans Institut:** Die Ablefy-Seite zu DHI 2.0 zeigt „239,60 €" mit dem
  Zusatz „Der Betrag wird in 4 Monatsraten beglichen". Ob das eine Monatsrate oder
  ein in vier Raten gezahlter Gesamtbetrag ist, gibt die Seite nicht eindeutig her —
  der Bot zitiert deshalb nur wörtlich und verlinkt. **Bitte beim Institut klären**
  und ggf. die Buchungsseite präzisieren lassen.
- **E2E auf dem Produktivserver** (ToDo 4, letzter Punkt) bleibt offen, bis der VPS
  steht. Der Testkatalog-Runner ist dafür vorbereitet: einfach mit
  `--base-url https://bot.…` gegen den Produktivserver laufen lassen. (Der
  QS-Lauf nutzte den unveränderten Live-Crawl-Datenstand vom 29.07.; ein frischer
  Live-Crawl war aus der Cloud-Testumgebung netzwerkbedingt nicht möglich, der
  Crawler-Code ist von v0.2.2 unberührt.)

## Reproduktion

```bash
pip install -r requirements.txt -r requirements-dev.txt
# Testkatalog (Server mit API-Key + TRUST_PROXY=1 auf Port 8000):
python tests/run_testkatalog.py --base-url http://127.0.0.1:8000
# Widget-Checks (eigener Mock-Server, Port 8123):
playwright install chromium
pytest tests/test_widget.py -v
```

Vollständiges Protokoll des Abnahme-Laufs (alle 35 Fragen, Antworten und
Check-Ergebnisse): [2026-07-30-testlauf-detail.md](2026-07-30-testlauf-detail.md).
