from datetime import timedelta
from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("SECRET_KEY", default="dev-secret-key-change-me")
DEBUG = config("DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "storages",
    # Local apps — Phase 1
    "apps.authentication",
    "apps.businesses",
    "apps.dashboard",
    # Local apps — Phase 2
    "apps.suppliers",
    "apps.customers",
    "apps.inventory",
    # Local apps — Phase 3
    "apps.sales",
    # Local apps — Phase 4
    "apps.expenses",
    "apps.notifications",
    "apps.reports",
    # Local apps — Phase 7 (per-tenant payment provider engine)
    "apps.payments",
    # Local apps — Phase 8 (premium feature add-ons: payments + tax gating)
    "apps.addons",
    # Local apps — Phase 9 (tax module: VAT free-tier + premium tax types/eTIMS)
    "apps.tax",
]

AUTH_USER_MODEL = "authentication.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="smartpos"),
        "USER": config("DB_USER", default="smartpos"),
        "PASSWORD": config("DB_PASSWORD", default="smartpos"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        # Without this, Django opens a fresh TCP+auth handshake to
        # Postgres on every single request and tears it down at the end —
        # fine at low traffic, but it's real latency multiplied by every
        # business's every request once this is serving many shops at
        # once. Keep connections open for 60s and reuse them across
        # requests on the same worker instead.
        "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
        "CONN_HEALTH_CHECKS": True,
    }
}

# Shared cache for rate limiting (DEFAULT_THROTTLE_CLASSES below),
# eventually session/query caching too. This MUST be a shared backend
# once there's more than one gunicorn worker or more than one app-server
# container — Django's default LocMemCache is private to a single
# process, so e.g. the "10/min" login throttle would actually allow
# ~10/min PER WORKER (and per container), not 10/min total, which
# quietly defeats the point of throttling as this scales out. Falls back
# to LocMemCache automatically when REDIS_URL isn't set, so local dev
# needs no extra services running.
REDIS_URL = config("REDIS_URL", default="")
CACHES = (
    {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
    if REDIS_URL
    else {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "login": "10/min",
        "payment_initiate": "20/min",
        "addon_purchase": "10/min",
    },
}

# Hard cap on any single upload (product images etc.) — belt-and-braces
# alongside the app-level compression in apps.inventory; stops an
# oversized file from ever reaching that code in the first place.
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS", default="http://localhost:5173", cast=Csv()
)
CORS_ALLOW_CREDENTIALS = True

# Msafi Labs' own Daraja (M-Pesa STK Push) credentials, used only by
# apps.addons.mpesa to charge shops for add-on purchases (Payments/Tax).
# There is no base MsafiPOS subscription any more — this is the only
# platform-level payment flow left. Referenced in apps/addons/mpesa.py;
# leaving these undefined would crash the first add-on purchase attempt.
PLATFORM_MPESA_SANDBOX = config("PLATFORM_MPESA_SANDBOX", default=True, cast=bool)
PLATFORM_MPESA_CONSUMER_KEY = config("PLATFORM_MPESA_CONSUMER_KEY", default="sy5w7QqVqb95SAiVccw4MpC5pXzJYVgrHwXmI3qDhUSelaRG")
PLATFORM_MPESA_CONSUMER_SECRET = config("PLATFORM_MPESA_CONSUMER_SECRET", default="brOxEs1dGCHGAsoITFGVOTqwlu05POuEI1fya2UrHoI6aGMa0PGuPADmJGzjyGpC")
PLATFORM_MPESA_SHORTCODE = config("PLATFORM_MPESA_SHORTCODE", default="174379")
PLATFORM_MPESA_PASSKEY = config("PLATFORM_MPESA_PASSKEY", default="bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919")
PUBLIC_API_BASE_URL ="https://uncouth-retreat-prewashed.ngrok-free.dev"

# Public base URLs used to build callback links handed to third-party
# payment providers (M-Pesa Daraja, PesaPal) — these must be the
# internet-reachable URL of this API/frontend, not localhost, or their
# callbacks/IPNs will never reach you. See apps/payments/.
PUBLIC_API_BASE_URL = config("PUBLIC_API_BASE_URL", default="http://localhost:8000")
PUBLIC_APP_BASE_URL = config("PUBLIC_APP_BASE_URL", default="http://localhost:5173")

# eTIMS (KRA OSCU/VSCU) base URLs — only known once a business has signed
# up in the eTIMS taxpayer sandbox/production portal. See apps/tax/etims.py.
ETIMS_SANDBOX_BASE_URL = config("ETIMS_SANDBOX_BASE_URL", default="")
ETIMS_PRODUCTION_BASE_URL = config("ETIMS_PRODUCTION_BASE_URL", default="")

# Production hardening — all no-ops in local dev (DEBUG=True), all active
# the moment DEBUG=False in an environment (docker-compose.prod.yml sets
# DEBUG=False). Nothing here needs a code change to "turn on" for
# production; it's driven entirely by the DEBUG env var already in .env.
if not DEBUG:
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7  # 1 week; raise once DNS/cert setup is confirmed stable
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = "DENY"
    # The app itself is behind Nginx/a load balancer in production (see
    # docker-compose.yml) which terminates TLS and forwards this header —
    # without it Django can't tell an already-HTTPS request from an HTTP
    # one and SECURE_SSL_REDIRECT would loop forever.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Serves Django's own static files (admin CSS/JS) directly from Gunicorn
# without needing a separate static-file server for them — Nginx still
# owns the SPA build and proxies /api + /admin through to this container.
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Object storage for user-uploaded media (product photos, business logos,
# avatars, expense receipts) — kept OFF the app server entirely once
# configured. This matters at scale for reasons local disk storage can't
# fix no matter how much RAM/CPU the app server gets:
#   - many businesses uploading photos means the app server's disk fills
#     up and has to keep growing forever;
#   - local files live on ONE server, so you can't run more than one app
#     server (no horizontal scaling) without images going missing
#     depending on which instance served the request;
#   - every image request ties up an app-server worker instead of being
#     served straight from object storage/CDN.
#
# STORAGE_BACKEND=s3 switches `default` to any S3-compatible provider —
# AWS S3, DigitalOcean Spaces, Backblaze B2, Cloudflare R2, Wasabi, etc.
# all speak the same S3 API, so this isn't locked to one vendor. Leave
# STORAGE_BACKEND unset (default "local") and nothing changes — dev/local
# keeps writing to MEDIA_ROOT exactly as before.
STORAGE_BACKEND = config("STORAGE_BACKEND", default="local")
if STORAGE_BACKEND == "s3":
    STORAGES["default"] = {"BACKEND": "storages.backends.s3.S3Storage"}

    AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_ACCESS_KEY_ID = config("AWS_S3_ACCESS_KEY_ID")
    AWS_S3_SECRET_ACCESS_KEY = config("AWS_S3_SECRET_ACCESS_KEY")
    AWS_S3_REGION_NAME = config("AWS_S3_REGION_NAME", default="us-east-1")
    # Only needed for non-AWS S3-compatible providers (DO Spaces, R2,
    # B2...) — leave unset for real AWS S3.
    AWS_S3_ENDPOINT_URL = config("AWS_S3_ENDPOINT_URL", default=None)
    # Front the bucket with a CDN domain if you have one (e.g. a
    # CloudFront/Spaces CDN endpoint) so images load fast for shops
    # anywhere in Kenya instead of round-tripping to the bucket's home
    # region on every request.
    AWS_S3_CUSTOM_DOMAIN = config("AWS_S3_CUSTOM_DOMAIN", default=None)
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=31536000"}  # 1 year — filenames are unique per upload
    AWS_DEFAULT_ACL = "public-read"  # product photos/logos are meant to be publicly viewable on receipts/POS
    AWS_QUERYSTRING_AUTH = False  # public-read objects don't need signed URLs — keeps links short and cacheable
    AWS_S3_FILE_OVERWRITE = False  # never clobber a same-named file from a different business

