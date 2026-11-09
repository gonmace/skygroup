import re
import unicodedata


def normalizar(texto):
    """Minúsculas, sin acentos y con espacios colapsados: «Cordinación» → «cordinacion»."""
    texto = unicodedata.normalize('NFKD', texto or '')
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto.lower()).strip()
