"""
קונפיגורציה מרכזית לשכבת המודיעין הכמותי.
כל פרמטר שלוקחים ממנו החלטה — מופיע כאן, במקום אחד.
"""
from zoneinfo import ZoneInfo

# ── מיקום הפיזי של חוזי הטמפרטורה ──────────────────────────
CITY_NAME_HE = "לונדון"
CITY_NAME_EN = "London"
LAT = 51.4700                    # שדה התעופה הית'רו
LON = -0.4543
TIMEZONE = "Europe/London"
TIMEZONE_TZ = ZoneInfo(TIMEZONE)

# ── חמשת מודלי מזג האוויר הגלובליים ────────────────────────
# (שם תצוגה → slug ב-Open-Meteo)
WEATHER_MODELS = {
    "MeteoFrance": "meteofrance_seamless",
    "ICON":        "icon_seamless",
    "GFS":         "gfs_seamless",
    "UKMO":        "ukmo_seamless",
    "ECMWF":       "ecmwf_ifs025",
}
MIN_MODELS_REQUIRED = 3  # דורשים לפחות 3/5 מודלים זמינים כדי לסמוך על הקונצנזוס

# ── פרמטרים להמרת טמפרטורה → הסתברות ──────────────────────
# σ הוא סטיית תקן של הרעש בתחזית — מינימום 0.7 (לפי המפרט),
# אך נשתמש בסטיית התקן הבין-מודלית אם היא גדולה יותר
# (חוסר הסכמה בין מודלים = אי-ודאות גבוהה יותר).
MIN_SIGMA = 0.7

# ── ולידציה ──────────────────────────────────────────────
TEMP_SANITY_MIN = -20.0          # בלונדון לא קר מזה
TEMP_SANITY_MAX = 45.0           # ולא חם מזה

# ── ספי איתות ─────────────────────────────────────────────
EDGE_THRESHOLD_BUY = 0.03        # 3% – סף קנייה
EDGE_THRESHOLD_STRONG = 0.08     # 8% – סף קנייה חזקה

# סינון חוזים לא-סחירים (מחיר קרוב מאוד ל-0 או 1)
PRICE_MIN_TRADABLE = 0.005
PRICE_MAX_TRADABLE = 0.995

# ── Polymarket ────────────────────────────────────────────
GAMMA_BASE = "https://gamma-api.polymarket.com"
BROAD_SCAN_LIMIT = 1000           # סריקה רחבה של עד 1000 אירועים
MARKET_KEYWORDS_REQUIRED = ["temperature"]        # חייב להופיע בכותרת האירוע
MARKET_KEYWORDS_ANY = ["london", "heathrow"]      # אחת מהן חייבת להופיע
MARKET_CITY_SLUG = "london"                       # לחיפוש slug ישיר

# ── HTTP ─────────────────────────────────────────────────
HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
HTTP_BACKOFF = 1.6

# ── תפוקה ─────────────────────────────────────────────────
OUTPUT_DIR  = "docs"
OUTPUT_HTML = "docs/index.html"
OUTPUT_JSON = "docs/data.json"
HISTORY_JSON = "docs/history.json"
HISTORY_MAX_ENTRIES = 96          # ~יממה בקצב 15 דקות
