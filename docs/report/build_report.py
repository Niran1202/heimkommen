"""Generate docs/Heimkommen_Project_Report.pdf.

    python docs/report/build_report.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[2]
IMG = ROOT / "docs" / "img"
OUT = ROOT / "docs" / "Heimkommen_Project_Report.pdf"
FONTS = Path("C:/Windows/Fonts")

# Arial covers the characters used below (ü, ≤, →, –); ReportLab's built-in Helvetica does not.
pdfmetrics.registerFont(TTFont("Body", str(FONTS / "arial.ttf")))
pdfmetrics.registerFont(TTFont("Body-Bold", str(FONTS / "arialbd.ttf")))
pdfmetrics.registerFont(TTFont("Body-Italic", str(FONTS / "ariali.ttf")))
pdfmetrics.registerFont(TTFont("Mono", str(FONTS / "consola.ttf")))
pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-Bold")

INK, INK2, LINE, ACCENT, TINT = (colors.HexColor(c) for c in ("#0b0b0b", "#52514e", "#e1e0d9", "#2a78d6", "#f1f0ec"))

base = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("title", parent=base["Title"], fontName="Body-Bold", fontSize=26, leading=31,
                            textColor=INK, alignment=TA_CENTER, spaceAfter=6),
    "subtitle": ParagraphStyle("subtitle", fontName="Body", fontSize=13, leading=18, textColor=INK2,
                               alignment=TA_CENTER),
    "h1": ParagraphStyle("h1", fontName="Body-Bold", fontSize=16, leading=20, textColor=INK, spaceBefore=14,
                         spaceAfter=6, keepWithNext=1),
    "h2": ParagraphStyle("h2", fontName="Body-Bold", fontSize=12, leading=15, textColor=INK, spaceBefore=10,
                         spaceAfter=4, keepWithNext=1),
    "body": ParagraphStyle("body", fontName="Body", fontSize=10, leading=14.5, textColor=INK, spaceAfter=5),
    "small": ParagraphStyle("small", fontName="Body", fontSize=8.5, leading=11.5, textColor=INK2),
    "cell": ParagraphStyle("cell", fontName="Body", fontSize=8.8, leading=11.5, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Body-Bold", fontSize=8.8, leading=11.5, textColor=INK),
    "caption": ParagraphStyle("caption", fontName="Body-Italic", fontSize=8.5, leading=11, textColor=INK2,
                              alignment=TA_CENTER, spaceAfter=8),
}


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def bullets(items: list[str]) -> ListFlowable:
    return ListFlowable([ListItem(p(i), leftIndent=12, value="•") for i in items], bulletType="bullet",
                        start="•", leftIndent=12, bulletFontName="Body", bulletFontSize=9)


def table(rows: list[list[str]], widths: list[float], bold_last_col: bool = False) -> Table:
    data = [[p(c, "cellb") for c in rows[0]]]
    for row in rows[1:]:
        data.append([p(c, "cellb" if bold_last_col and i == len(row) - 1 else "cell") for i, c in enumerate(row)])
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TINT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK2),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def image(path: Path, width_mm: float, caption: str) -> KeepTogether:
    img = Image(str(path))
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth, img.drawHeight = width_mm * mm, width_mm * mm * ratio
    return KeepTogether([img, Spacer(1, 3), p(caption, "caption")])


def footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Body", 8)
    canvas.setFillColor(INK2)
    canvas.drawString(20 * mm, 12 * mm, "Heimkommen – project report")
    canvas.drawRightString(190 * mm, 12 * mm, f"Page {doc.page}")
    canvas.setStrokeColor(LINE)
    canvas.line(20 * mm, 16 * mm, 190 * mm, 16 * mm)
    canvas.restoreState()


def story() -> list:
    s: list = []

    # Title page
    s += [Spacer(1, 45 * mm)]
    icon = IMG / "icon.png"
    if icon.exists():
        s += [Image(str(icon), width=28 * mm, height=28 * mm), Spacer(1, 8 * mm)]
    s += [p("Heimkommen", "title"),
          p("Will I get home tonight?", "subtitle"),
          Spacer(1, 4 * mm),
          p("Regional journey planning with real delay risk for the Schwarzwald-Baar-Heuberg region", "subtitle"),
          Spacer(1, 30 * mm),
          p("Project report · September 2026", "subtitle"),
          Spacer(1, 3 * mm),
          p("github.com/Niran1202/heimkommen · github.com/Niran1202/heimkommen-desktop", "subtitle"),
          PageBreak()]

    # 1 Summary
    s += [p("1. Summary", "h1"),
          p("Most journey planners assume every connection works. Heimkommen instead estimates <b>how likely</b> "
            "each connection is to work, based on six months of real train delays, and answers the question a "
            "traveller actually has late in the evening: <i>will I get home tonight, and which train should I "
            "take?</i>"),
          p("For every journey the app shows the probability that all connections work, the probability of "
            "arriving at most five minutes late, the probability of getting home at all tonight, the weakest "
            "connection with a Plan B, and the latest departure that is still safe."),
          p("In a replay of 891 real evening journeys from July and August 2026 (months the model never saw), "
            "Heimkommen's probabilities were clearly better than both a timetable-only planner and a "
            "historical-median approach on every measure (section 7)."),
          p("The project is available in three forms built from the same code:", "body"),
          table([["Form", "Where", "Notes"],
                 ["Web application", "github.com/Niran1202/heimkommen",
                  "Accounts, saved trips, nightly accuracy tracking, Docker deployment"],
                 ["Windows desktop app", "github.com/Niran1202/heimkommen-desktop (release v1.0.0)",
                  "Installer or portable zip, no login, everything bundled"],
                 ["Local development", "Developer PC", "SQLite database, runs without Docker"]],
                [38, 62, 70])]

    # 2 How it works
    s += [p("2. How it works", "h1"),
          table([["Step", "What happens"],
                 ["1. Routing", "A RAPTOR route planner finds journeys in the official NVBW timetable."],
                 ["2. Delay prediction", "A machine-learning model predicts, for each train, the range of delays "
                  "at the boarding and alighting station, plus its chance of being cancelled."],
                 ["3. Simulation", "2,000 possible evenings are played out per journey: sample delays, check "
                  "every connection, switch to the next train if one is missed, mark the run “stranded” if "
                  "nothing is left that night."],
                 ["4. Answer", "The share of successful runs becomes the probabilities shown to the user."]],
                [38, 132]),
          Spacer(1, 4)]
    if (IMG / "journey_card.png").exists():
        s += [image(IMG / "journey_card.png", 52, "Figure 1 – A journey on a phone: risk per connection, the "
                                                 "weak point (5-minute change in Rottweil), Plan B and the map.")]

    # 3 Data
    s += [p("3. Data sources", "h1"),
          table([["Data", "Source and licence", "What was used", "Used for"],
                 ["Timetable", "NVBW “bwgesamt” GTFS feed, version 20260913 (CC BY 4.0)",
                  "705 MB ZIP, valid 3 May – 12 Dec 2026", "Routing"],
                 ["Historical delays", "piebro/deutsche-bahn-data on Hugging Face (CC BY 4.0, data by Deutsche Bahn)",
                  "6 monthly files, March–August 2026, ~600 MB each (all of Germany)", "Training and evaluation"],
                 ["Yesterday's train times", "Same dataset, raw daily API responses",
                  "e.g. 22 Sep 2026: 112,252 stop events", "Nightly accuracy check"],
                 ["Live delays", "DB Timetables API (DB API Marketplace, free plan)",
                  "Only on request; cached 60 s, max. 30 calls/min", "Live status"],
                 ["Map tiles", "OpenStreetMap (ODbL)", "Only when a map is opened", "Journey map"]],
                [26, 52, 55, 37]),
          p("Imported timetable", "h2"),
          p("Rail was kept for all of Baden-Württemberg (so long regional trips can be planned); buses only in the "
            "three region districts. Result: 527 routes, 65,918 trips, 1,122,593 stop times, 8,549 stops, "
            "8,806 service calendars, 337,769 calendar exceptions and 15,966 transfer rules, imported in "
            "80 seconds."),
          p("Delay history", "h2"),
          p("After filtering to the matched stations, about 3 million stop records per month remain (roughly "
            "18 million in total). Rail-replacement bus rows and unscheduled extra stops were removed.")]

    # 4 Station matching
    s += [p("4. Linking the two datasets", "h1"),
          p("The timetable and the delay data name stations differently (“Villingen Bahnhof/ZOB” vs. "
            "“Villingen (Schwarzw)”). Stations were therefore matched by <b>timetable coincidence</b>: if the same "
            "train number stops at the same minute in both datasets, that is a vote for the pair."),
          bullets(["Input: four days in August 2026 – 450,666 timetable events and 1,838,273 delay-data events.",
                   "Votes are counted per distinct train, so a single train number that collides with another "
                   "operator's train cannot win; pairs whose names share no word need at least five trains.",
                   "Result: 1,016 stations matched (977 by timetable, 39 by name as fallback); all key stations "
                   "are correct."])]

    # 5 Models
    s += [PageBreak(), p("5. Models and algorithms", "h1"),
          p("No deep learning and no language model is used in the product."),
          table([["Component", "Type", "Trained?"],
                 ["Delay model", "8 LightGBM quantile-regression models (5, 10, 25, 50, 75, 90, 95, 98 %)",
                  "Yes, on historical delays"],
                 ["Cancellation model", "Historical rate per line × station, pulled towards the line and product "
                  "average when data is sparse", "Computed from data"],
                 ["Baselines", "Historical quantiles per line × station; historical median", "Computed from data"],
                 ["Router", "RAPTOR (Delling et al., 2012), own Python implementation", "No – algorithm"],
                 ["Simulator", "Monte Carlo (NumPy), samples from the predicted quantiles", "No – uses the model"]],
                [34, 96, 40]),
          p("How the delay model was trained", "h2"),
          table([["Aspect", "Choice"],
                 ["Unit of data", "One row per train arrival or departure at a station"],
                 ["Features (10)", "Product (RE/RB/S/long distance), operator, line, station, hour, weekday, stop "
                  "number and relative position along the run, arrival/departure, delay at the previous stop"],
                 ["Target", "Delay in minutes, clipped to −5…120; cancelled events handled separately"],
                 ["Split (by time)", "Training March–June 2026: 2,713,317 events. Test July–August 2026: "
                  "578,578 events. Never a random split."],
                 ["Previous-stop delay", "Hidden for half of the training rows, so the model works both when "
                  "planning ahead (unknown) and with live data (known)"],
                 ["Settings", "Quantile objective, learning rate 0.08, 63 leaves, ≥ 200 rows per leaf, "
                  "300 rounds, 90 % feature sampling, 80 % bagging, seed 42, native categorical features"],
                 ["Most important", "Station, line, operator, stop number, previous delay, hour"],
                 ["Safety rule", "A new model is activated only if it scores at least as well as the current one"],
                 ["Output", "Model v1, about 28 MB"]],
                [38, 132])]

    # 6 Architecture
    s += [p("6. System architecture", "h1"),
          bullets(["<b>Offline (laptop):</b> download and filter delay data, train the model, run the replay "
                   "evaluation. The large data never leaves the laptop.",
                   "<b>Server:</b> FastAPI backend with the in-memory timetable, delay model and simulator; "
                   "PostgreSQL, Redis, Celery jobs (daily data update, nightly accuracy check, weekly retrain); "
                   "Caddy for HTTPS; Prometheus and Grafana for monitoring.",
                   "<b>Frontend:</b> React single-page app (phone first, light and dark mode) with a Leaflet map.",
                   "<b>Desktop:</b> the same backend and frontend packaged as one Windows program that opens in "
                   "its own window."]),
          Spacer(1, 4)]

    # 7 Results
    s += [PageBreak(), p("7. Results", "h1"),
          p("Delay model on the test months", "h2"),
          table([["Method", "Average quantile loss (lower is better)"],
                 ["LightGBM, planning mode", "1.006"],
                 ["LightGBM, previous-stop delay known", "0.986"],
                 ["Historical quantiles per line × station", "1.053"],
                 ["Historical median", "1.786"]], [100, 70]),
          p("Calibration of the upper range: 88.5 % of delays fell below the predicted 90th percentile, "
            "93.9 % below the 95th and 97.3 % below the 98th. Cancellations are only marginally better than a "
            "single global rate (Brier 0.0338 vs. 0.0343)."),
          p("Full journeys: historical replay", "h2"),
          p("910 evening journeys were planned on every second day of July–August 2026 (12 origin/destination "
            "pairs, 4 departure times); 891 had complete real data to compare against."),
          table([["Brier score (lower is better)", "Timetable only", "Historical median", "Heimkommen"],
                 ["All connections work (happened 76 %)", "0.241", "0.168", "0.127"],
                 ["Arrive ≤ 5 min late (happened 53 %)", "0.473", "0.391", "0.216"],
                 ["Stranded (happened 4 %)", "0.043", "0.043", "0.033"]],
                [70, 32, 36, 32], bold_last_col=True),
          Spacer(1, 6)]
    if (IMG / "brier.png").exists():
        s += [image(IMG / "brier.png", 130, "Figure 2 – Brier scores of the three methods in the replay.")]
    if (IMG / "calibration.png").exists():
        s += [image(IMG / "calibration.png", 95, "Figure 3 – Calibration: predicted probability vs. how often "
                                                 "it actually happened.")]
    s += [p("Where it is weaker", "h2"),
          table([["Shortest change in the journey", "Journeys", "Predicted to work", "Actually worked"],
                 ["≤ 5 min", "93", "38 %", "27 %"],
                 ["6–10 min", "187", "66 %", "59 %"],
                 ["> 10 min", "240", "86 %", "80 %"]], [70, 30, 36, 34]),
          p("The simulator is optimistic about tight connections. Train delays are simulated independently of "
            "each other, whereas in reality a bad evening affects many trains at once."),
          p("Live check", "h2"),
          p("On 22 September 2026, 30 logged predictions were matched with what really happened: connection "
            "Brier score 0.139 vs. 0.207 for timetable-only."),
          p("A finding for travellers", "h2"),
          table([["From → To (Friday, Deutschlandticket)", "Last departure", "Chance to get home",
                  "Latest ≥ 95 % safe"],
                 ["Stuttgart Hbf → Villingen", "22:17", "81 %", "21:14"],
                 ["Stuttgart Hbf → Donaueschingen", "20:23", "79 %", "19:14"],
                 ["Stuttgart Hbf → Bad Dürrheim", "20:23", "18 %", "none"],
                 ["Freiburg Hbf → Villingen", "22:42", "78 %", "21:00"]], [70, 30, 36, 34])]

    # 8 Software
    s += [PageBreak(), p("8. Software and libraries", "h1"),
          table([["Area", "Libraries and tools (version)"],
                 ["Web API", "FastAPI 0.141, Starlette 1.7, Uvicorn 0.53, Pydantic 2.13, pydantic-settings 2.15"],
                 ["Database", "SQLAlchemy 2.0.54, Alembic 1.20, SQLite (local) / PostgreSQL 16 via psycopg 3.3"],
                 ["Data and ML", "NumPy 2.5, pandas 3.0, PyArrow 25, LightGBM 4.7, SciPy 1.18"],
                 ["Background jobs", "Celery 5.6, Redis 7 (client 8.1)"],
                 ["Security", "bcrypt 5.0, python-jose 3.5, defusedxml 0.7, email-validator 2.3"],
                 ["Other backend", "httpx 0.28, prometheus-client 0.26, tzdata"],
                 ["Frontend", "React 18.3, React Router 6.30, TypeScript 5.9, Vite 5.4, Leaflet 1.9, "
                  "openapi-typescript 7.13, ESLint 9.39"],
                 ["Analysis", "Jupyter notebooks (nbclient), matplotlib 3.11"],
                 ["Testing and quality", "pytest 9.1 (38 unit/API + 2 integration tests), testcontainers, "
                  "Playwright 1.63, ruff 0.16, mypy 2.3"],
                 ["Infrastructure", "Docker and Docker Compose, Caddy, Prometheus, Grafana, GitHub Actions"],
                 ["Desktop packaging", "PyInstaller 6.22, pywebview 6.2 with Edge WebView2, Inno Setup 6, Pillow 12.3"],
                 ["Development tools", "Python 3.14 (Docker images use 3.12), Node 26, Git, GitHub CLI, VS Code, "
                  "Claude Code (AI coding assistant)"]],
                [38, 132])]

    # 9 Quality
    s += [p("9. Quality and delivery", "h1"),
          bullets(["38 unit and API tests pass; ruff and mypy report no issues; the frontend lints and builds.",
                   "Continuous integration on GitHub is green, including a job that runs the whole stack in Docker.",
                   "The user interface was checked in a real browser at phone and desktop width, light and dark mode.",
                   "The Windows app was tested end to end: install, launch, correct results, uninstall. The "
                   "installer is 86 MB and needs no administrator rights."])]
    if (IMG / "desktop_app.png").exists():
        s += [image(IMG / "desktop_app.png", 150, "Figure 4 – The Windows desktop app: no login, same results "
                                                  "as the web version.")]

    # 10 Limitations
    s += [p("10. Known limitations and next steps", "h1"),
          table([["Limitation", "Next step"],
                 ["Long-distance trains mostly missing (the NVBW feed has only 4 such lines)",
                  "Add DB's national long-distance feed"],
                 ["Tight connections are predicted too optimistically",
                  "Model correlated delays (network-wide bad evenings), station-specific change times"],
                 ["Buses and trams assumed on time; only in the three region districts",
                  "Add bus delay data if it becomes available"],
                 ["Timetable valid until 12 December 2026", "Import the next NVBW feed and rebuild"],
                 ["Cancellations barely better than a global rate", "Use disruption and construction information"],
                 ["Windows installer is not code-signed", "Sign it to avoid the SmartScreen warning"]],
                [85, 85]),
          Spacer(1, 10),
          p("Heimkommen is an independent student project and not an official Deutsche Bahn service. "
            "Predictions are estimates. Timetable © NVBW; delay history piebro/deutsche-bahn-data (CC BY 4.0, "
            "data by Deutsche Bahn); map © OpenStreetMap contributors.", "small")]
    return s


def main() -> None:
    doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                            bottomMargin=22 * mm, title="Heimkommen – project report", author="Niran1202",
                            subject="Regional journey planning with delay risk")
    doc.build(story(), onFirstPage=lambda c, d: None, onLaterPages=footer)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
