/* FIXTURE — rekonstruiert aus der Live-Datei
 * https://deutsches-hypnoseinstitut.de/assets/js/dhi-seminarkalender.js?v=20260727a
 * (Stand 29.07.2026, 30 Termine). Titel sind aus kind/stage abgeleitet.
 * Dient nur dem Offline-Test des Parsers — der Live-Crawl lädt das Original.
 */
(() => {
  const PRODUCT = {
    presence12: "https://dhi2.de/s/d-hi/dhi1-stufe-1-2-hypnosegrundausbildung-beim-deutschen-hypnoseinstitut",
    presence3: "https://dhi2.de/s/d-hi/dhi-1-0-stufe-3-hypnose-experten-ausbildung-beim-deutschen-hypnoseinstitut",
    hybrid12: "https://dhi2.de/s/d-hi/dhi-2-0-hybrid-hypnoseausbildung-stufe-1-2-inkl-2-praesenzuebungstagen-in-aschaffenburg-189d9303",
    hybrid3: "https://dhi2.de/s/d-hi/dhi-2-0-hybrid-stufe-3-zzgl-2-praesenzuebungstagen-hypnoseausbildung",
    practice12: "https://dhi2.de/s/d-hi/dhi-2-0-hypnosegrundausbildung-beim-deutschen-hypnoseinstitut-dhi-4-tage-in-praesenz-in-aschaffenburg-inkl-abschlusspruefung-83cac65a",
    practice3: "https://dhi2.de/s/d-hi/dhi2-0-praxis-uebungstage-der-stufen-1-2-beim-deutschen-hypnoseinstitut-2-tage-in-praesenzf16c9c37"
  };
  const seminars = [
    {id:"p12-20260921",kind:"presence",stage:"1+2",title:"DHI 1.0 · Stufe 1+2",start:"2026-09-21",end:"2026-09-25",time:"09:30",location:"Aschaffenburg",url:PRODUCT.presence12},
    {id:"p12-20270111",kind:"presence",stage:"1+2",title:"DHI 1.0 · Stufe 1+2",start:"2027-01-11",end:"2027-01-15",time:"09:30",location:"Aschaffenburg",url:PRODUCT.presence12},
    {id:"p12-20270308",kind:"presence",stage:"1+2",title:"DHI 1.0 · Stufe 1+2",start:"2027-03-08",end:"2027-03-12",time:"09:30",location:"Aschaffenburg",url:PRODUCT.presence12},
    {id:"p12-20270531",kind:"presence",stage:"1+2",title:"DHI 1.0 · Stufe 1+2",start:"2027-05-31",end:"2027-06-04",time:"09:30",location:"Aschaffenburg",url:PRODUCT.presence12},
    {id:"p12-20270920",kind:"presence",stage:"1+2",title:"DHI 1.0 · Stufe 1+2",start:"2027-09-20",end:"2027-09-24",time:"09:30",location:"Aschaffenburg",url:PRODUCT.presence12},
    {id:"p3-20261026",kind:"presence",stage:"3",title:"DHI 1.0 · Stufe 3 (Masterclass)",start:"2026-10-26",end:"2026-10-30",time:"09:30",location:"Aschaffenburg",url:PRODUCT.presence3},
    {id:"p3-20270607",kind:"presence",stage:"3",title:"DHI 1.0 · Stufe 3 (Masterclass)",start:"2027-06-07",end:"2027-06-11",time:"",location:"Aschaffenburg",url:PRODUCT.presence3},
    {id:"h12-20270125",kind:"hybrid",stage:"1+2",title:"DHI 2.0 · Stufe 1+2 (Live-Online)",start:"2027-01-25",end:"2027-01-28",time:"09:30",location:"Live-Online",url:PRODUCT.hybrid12},
    {id:"h12-20270405",kind:"hybrid",stage:"1+2",title:"DHI 2.0 · Stufe 1+2 (Live-Online)",start:"2027-04-05",end:"2027-04-08",time:"09:30",location:"Live-Online",url:PRODUCT.hybrid12},
    {id:"h12-20270621",kind:"hybrid",stage:"1+2",title:"DHI 2.0 · Stufe 1+2 (Live-Online)",start:"2027-06-21",end:"2027-06-24",time:"09:30",location:"Live-Online",url:PRODUCT.hybrid12},
    {id:"h3-20270222",kind:"hybrid",stage:"3",title:"DHI 2.0 · Stufe 3 (Live-Online)",start:"2027-02-22",end:"2027-02-25",time:"09:30",location:"Live-Online",url:PRODUCT.hybrid3},
    {id:"h3-20270426",kind:"hybrid",stage:"3",title:"DHI 2.0 · Stufe 3 (Live-Online)",start:"2027-04-26",end:"2027-04-29",time:"09:30",location:"Live-Online",url:PRODUCT.hybrid3},
    {id:"h3-20270712",kind:"hybrid",stage:"3",title:"DHI 2.0 · Stufe 3 (Live-Online)",start:"2027-07-12",end:"2027-07-15",time:"09:30",location:"Live-Online",url:PRODUCT.hybrid3},
    {id:"u12-ab-20270203",kind:"practice",stage:"1+2",title:"DHI 2.0 · Übungstage · Stufe 1+2",start:"2027-02-03",end:"2027-02-04",time:"09:30–16:00",location:"Aschaffenburg",url:PRODUCT.practice12},
    {id:"u12-ab-20270414",kind:"practice",stage:"1+2",title:"DHI 2.0 · Übungstage · Stufe 1+2",start:"2027-04-14",end:"2027-04-15",time:"09:30–16:00",location:"Aschaffenburg",url:PRODUCT.practice12},
    {id:"u12-ab-20270628",kind:"practice",stage:"1+2",title:"DHI 2.0 · Übungstage · Stufe 1+2",start:"2027-06-28",end:"2027-06-29",time:"09:00–16:00",location:"Aschaffenburg",url:PRODUCT.practice12},
    {id:"u12-l-20270421",kind:"practice",stage:"1+2",title:"DHI 2.0 · Übungstage · Stufe 1+2",start:"2027-04-21",end:"2027-04-22",time:"09:30–16:00",location:"Leipzig",url:PRODUCT.practice12},
    {id:"u12-l-20270703",kind:"practice",stage:"1+2",title:"DHI 2.0 · Übungstage · Stufe 1+2",start:"2027-07-03",end:"2027-07-04",time:"09:30–16:00",location:"Leipzig",url:PRODUCT.practice12},
    {id:"u12-s-20270130",kind:"practice",stage:"1+2",title:"DHI 2.0 · Übungstage · Stufe 1+2",start:"2027-01-30",end:"2027-01-31",time:"09:30–16:00",location:"Stuttgart",url:PRODUCT.practice12},
    {id:"u12-s-20270410",kind:"practice",stage:"1+2",title:"DHI 2.0 · Übungstage · Stufe 1+2",start:"2027-04-10",end:"2027-04-11",time:"09:30–16:00",location:"Stuttgart",url:PRODUCT.practice12},
    {id:"u12-s-20270707",kind:"practice",stage:"1+2",title:"DHI 2.0 · Übungstage · Stufe 1+2",start:"2027-07-07",end:"2027-07-08",time:"09:00–16:00",location:"Stuttgart",url:PRODUCT.practice12},
    {id:"u3-ab-20270227",kind:"practice",stage:"3",title:"DHI 2.0 · Übungstage · Stufe 3",start:"2027-02-27",end:"2027-02-28",time:"09:30",location:"Aschaffenburg",url:PRODUCT.practice3},
    {id:"u3-ab-20270505",kind:"practice",stage:"3",title:"DHI 2.0 · Übungstage · Stufe 3",start:"2027-05-05",end:"2027-05-06",time:"09:30",location:"Aschaffenburg",url:PRODUCT.practice3},
    {id:"u3-ab-20270726",kind:"practice",stage:"3",title:"DHI 2.0 · Übungstage · Stufe 3",start:"2027-07-26",end:"2027-07-27",time:"09:30",location:"Aschaffenburg",url:PRODUCT.practice3},
    {id:"u3-l-20270302",kind:"practice",stage:"3",title:"DHI 2.0 · Übungstage · Stufe 3",start:"2027-03-02",end:"2027-03-03",time:"09:30",location:"Leipzig",url:PRODUCT.practice3},
    {id:"u3-l-20270512",kind:"practice",stage:"3",title:"DHI 2.0 · Übungstage · Stufe 3",start:"2027-05-12",end:"2027-05-13",time:"09:30",location:"Leipzig",url:PRODUCT.practice3},
    {id:"u3-l-20270717",kind:"practice",stage:"3",title:"DHI 2.0 · Übungstage · Stufe 3",start:"2027-07-17",end:"2027-07-18",time:"09:30",location:"Leipzig",url:PRODUCT.practice3},
    {id:"u3-s-20270317",kind:"practice",stage:"3",title:"DHI 2.0 · Übungstage · Stufe 3",start:"2027-03-17",end:"2027-03-18",time:"09:30",location:"Stuttgart",url:PRODUCT.practice3},
    {id:"u3-s-20270508",kind:"practice",stage:"3",title:"DHI 2.0 · Übungstage · Stufe 3",start:"2027-05-08",end:"2027-05-09",time:"09:30",location:"Stuttgart",url:PRODUCT.practice3},
    {id:"u3-s-20270721",kind:"practice",stage:"3",title:"DHI 2.0 · Übungstage · Stufe 3",start:"2027-07-21",end:"2027-07-22",time:"09:30",location:"Stuttgart",url:PRODUCT.practice3}
  ];
  const notes = [
    "Weitere Übungsstandorte: Hamburg, Oberstaufen-Steibis und Gallicano (Toskana) — Termine nach Vereinbarung, Details auf hybrid.deutsches-hypnoseinstitut.de/uebungstage-standorte.html"
  ];
  window.__DHI_FIXTURE = { PRODUCT, seminars, notes };
})();
