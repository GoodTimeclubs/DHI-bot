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
    (Renderer aus v0.1.1). Seit der Gate-Erweiterung vom 01.08. beantwortet
    die deterministische Termin-Logik diese Frage (statt des TESTMODUS-Mocks) —
    der Check prüft den Renderer damit am echten Produktionspfad."""
    w = open_chat(desktop)
    w.locator("textarea").fill("Wann ist der nächste Termin für Stufe 1+2?")
    w.locator(".inp button").click()
    antwort = w.locator(".m.bot").nth(1)
    expect(antwort).to_contain_text("Stufe 1+2", timeout=20_000)
    btn = antwort.locator("a.btnlink").first
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


# ── Button-Landschaft der Instituts-Website (v0.3.1) ────────────────────────
# Fixture-Seite, die den Aufbau der echten Website nachstellt: fixierter
# Pseudo-WhatsApp-Button (bottom 20px, 60x60) und eine 5-spaltige CTA-Leiste
# am unteren Rand (nur mobil sichtbar), deren 5. Element den Chat per
# [data-dhi-chat] öffnet. Ausgeliefert per page.route — kein neues File nötig,
# widget.js kommt weiterhin vom echten Testserver (gleicher Origin).

CTA_LEISTE = """
  <nav id="cta-leiste" aria-label="Schnellkontakt">
    <a href="tel:+4960219208003">Anruf</a>
    <a href="https://wa.me/4915154434470">WhatsApp</a>
    <a href="mailto:info@example.de">E-Mail</a>
    <a href="/seminarkalender.html">Termine</a>
    <a href="#chat" id="cta-chat" data-dhi-chat>Chat</a>
  </nav>
"""


def _institut_html(server: str, attrs: str = "", cta: bool = True) -> str:
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  #wa-float {{ position: fixed; right: 20px; bottom: 20px; width: 60px; height: 60px;
               border-radius: 50%; background: #25d366; border: 0; z-index: 99999; }}
  #cta-leiste {{ position: fixed; left: 0; right: 0; bottom: 0; display: none;
                 grid-template-columns: repeat(5, 1fr); background: #1d3557; z-index: 99998; }}
  #cta-leiste a {{ color: #fff; text-align: center; padding: 14px 4px;
                   font: 13px sans-serif; text-decoration: none; }}
  @media (max-width: 640px) {{ #cta-leiste {{ display: grid; }} #wa-float {{ display: none; }} }}
</style></head>
<body>
<h1>Deutsches Hypnoseinstitut — Test-Fixture</h1>
<button id="wa-float" title="WhatsApp"></button>
{CTA_LEISTE if cta else ""}
<script src="{server}/widget.js" data-api="{server}" {attrs} defer></script>
</body></html>"""


def _open_institut(browser, server, profil: dict, attrs: str = "", cta: bool = True):
    """Öffnet die Instituts-Fixture-Seite; Widget wird angehängt (der Float
    kann je nach Attributen bewusst unsichtbar sein — daher kein visible-Wait)."""
    ctx = browser.new_context(**profil)
    page = ctx.new_page()
    html = _institut_html(server, attrs, cta)
    page.route("**/institut.html", lambda route: route.fulfill(
        status=200, content_type="text/html; charset=utf-8", body=html))
    page.goto(f"{server}/institut.html", wait_until="domcontentloaded")
    page.wait_for_selector("#dhi-bot-widget", state="attached")
    return ctx, page


def test_desktop_offset_ueber_whatsapp(browser, server):
    """T18: data-desktop-bottom="96" stapelt den Chat-Button ÜBER den
    WhatsApp-Float — gleiche Flucht rechts, keine Überlagerung."""
    ctx, page = _open_institut(browser, server, DESKTOP, 'data-desktop-bottom="96"')
    try:
        chat = page.locator("#dhi-bot-widget .btn").bounding_box()
        wa = page.locator("#wa-float").bounding_box()
        assert chat["y"] + chat["height"] <= wa["y"], \
            f"Chat-Button ({chat}) überlappt den WhatsApp-Button ({wa})"
        assert chat["y"] < wa["y"], "Chat-Button liegt nicht über dem WhatsApp-Button"
        # gleiche rechte Flucht (beide right: 20px)
        assert abs((chat["x"] + chat["width"]) - (wa["x"] + wa["width"])) <= 2
    finally:
        ctx.close()


def test_desktop_offset_panel_im_viewport(browser, server):
    """T19: Panel wandert mit dem Offset mit (bottom = Offset + 72) und bleibt
    auch auf einem nur 700px hohen Viewport vollständig sichtbar."""
    ctx, page = _open_institut(browser, server,
                               {"viewport": {"width": 1280, "height": 700}},
                               'data-desktop-bottom="96"')
    try:
        w = widget(page)
        w.locator(".btn").click()
        expect(w.locator(".panel")).to_be_visible()
        box = w.locator(".panel").bounding_box()
        assert box["y"] >= 0, f"Panel oben abgeschnitten (y={box['y']})"
        assert box["y"] + box["height"] <= 700.5, "Panel unten abgeschnitten"
        abstand_unten = 700 - (box["y"] + box["height"])
        assert abs(abstand_unten - 168) <= 2, \
            f"Panel klebt nicht bei Offset+72=168px über dem Rand ({abstand_unten}px)"
    finally:
        ctx.close()


def test_mobil_button_off_float_versteckt(browser, server):
    """T20: data-mobile-button="off" blendet den eigenen Float mobil aus —
    auch nach dem 500-ms-Sicherheitsnetz (CTA-Leiste ist ja vorhanden)."""
    ctx, page = _open_institut(browser, server, MOBIL, 'data-mobile-button="off"')
    try:
        expect(page.locator("#dhi-bot-widget .btn")).to_be_hidden()
        page.wait_for_timeout(800)  # Sicherheitsnetz darf NICHT anspringen
        expect(page.locator("#dhi-bot-widget .btn")).to_be_hidden()
    finally:
        ctx.close()


def test_mobil_cta_trigger_oeffnet(browser, server):
    """T21: Klick auf das [data-dhi-chat]-Element der CTA-Leiste öffnet das
    Panel (delegierter Listener), ohne dass der <a>-Link navigiert."""
    ctx, page = _open_institut(browser, server, MOBIL, 'data-mobile-button="off"')
    try:
        w = widget(page)
        page.locator("#cta-chat").click()
        expect(w.locator(".panel")).to_be_visible()
        assert page.url.endswith("institut.html"), "Anker-Link hat navigiert"
        assert page.locator("#cta-chat").get_attribute("aria-expanded") == "true"
    finally:
        ctx.close()


def test_desktop_dhibot_api(browser, server):
    """T22: window.DHIBot.open() öffnet das Panel, close() schließt es —
    auch ganz ohne die neuen data-Attribute."""
    ctx, page = _open_institut(browser, server, DESKTOP)
    try:
        w = widget(page)
        page.evaluate("window.DHIBot.open()")
        expect(w.locator(".panel")).to_be_visible()
        page.evaluate("window.DHIBot.close()")
        expect(w.locator(".panel")).to_be_hidden()
    finally:
        ctx.close()


def test_mobil_fallback_ohne_cta(browser, server):
    """T23: Sicherheitsnetz — "off" auf einer Seite OHNE [data-dhi-chat]
    (z. B. Subdomain ohne CTA-Leiste): der Float erscheint nach kurzem
    Nachlauf trotzdem, sonst wäre der Chat dort mobil unerreichbar."""
    ctx, page = _open_institut(browser, server, MOBIL,
                               'data-mobile-button="off"', cta=False)
    try:
        expect(page.locator("#dhi-bot-widget .btn")).to_be_visible(timeout=5000)
    finally:
        ctx.close()
