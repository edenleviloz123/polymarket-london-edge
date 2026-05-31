"""
קונפיגורציה מרכזית לשכבת המודיעין הכמותי.
כל פרמטר שמקבלים עליו החלטה מופיע כאן, במקום אחד.
"""
from zoneinfo import ZoneInfo

# ── רשימת הערים לסריקה ───────────────────────────────────
# כל ערך ברשימה הוא מילון עם כל מה שצריך לסרוק עיר:
#   קואורדינטות, אזור זמן, תחנת METAR (קוד ICAO),
#   הכתובת בוונדרגראונד, וה-slug של פולימארקט לאותה עיר.
# ניתן להרחיב ערים נוספות בהמשך באמצעות הוספת מילון נוסף.
CITIES = [
    {
        "key":                  "london",
        "display_name_he":      "לונדון",
        "display_name_en":      "London",
        "lat":                  51.5048,
        "lon":                  0.0495,
        "timezone":             "Europe/London",
        "metar_station":        "EGLC",
        "wu_url_part":          "gb/london/EGLC",
        "polymarket_city_slug": "london",
        "unit":                 "C",
    },
    {
        "key":                  "paris",
        "display_name_he":      "פריז",
        "display_name_en":      "Paris",
        "lat":                  49.0097,   # Charles de Gaulle
        "lon":                  2.5479,
        "timezone":             "Europe/Paris",
        "metar_station":        "LFPG",
        "wu_url_part":          "fr/paris/LFPG",
        "polymarket_city_slug": "paris",
        "unit":                 "C",
    },
]

# העיר ה"ברירת-מחדל" לצורכי שליפות גלובליות (אם מישהו עדיין משתמש).
# בעתיד נסיר את זה כליל.
DEFAULT_CITY = CITIES[0]
TIMEZONE_TZ = ZoneInfo(DEFAULT_CITY["timezone"])

# אזור זמן של המשתמש — מוצג במקביל בדשבורד
USER_TZ_NAME = "Asia/Jerusalem"
USER_TZ = ZoneInfo(USER_TZ_NAME)

# ── חמשת מודלי מזג האוויר הגלובליים ────────────────────────
WEATHER_MODELS = {
    "MeteoFrance": "meteofrance_seamless",
    "ICON":        "icon_seamless",
    "GFS":         "gfs_seamless",
    "UKMO":        "ukmo_seamless",
    "ECMWF":       "ecmwf_ifs025",
}
MIN_MODELS_REQUIRED = 3

# ── פרמטרים להמרת טמפרטורה → הסתברות ──────────────────────
MIN_SIGMA = 0.1

# ── ולידציה ──────────────────────────────────────────────
TEMP_SANITY_MIN = -20.0
TEMP_SANITY_MAX = 45.0

# ── ספי איתות ─────────────────────────────────────────────
EDGE_THRESHOLD_BUY = 0.03
EDGE_THRESHOLD_STRONG = 0.08
MIN_PROB_FOR_BUY = 0.30

# סף עליון להסתברות שאנחנו "אמיתית" מאמינים בה. ההיסטוריה הראתה ש-
# 0/7 הימורים עם prob=100% ניצחו, וב-prob>75% המציאות היא ~50% בלבד.
# בגובה הזה אנחנו פשוט מנופחים בביטחון. סף 0.95 חוסם רק את ה-100%.
MAX_PROB_FOR_BUY = 0.95

# סף תחתון למחיר השוק. הימור על מחיר <5% הוא הימור על אירוע נדיר —
# 0/20 ניצחו בהיסטוריה ($589 הפסד מצטבר). מסננים החוצה.
MIN_PRICE_FOR_BUY = 0.05

PRICE_MIN_TRADABLE = 0.005
PRICE_MAX_TRADABLE = 0.995

# ── רשימה שחורה דינמית של buckets ─────────────────────────
# כל (עיר, °C) שיש לה N>=BLACKLIST_MIN_N הימורים סגורים וגם
# אחוז הזכייה <BLACKLIST_MAX_WR נחסם אוטומטית להימורים חדשים.
# לדוגמה כעת: london 17°C (14% WR), london 19°C (11% WR),
# london 27°C (0% WR), paris 18°C (0% WR).
BLACKLIST_ENABLED = True
BLACKLIST_MIN_N   = 5         # דורש לפחות 5 הימורים סגורים
BLACKLIST_MAX_WR  = 0.25      # WR < 25% → רשימה שחורה

# ── סינון לפי הסכמת אנסמבלים ──────────────────────────────
# אם הפער בין הממוצע של ECMWF EPS ל-NOAA GEFS גדול מהסף הזה,
# אי-הוודאות גבוהה מדי — נכפה HOLD ללא קשר ל-edge.
ENSEMBLE_AGREEMENT_MAX_C = 1.0

# ── סינון התמדה (Persistence) ─────────────────────────────
# איתות חייב להופיע ברציפות במספר הרצות עוקבות לפני שירשם כעסקה
# מדומה. עוזר לסנן רעש קצר-טווח של "אותו bucket שמופיע ונעלם".
# הניתוח האחרון הראה -60% ROI לאיתותי צהריים, רובם איתותים רעשניים.
PERSISTENCE_MIN_MINUTES = 8       # ~3 הרצות עוקבות בקצב של 2-5 דק׳
CANDIDATE_STALE_MINUTES = 15      # שכחת candidate אם לא חזר בתוך 15 דק׳
CANDIDATES_FILE = "docs/candidates.json"

# ── תיוג שעת-יום על איתותים ───────────────────────────────
# כל איתות מקבל קטגוריה לפי השעה המקומית של העיר ברגע הרישום.
# אחרי 30+ איתותים נוכל לראות אם יש שעות מסוימות בהן המודל מצליח יותר.
TIME_OF_DAY_BUCKETS = [
    # (שם, שעת התחלה כולל, שעת סיום לא כולל)
    ("night",      0,  6),
    ("morning",    6, 12),
    ("noon",      12, 16),
    ("afternoon", 16, 20),
    ("evening",   20, 24),
]

# ── Polymarket ────────────────────────────────────────────
GAMMA_BASE = "https://gamma-api.polymarket.com"
BROAD_SCAN_LIMIT = 1000
MARKET_KEYWORDS_REQUIRED = ["temperature"]
MARKET_KEYWORDS_ANY = [c["polymarket_city_slug"] for c in CITIES]

# ── HTTP ─────────────────────────────────────────────────
HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
HTTP_BACKOFF = 1.6

# ── Ensemble Prediction Systems ──────────────────────────
OPEN_METEO_ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENSEMBLE_MODELS = {
    "ECMWF EPS": "ecmwf_ifs025",
    "NOAA GEFS": "gfs025",
}
ENSEMBLE_MIN_MEMBERS = 10

# ── סינון חריגים בין-מודלים ───────────────────────────────
OUTLIER_THRESHOLD_C = 2.0

# ── תיקון הטיה שיטתית של מודלים ───────────────────────────
# נתונים היסטוריים בפועל מראים שלכל (עיר, מודל) יש הטיה שיטתית.
# לדוגמה: ECMWF בלונדון +0.58°C (חם מדי), בפריז -1.10°C (קר מדי).
# התיקון הוא דינמי — נשאב אוטומטית מתוך accuracy.json אחרי
# שנצברו לפחות BIAS_CORRECTION_MIN_N ימים.
BIAS_CORRECTION_ENABLED = True
BIAS_CORRECTION_MIN_N   = 5         # דורשים מינימום 5 ימי היסטוריה
BIAS_CORRECTION_MAX_C   = 2.0       # לא מחילים תיקון מעל 2°C (סימן שמשהו אחר מוזר)

# ── תצוגת חוזים ───────────────────────────────────────────
TOP_N_BUCKETS = 4

# ── מעקב דיוק מודלים לאורך זמן ────────────────────────────
ACCURACY_JSON     = "docs/accuracy.json"
FORECASTS_LOG     = "docs/forecasts.jsonl"
OBSERVATIONS_JSON = "docs/observations.json"
ACCURACY_MAX_DAYS = 60
OBSERVATION_CUTOFF_HOURS = 6
ACCURACY_HIT_WINDOW_C = 1.0

# ── מעקב איתותים (paper trading) ─────────────────────────
SIGNALS_LOG         = "docs/signals.jsonl"
PAPER_BANKROLL_USD  = 100.0      # "בנקרול" תאורטי לחישוב גודל פוזיציות
KELLY_FRACTION      = 0.5        # half-kelly — שמרני, מופחת סיכוי לפשיטת רגל

# ── מעקב מחירי שוק לאורך זמן ─────────────────────────────
# כל (עיר, תאריך יעד) מקבל snapshot של מחירי כל ה-buckets כל ~30 דקות.
# זה מאפשר לנו לבנות עקומת כיול של השוק: לענות על "מתי השוק צודק
# יותר" ו-"מהו התזמון הטוב ביותר להימור".
PRICES_LOG          = "docs/prices.jsonl"
PRICES_MIN_INTERVAL_MIN = 25      # רישום רק אם עברו לפחות 25 דק׳ מאז המדידה הקודמת

# ── תפוקה ─────────────────────────────────────────────────
OUTPUT_DIR   = "docs"
OUTPUT_HTML  = "docs/index.html"
OUTPUT_JSON  = "docs/data.json"
HISTORY_JSON = "docs/history.json"
HISTORY_MAX_ENTRIES = 96
