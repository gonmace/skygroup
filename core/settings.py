import os
from decouple import config, Csv

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(PROJECT_DIR)

_SECRET_KEY_DEFAULT = 'django-insecure-default-only-for-dev-run-make-setup'
SECRET_KEY = config('SECRET_KEY', default=_SECRET_KEY_DEFAULT)

DEBUG = config('DEBUG', default=False, cast=bool)

# Validar solo cuando existe .env (entorno configurado) pero SECRET_KEY no fue definido.
# Sin .env = instalación inicial, el default es aceptable.
if SECRET_KEY == _SECRET_KEY_DEFAULT and os.path.exists(os.path.join(BASE_DIR, '.env')):
    raise ValueError("SECRET_KEY no está en .env. Ejecuta 'make setup' para generarlo.")

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='', cast=Csv())

# En producción (DEBUG apagado) no se arranca con la clave de ejemplo ni sin hosts: en el contenedor no hay .env
# (las variables llegan por env_file), así que la comprobación de arriba no alcanza.
if not DEBUG:
    from django.core.exceptions import ImproperlyConfigured
    if SECRET_KEY == _SECRET_KEY_DEFAULT:
        raise ImproperlyConfigured('SECRET_KEY no está definida: con DEBUG apagado se usaría la clave de ejemplo.')
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured('ALLOWED_HOSTS está vacío: define los dominios del sitio en .env.')

ADMIN_URL = config('ADMIN_URL', default='admin/')

# Application definition

INSTALLED_APPS = [
    'home',
    'empresas',
    'cuentas',
    'proyectos',
    'archivos',
    'panel',
    'notificaciones',
    'mje_mensajes',
    'tar_tickets',
    'tar_adjuntos',
    'reg_base',
    'reg_txtss',
    'reg_construccion',
    'reg_construccion_base',
    'reg_fotos',
    'reg_actividades',
    'jor_empleados',
    'jor_diario',
    'jor_actividades',
    'jor_reportes',
    'axes',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'csp.middleware.CSPMiddleware',
    'archivos.middleware.MediaCspMiddleware',  # añade la CDN configurada en el admin al CSP
    'django.contrib.sessions.middleware.SessionMiddleware',
    'axes.middleware.AxesMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'empresas.embebido.EmbebidoMiddleware',  # permite iframes solo desde el Nextcloud de la empresa (y FRAME_ANCESTORS)
    'cuentas.impersonacion.ImpersonacionMiddleware',  # superusuario → ver como otro usuario
    # Debe ir al FINAL: necesita request.user y messages (ver empresas/tenancy.py).
    'empresas.tenancy.EmpresaMiddleware',
]

INSTALLED_APPS += ['tailwind', 'theme']
TAILWIND_APP_NAME = 'theme'

ASGI_APPLICATION = 'core.asgi.application'

if DEBUG:
    # daphne antes que staticfiles: su `runserver` es ASGI (HTTP + WebSocket) y sigue sirviendo estáticos.
    INSTALLED_APPS.insert(0, 'daphne')
    INSTALLED_APPS += ['django_browser_reload']
    MIDDLEWARE += ['django_browser_reload.middleware.BrowserReloadMiddleware']
    INTERNAL_IPS = ['127.0.0.1', '::1']
    import sys
    if sys.platform == 'win32':
        NPM_BIN_PATH = r'C:\Program Files\nodejs\npm.cmd'

AUTH_USER_MODEL = 'cuentas.User'
LOGIN_URL = 'cuentas:login'
LOGIN_REDIRECT_URL = 'home'  # se resuelve con el prefijo de la empresa del request
LOGOUT_REDIRECT_URL = 'cuentas:login'

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'cuentas.backends.EmailBackend',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'empresas.context_processors.marca_empresa',
                'empresas.context_processors.selector_empresas',
                'empresas.context_processors.papel_plataforma',
                'panel.menu.menu_lateral',
                'notificaciones.context_processors.campana',
                'mje_mensajes.context_processors.mensajeria',
                'jor_diario.context_processors.jornada_hoy',
                'cuentas.context_processors.nextcloud_cuenta',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

# Database: SQLite por defecto en dev, PostgreSQL si se define POSTGRES_DB
if config('POSTGRES_DB', default=''):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('POSTGRES_DB'),
            'USER': config('POSTGRES_USER'),
            'PASSWORD': config('POSTGRES_PASSWORD'),
            'HOST': config('POSTGRES_HOST', default='postgres'),
            'PORT': config('POSTGRES_PORT', default='5432'),
            'CONN_MAX_AGE': 60,
            'CONN_HEALTH_CHECKS': True,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': config('SQLITE_PATH', default=os.path.join(BASE_DIR, 'db.sqlite3')),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    # Sin UserAttributeSimilarityValidator (decisión del propietario): se permite una contraseña parecida al correo.
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es'
TIME_ZONE = 'America/La_Paz'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
WHITENOISE_MANIFEST_STRICT = not DEBUG  # True en prod: rechaza archivos sin entrada en manifest

# ── Media ─────────────────────────────────────────────────────────────────────
# Modo (local / S3), bucket, credenciales y URL de la CDN se configuran en el admin
# (app `archivos`) y aplican sin reiniciar. HybridMediaStorage se comporta como
# ConfigurableMediaStorage y, en modo S3, además sigue sirviendo lo que aún
# está en disco hasta moverlo con `manage.py media_a_cdn` (ver archivos/storage.py).
S3_URL_EXPIRE = config('S3_URL_EXPIRE', default=300, cast=int)  # segundos de las URLs firmadas (privados)
# Token de los endpoints internos (n8n/cron, cabecera X-Internal-Token). Vacío = deshabilitados.
INTERNAL_API_TOKEN = config('INTERNAL_API_TOKEN', default='')
DISK_ALERT_PERCENT = config('DISK_ALERT_PERCENT', default=85, cast=int)

FOTO_MAX_SIZE = config('FOTO_MAX_SIZE', default=25 * 1024 * 1024, cast=int)  # 25 MB por foto (Registros)

# ── Adjuntos de Tareas ────────────────────────────────────────────────────────
ATTACHMENT_MAX_SIZE = config('ATTACHMENT_MAX_SIZE', default=20 * 1024 * 1024, cast=int)  # 20 MB
ATTACHMENT_ALLOWED_TYPES = (
    'image/', 'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'text/plain', 'text/csv',
)

STORAGES = {
    'staticfiles': {
        # CompressedManifestStaticFilesStorage: hashes en filenames (cache-busting seguro)
        # + archivos .gz pre-generados que nginx sirve con gzip_static on
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
    # Media pública: config en el admin (app 'archivos'); híbrido para activar S3 sin migrar antes
    'default': {'BACKEND': 'archivos.storage.HybridMediaStorage'},
    'privado': {'BACKEND': 'archivos.storage.HybridPrivateStorage'},
}

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Email: el backend de la plataforma usa el SMTP configurado en Plataforma → Correo (BD) y, si no hay, el de abajo:
# consola en dev, SMTP en prod si se configura EMAIL_HOST en el .env.
EMAIL_BACKEND = 'cuentas.correo_backend.EmailBackend'
if config('EMAIL_HOST', default=''):
    EMAIL_BACKEND_BASE = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = config('EMAIL_HOST')
    EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
    EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
    EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
    DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@example.com')
else:
    EMAIL_BACKEND_BASE = 'django.core.mail.backends.console.EmailBackend'

# ── Seguridad ──────────────────────────────────────────────────────────────────
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REDIRECT_EXEMPT = [r'^healthz$']  # healthcheck interno de Docker (HTTP plano)

# Detrás de nginx (producción) o ngrok (pruebas en celular) la petición llega como HTTP; sin esto
# `request.is_secure()` es falso y el origen esperado por WebAuthn (passkey) no coincide con el del navegador.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

X_FRAME_OPTIONS = 'DENY'
# Ruta de skygroup dentro de Nextcloud (app «External sites»): a ella se vuelve tras vincular el celular fuera del iframe.
NEXTCLOUD_APP_RUTA = config('NEXTCLOUD_APP_RUTA', default='/apps/external/1/')
# Orígenes que pueden mostrar la app en un iframe además del Nextcloud de cada empresa (p. ej. https://sky.midominio.com).
FRAME_ANCESTORS = config('FRAME_ANCESTORS', default='', cast=Csv())

# ── Redis (cache, sesiones) ───────────────────────────────────────────────────
# En dev sin .env, se conecta a localhost:6379 (Docker Desktop expone el puerto al host).
# En producción, .env siempre define REDIS_URL=redis://redis:6379/0 (nombre del servicio Docker).
REDIS_URL = config('REDIS_URL', default='redis://localhost:6379/0')

if DEBUG and not config('REDIS_URL', default=''):
    # Dev sin Redis: permite 'runserver' sin contenedores activos.
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
else:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            },
        }
    }

# ── Channels (WebSocket / tiempo real) ────────────────────────────────────────
if DEBUG and not config('REDIS_URL', default=''):
    # Dev sin Redis: capa en memoria (un solo proceso, suficiente para `runserver`).
    CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            # socket_timeout holgado: redis-py 8 usa 5 s por defecto, igual al BZPOPMIN bloqueante
            # de channels_redis, y el WebSocket se caía en cada conexión inactiva.
            'CONFIG': {'hosts': [{'address': REDIS_URL, 'socket_timeout': 30}]},
        }
    }

# cached_db: lectura rápida desde Redis y respaldo en DB (un reinicio de Redis no desloguea a nadie).
SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
SESSION_CACHE_ALIAS = 'default'

# ── django-axes (protección brute force) ──────────────────────────────────────
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hora
AXES_LOCKOUT_PARAMETERS = ['ip_address', 'username']
# El User se identifica por email, pero AuthenticationForm sigue enviando el campo como
# 'username'; sin esto axes toma USERNAME_FIELD ('email') y registra el intento sin usuario.
AXES_USERNAME_FORM_FIELD = 'username'
AXES_RESET_ON_SUCCESS = True
# Página amistosa (HTTP 429) con qué hacer cuando alguien queda bloqueado.
AXES_LOCKOUT_TEMPLATE = 'cuentas/bloqueado.html'

# Handler de base de datos en todos los entornos: los intentos fallidos quedan en el admin
# (Axes → Access attempts) y un superusuario desbloquea borrando el registro del bloqueado.
# (El handler de caché no guarda nada en DB, así que no se podría gestionar desde el admin.)
AXES_HANDLER = 'axes.handlers.database.AxesDatabaseHandler'

if not DEBUG:
    # Tras nginx, REMOTE_ADDR es la IP del gateway Docker (igual para todos): sin esto un
    # atacante bloquearía a todos los usuarios. nginx sobrescribe X-Real-IP con la IP real
    # y la app solo es alcanzable a través de nginx (el puerto se publica en 127.0.0.1), así que el header es confiable.
    AXES_IPWARE_META_PRECEDENCE_ORDER = ['HTTP_X_REAL_IP', 'REMOTE_ADDR']

# Registros: imagen estática del widget de mapa (Google Static Maps). Vacío = el widget muestra los puntos pero no
# puede generar la imagen para el informe.
GOOGLE_MAPS_API_KEY = config('GOOGLE_MAPS_API_KEY', default='')

# Django usa 'same-origin' por defecto: sin Referer, OpenStreetMap bloquea las teselas (403 «Access blocked»).
# Con este valor solo se envía el origen (sin ruta ni query) a otros dominios.
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# ── Content Security Policy ───────────────────────────────────────────────────
CONTENT_SECURITY_POLICY = {
    'DIRECTIVES': {
        'default-src': ["'self'"],
        'script-src': ["'self'"],
        'style-src': ["'self'"],
        # Teselas de los mapas Leaflet de Registros (satélite Esri y calles OSM).
        'img-src': ["'self'", 'data:', 'https://server.arcgisonline.com', 'https://*.tile.openstreetmap.org'],
        'font-src': ["'self'"],
        'connect-src': ["'self'"]
        + ([] if not DEBUG else ['ws://localhost:*', 'ws://127.0.0.1:*']),
    },
}

# URL pública del sitio (sin barra final): empresas.tenancy.empresa_url la usa para enlaces en correos.
SITE_URL = config('SITE_URL', default='')

# ── Admins y logging ──────────────────────────────────────────────────────────
ADMIN_EMAIL = config('ADMIN_EMAIL', default='')
ADMINS = [('Admin', ADMIN_EMAIL)] if ADMIN_EMAIL else []
MANAGERS = ADMINS

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'require_debug_false': {'()': 'django.utils.log.RequireDebugFalse'}
    },
    'formatters': {
        'simple': {'format': '{asctime} {levelname} {name} {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler',
        },
    },
    # Errores visibles en 'docker logs'; email a admins solo si hay ADMIN_EMAIL.
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'INFO'},
        'cuentas.impersonacion': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'django.request': {
            'handlers': ['console'] + (['mail_admins'] if ADMINS else []),
            'level': 'ERROR',
            'propagate': False,
        },
    },
}
