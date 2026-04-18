"""
קונפיגורציה מרכזית לשכבת המודיעין הכמותי.
כל פרמטר שלוקחים ממנו החלטה — מופיע כאן, במקום אחד.
"""
from zoneinfo import ZoneInfo

# ── מיקום הפיזי של חוזי הטמפרטורה ──────────────────────────
# חשוב: Polymarket מיישב את החוזים לפי התחזית ל-London City Airport (EGLC)
# כפי שמצויין ב-"Resolution source" של האירוע ב-Wunderground,
# ולא לפי Heathrow (EGLL). הקואורדינטות למטה הן של EGLC.
CITY_NAME_HE = "לונדון (City Airport / EGLC)"
CITY_NAME_EN = "London City Airport"
LAT = 51.5048                    # London City Airport (EGLC) — תחנת הייחוס של Polymarket
LON = 0.0495
TIMEZONE = "Europe/London"
TIMEZONE_TZ = ZoneInfo(TIMEZONE)
# אזור זמן של המשתמש — מוצג במקביל ללונדון בדשבורד
USER_TZ_NAME = "Asia/Jerusalem"
USER_TZ = ZoneInfo(USER_TZ_NAME)

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

# ── סינון חריגים בין-מודלים ───────────────────────────────
# מודל שחורג מעל הסף הזה מהחציון של השאר — מסומן כ-outlier
# בדשבורד (צ'יפ אדום) ומושמט מחישוב הקונצנזוס באותו יום.
OUTLIER_THRESHOLD_C = 2.0

# ── תצוגת חוזים ───────────────────────────────────────────
# להציג רק את N ההסתברויות הגבוהות ביותר בטבלה (פחות רעש).
TOP_N_BUCKETS = 4

# ── מעקב דיוק מודלים לאורך זמן ────────────────────────────
ACCURACY_JSON   = "docs/accuracy.json"     # מדדי דיוק מצטברים
FORECASTS_LOG   = "docs/forecasts.jsonl"   # לוג תחזיות לכל הרצה (append-only)
OBSERVATIONS_JSON = "docs/observations.json"   # מקס' יומי בפועל שנמדד
ACCURACY_MAX_DAYS = 60                      # חלון מעקב דיוק
# נותנים לזה 6 שעות להיסגר אחרי סוף היום לפני שנאסוף תצפית
OBSERVATION_CUTOFF_HOURS = 6
# כמה מודלים עם MAE-נמוך להצליב לשכבת "הסכמה זהב" (לעתיד)
ACCURACY_HIT_WINDOW_C = 1.0                 # "פגע בטווח" = הפרש ≤ זה

# ── תפוקה ─────────────────────────────────────────────────
OUTPUT_DIR  = "docs"
OUTPUT_HTML = "docs/index.html"
OUTPUT_JSON = "docs/data.json"
HISTORY_JSON = "docs/history.json"
HISTORY_MAX_ENTRIES = 96          # ~יממה בקצב 15 דקות
