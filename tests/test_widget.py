# DHI Bot — Playwright-Checks für das Chat-Widget (Desktop + Mobil)
# ==================================================================
# Prüft die Mobile-Optimierungen aus v0.2.1 und das Desktop-Grundverhalten:
# Vollbild-Chat auf kleinen Screens, Schließen-Button, Tastatur-Follow
# (VisualViewport), 16-px-Eingabe gegen iOS-Auto-Zoom, kein Auto-Fokus auf
# Touch-Geräten, größere Tippflächen, Link-Buttons im Antwort-Renderer.
#
# Ausführen (startet eigenen Server im Mock-Modus auf Port 8123, kein API-Key
# nötig — es müssen aber Index-Daten in data/ liegen, notfalls per
# `python -m app.crawler --from-fixtures`):
#     pip install -r requirements-dev.txt
#     playwright install chromium        # einmalig (entfällt, wenn DHI_CHROMIUM gesetzt)
#     pytest tests/test_widget.py -v
#
# Optional: DHI_CHROMIUM=/pfad/zu/chromium nutzt einen vorhandenen Browser.
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("DHI_TEST_PORT", "8123"))
BASE = f"http://127.0.0.1:{PORT}"

DESKTOP = {"viewport": {"width": 1280, "height": 800}}
MOBIL = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile Safari/604.1",
}


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def server():
    """Startet den Bot im Mock-Modus (deterministisch, keine API-Kosten)."""
    if not (ROOT / "data" / "index.pkl").exists():
        subprocess.run([sys.executable, "-m", "app.crawler", "--from-fixtures"],
                       cwd=ROOT, check=True)
        subprocess.run([sys.executable, "-c",
                        "from app.indexer import build_index; build_index()"],
                       cwd=ROOT, check=True)
    env = {**os.environ, "MOCK_LLM": "1", "CRAWL_ON_START": "never"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{BASE}/api/health", timeout=2).status_code == 200:
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        else:
            raise RuntimeError("Testserver startet nicht")
        yield BASE
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        exe = os.environ.get("DHI_CHROMIUM")
        b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        yield b
        b.close()


def _open_page(browser, server, profil: dict):
    ctx = browser.new_context(**profil)
    page = ctx.new_page()
    page.goto(server, wait_until="domcontentloaded")
    # Der Host-Div selbst ist "unsichtbar" (nur Shadow-Inhalt hat Layout) —
    # daher auf attached warten und dann auf den sichtbaren Start-Button.
    page.wait_for_selector("#dhi-bot-widget", state="attached")
    expect(page.locator("#dhi-bot-widget .btn")).to_be_visible()
    return ctx, page


@pytest.fixture()
def desktop(browser, server):
    ctx, page = _open_page(browser, server, DESKTOP)
    yield page
    ctx.close()


@pytest.fixture()
def mobil(browser, server):
    ctx, page = _open_page(browser, server, MOBIL)
    assert page.evaluate("matchMedia('(pointer: coarse)').matches"), \
        "Touch-Emulation greift nicht — Mobil-Checks wären wirkungslos"
    yield page
    ctx.close()


def widget(page):
    return page.locator("#dhi-bot-widget")


def open_chat(page):
    w = widget(page)
    w.locator(".btn").click()
    expect(w.locator(".panel")).to_be_visible()
    return w


def send_frage(page, text: str):
    w = widget(page)
    w.locator("textarea").fill(text)
    w.locator(".inp button").click()
    # Mock-Antwort abwarten (erste Bot-Blase ist die Begrüßung)
    expect(w.locator(".m.bot").nth(1)).to_contain_text("TESTMODUS", timeout=20_000)
    return w


# ── Desktop ─────────────────────────────────────────────────────────────────

def test_desktop_start_button_panel_zu(desktop):
    """T01: Start-Button sichtbar, Panel anfangs geschlossen."""
    w = widget(desktop)
    expect(w.locator(".btn")).to_be_visible()
    expect(w.locator(".panel")).to_be_hidden()


def test_desktop_panel_schwebt(desktop):
    """T02: Desktop-Panel bleibt schwebendes Fenster (kein Vollbild) — v0.2.1
    darf das Desktop-Verhalten nicht verändert haben."""
    w = open_chat(desktop)
    box = w.locator(".panel").bounding_box()
    vp = desktop.viewport_size
    assert 330 <= box["width"] <= 400, f"unerwartete Breite {box['width']}"
    assert box["width"] < vp["width"] * 0.5
    assert box["x"] + box["width"] <= vp["width"] - 10  # rechts abgesetzt
    radius = w.locator(".panel").evaluate("el => getComputedStyle(el).borderRadius")
    assert radius != "0px"


def test_desktop_begruessung_und_chips(desktop):
    """T03: Begrüßung + 4 Vorschlags-Chips erscheinen beim Öffnen."""
    w = open_chat(desktop)
    expect(w.locator(".m.bot").first).to_contain_text("Ausbildungsberater")
    expect(w.locator(".chip")).to_have_count(4)


def test_desktop_autofokus(desktop):
    """T04: Auf Desktop wird das Eingabefeld automatisch fokussiert."""
    open_chat(desktop)
    tag = desktop.evaluate(
        "document.getElementById('dhi-bot-widget').shadowRoot.activeElement?.tagName")
    assert tag == "TEXTAREA"


def test_desktop_schliessen(desktop):
    """T05: Schließen-Button im Kopf schließt das Panel."""
    w = open_chat(desktop)
    w.locator(".head .x").click()
    expect(w.locator(".panel")).to_be_hidden()
    expect(w.locator(".btn")).to_be_visible()


def test_desktop_chat_roundtrip_linkbuttons(desktop):
    """T06: Frage → Antwort-Roundtrip; URLs werden als Button-Links gerendert
    (Renderer aus v0.1.1)."""
    open_chat(desktop)
    w = send_frage(desktop, "Wann ist der nächste Termin für Stufe 1+2?")
    btn = w.locator(".m.bot").nth(1).locator("a.btnlink").first
    expect(btn).to_be_visible()
    assert btn.get_attribute("target") == "_blank"
    assert (btn.get_attribute("href") or "").startswith("http")


def test_desktop_enter_sendet(desktop):
    """T07: Enter im Eingabefeld sendet die Nachricht."""
    w = open_chat(desktop)
    w.locator("textarea").fill("Was kostet die Ausbildung?")
    w.locator("textarea").press("Enter")
    expect(w.locator(".m.user").first).to_contain_text("Was kostet")
    expect(w.locator(".m.bot").nth(1)).to_contain_text("TESTMODUS", timeout=20_000)


def test_desktop_ki_hinweis(desktop):
    """T08: Pflicht-Hinweis (KI-Assistent, keine sensiblen Gesundheitsdaten)
    steht im Widget-Fuß."""
    w = open_chat(desktop)
    expect(w.locator(".foot")).to_contain_text("KI-Assistent")
    expect(w.locator(".foot")).to_contain_text("Gesundheitsdaten")


# ── Mobil (v0.2.1) ──────────────────────────────────────────────────────────

def test_mobil_vollbild(mobil):
    """T09: Auf kleinen Screens öffnet der Chat als Vollbild ohne Ecken-Radius."""
    w = open_chat(mobil)
    box = w.locator(".panel").bounding_box()
    vp = mobil.viewport_size
    assert abs(box["width"] - vp["width"]) <= 2, f"kein Vollbild: {box['width']}px breit"
    assert box["height"] >= vp["height"] * 0.95
    radius = w.locator(".panel").evaluate("el => getComputedStyle(el).borderRadius")
    assert radius == "0px"


def test_mobil_startbutton_verschwindet(mobil):
    """T10: Im Vollbild wird der schwebende Start-Button ausgeblendet."""
    w = open_chat(mobil)
    expect(w.locator(".btn")).to_be_hidden()


def test_mobil_schliessen_button(mobil):
    """T11: Schließen-Button funktioniert im Vollbild; Start-Button kommt zurück."""
    w = open_chat(mobil)
    w.locator(".head .x").click()
    expect(w.locator(".panel")).to_be_hidden()
    expect(w.locator(".btn")).to_be_visible()


def test_mobil_kein_autofokus(mobil):
    """T12: Auf Touch-Geräten KEIN Auto-Fokus (sonst springt sofort die
    Bildschirmtastatur auf)."""
    open_chat(mobil)
    tag = mobil.evaluate(
        "document.getElementById('dhi-bot-widget').shadowRoot.activeElement?.tagName")
    assert tag != "TEXTAREA"


def test_mobil_16px_eingabe(mobil):
    """T13: Eingabefeld hat 16 px Schrift — verhindert den iOS-Auto-Zoom."""
    w = open_chat(mobil)
    fs = w.locator("textarea").evaluate("el => getComputedStyle(el).fontSize")
    assert fs == "16px", f"font-size ist {fs}"


def test_mobil_touch_ziele(mobil):
    """T14: Chips und Link-Buttons haben mobile Tippflächen (≥ 36 px hoch)."""
    open_chat(mobil)
    chip = widget(mobil).locator(".chip").first.bounding_box()
    assert chip["height"] >= 34, f"Chip nur {chip['height']}px hoch"
    w = send_frage(mobil, "Wann ist der nächste Termin?")
    btn = w.locator(".m.bot").nth(1).locator("a.btnlink").first
    expect(btn).to_be_visible()
    assert btn.bounding_box()["height"] >= 36


def test_mobil_overscroll_contain(mobil):
    """T15: Nachrichtenliste kapselt ihr Scrollen (kein Mitscrollen der Seite)."""
    w = open_chat(mobil)
    osb = w.locator(".msgs").evaluate("el => getComputedStyle(el).overscrollBehavior")
    assert "contain" in osb


def test_mobil_tastatur_follow(mobil):
    """T16: Panel folgt dem VisualViewport — schrumpft der sichtbare Bereich
    (Bildschirmtastatur), passt sich die Panel-Höhe an."""
    w = open_chat(mobil)
    mobil.set_viewport_size({"width": 390, "height": 520})
    mobil.wait_for_timeout(250)  # vv-resize-Handler
    style_h = w.locator(".panel").evaluate("el => el.style.height")
    assert style_h.endswith("px") and 480 <= float(style_h[:-2]) <= 540, \
        f"Panel folgt der Tastatur nicht (style.height={style_h!r})"


def test_widgetjs_mobile_css_regression(server):
    """T17: widget.js enthält die mobilen CSS-Bausteine aus v0.2.1
    (dvh-Vollbild, Safe-Area, Touch-Medienabfrage)."""
    js = httpx.get(f"{server}/widget.js", timeout=10).text
    for merkmal in ("100dvh", "safe-area-inset-bottom", "pointer: coarse",
                    "visualViewport"):
        assert merkmal in js, f"{merkmal} fehlt in widget.js"
