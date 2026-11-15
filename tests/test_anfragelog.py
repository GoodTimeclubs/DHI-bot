"""Anonymes Anfrage-Log: Schwärzen, Themen, Speichern, Aufbewahrungsfrist.

    pytest tests/test_anfragelog.py -v
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import anfragelog  # noqa: E402


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(anfragelog, "DB", tmp_path / "anfragen.db")
    return tmp_path / "anfragen.db"


@pytest.mark.parametrize("text, erwartet", [
    ("Meine Mail ist max.muster@web.de, bitte melden", "Meine Mail ist [E-Mail], bitte melden"),
    ("Ruf mich an: 0151 23456789", "Ruf mich an: [Telefon]"),
    ("Tel. +49 (171) 123-45-67 abends", "Tel. [Telefon] abends"),
    ("IBAN DE89 3704 0044 0532 0130 00", "IBAN [IBAN]"),
])
def test_kontaktdaten_werden_geschwaerzt(text, erwartet):
    assert anfragelog.schwaerzen(text) == erwartet


@pytest.mark.parametrize("text", [
    "Termin 11.01.2027 bis 15.01.2027",
    "Stufe 1+2 kostet 3.596,00 € oder 10 Raten à 359,60 €",
    "Telefon 06021 920 8003 oder WhatsApp 0151 544 344 70",  # eigene DHI-Nummern
    "Saison 2026/2027, 66 Termine",
])
def test_normale_inhalte_bleiben_lesbar(text):
    assert anfragelog.schwaerzen(text) == text


@pytest.mark.parametrize("frage, thema", [
    ("Wann ist der nächste Termin?", "Termine"),
    ("Was kostet Stufe 1+2?", "Preise & Zahlung"),
    ("Kann ich mich beraten lassen?", "Beratung & Kontakt"),
    ("Gibt es das auch in Hamburg?", "Standorte & Format"),
    ("Hallo", "Sonstiges"),
])
def test_thema(frage, thema):
    assert anfragelog.thema(frage) == thema


def test_speichern_und_auswerten():
    anfragelog.speichern("g1", "deutsches-hypnoseinstitut.de", "Was kostet das? 0151 23456789", "3.596 €", "llm")
    anfragelog.speichern("g1", "deutsches-hypnoseinstitut.de", "Wann ist der nächste Termin?", "…", "termine")
    anfragelog.speichern("g2", "hybrid.deutsches-hypnoseinstitut.de", "Hallo", "(Fehler)", "fehler")

    d = anfragelog.auswertung(tage=30)
    assert d["gesamt"] == 3 and d["gespraeche"] == 2
    assert d["themen"]["Preise & Zahlung"] == 1
    assert d["seiten"]["deutsches-hypnoseinstitut.de"] == 2
    assert d["arten"]["fehler"] == 1
    assert sum(d["pro_tag"].values()) == 3
    assert d["anfragen"][-1]["frage"] == "Was kostet das? [Telefon]"
    assert anfragelog.auswertung(suche="Termin")["gesamt"] == 1


def test_kein_personenbezug_in_der_tabelle(db):
    anfragelog.speichern("g1", "x.de", "Frage", "Antwort", "llm")
    spalten = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(anfragen)")}
    assert not spalten & {"ip", "user_agent", "cookie"}


def test_alte_eintraege_werden_geloescht(db):
    anfragelog.speichern("g1", "x.de", "alt", "a", "llm")
    with sqlite3.connect(db) as c:
        c.execute("UPDATE anfragen SET ts = '2000-01-01T00:00:00+00:00'")
    anfragelog.speichern("g2", "x.de", "neu", "a", "llm")
    with sqlite3.connect(db) as c:
        assert [r[0] for r in c.execute("SELECT frage FROM anfragen")] == ["neu"]


def test_loeschen():
    anfragelog.speichern("g1", "x.de", "Frage", "Antwort", "llm")
    eid = anfragelog.auswertung()["anfragen"][0]["id"]
    assert anfragelog.loeschen(eid) is True
    assert anfragelog.loeschen(eid) is False
    assert anfragelog.auswertung()["gesamt"] == 0


def test_gespraechs_id_wird_bereinigt():
    anfragelog.speichern("<script>x</script>", "x.de", "F", "A", "llm")
    assert anfragelog.auswertung()["anfragen"][0]["gespraech"] == "scriptxscript"
