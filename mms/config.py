"""Central configuration for the Más Móvil brand-sentiment dashboard."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
DB_PATH = DATA / "masmovil.db"
STATUS_PATH = DATA / "status.json"
HF_HOME = ROOT / ".hf"

BRAND = "Más Móvil Panamá"
LOOKBACK_DAYS = 90

# ---- App stores (verified 10 Oct 2026) ----
GOOGLE_PLAY_APP_ID = "com.cwp.app"            # "Mi Más" / "Más" by Cable & Wireless Panamá
APPLE_APP_ID = "1391146262"                    # apps.apple.com/pa/app/mi-mas/id1391146262
STORE_COUNTRY = "pa"
STORE_LANG = "es"
MAX_REVIEWS_PER_STORE = 300
GOOGLE_PLAY_HARD_CAP = 1500   # free endpoint; ensures the 90-day window is covered

# ---- Social accounts ----
FACEBOOK_PAGE = "https://www.facebook.com/masmovilpanama"     # verified page
INSTAGRAM_PROFILE = "https://www.instagram.com/masmovilpanama/"  # "+Móvil Panamá (@masmovilpanama)"
TIKTOK_PROFILE = "masmovilpanama"   # NOTE: first Apify run (10 Oct 2026) returned no videos for this profile; official handle unconfirmed
TIKTOK_HASHTAGS = ["masmovilpanama"]   # "#masmovil" was mostly Spain/gaming noise
X_HANDLE = "MasMovilPanama"         # verified (id 435865158); support handle @masmovilayuda
X_SEARCH = ['@MasMovilPanama', '@masmovilayuda', '"más móvil" panamá', '#MasMovilPanama']
LINKEDIN_COMPANY = "https://www.linkedin.com/company/masmovil-panama/"

MAX_POSTS_PER_ACCOUNT = 30
MAX_COMMENTS_PER_POST = 15   # Apify FREE plan has a $5/month limit; 50/post could cost ~$10 per refresh
MAX_X_ITEMS = 300

# ---- Apify actors (public Apify Store) ----
ACTORS = {
    "facebook_posts": "apify~facebook-posts-scraper",
    "facebook_comments": "apify~facebook-comments-scraper",
    "instagram_posts": "apify~instagram-scraper",
    "instagram_comments": "apify~instagram-comment-scraper",
    "tiktok_posts": "clockworks~tiktok-scraper",
    "tiktok_comments": "clockworks~tiktok-comments-scraper",
    "x_search": "apidojo~tweet-scraper",
    # LinkedIn company-post actors are pay-per-result and flaky; disabled by default.
    "linkedin_posts": None,
}
APIFY_RUN_TIMEOUT_S = 900
# Hard USD cap per actor run (passed as maxTotalChargeUsd)
MAX_CHARGE_POSTS_USD = 0.50
MAX_CHARGE_COMMENTS_USD = 1.25
MAX_CHARGE_X_USD = 0.20
