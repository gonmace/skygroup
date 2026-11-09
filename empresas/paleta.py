"""Paleta de marca derivada de uno o dos colores (primario / acento) por tema.

Objetivo: que cualquier color que elija una empresa produzca una interfaz legible. El color de
marca se respeta tal cual para rellenos (botones, chips); solo se ajusta cuando hace falta:

* `--p-text` / `--a-text`: variante del primario / acento apta para TEXTO y anillo de foco
  (≥ 4.5:1 sobre las superficies del tema y sobre su propio tinte del 10 %). Mismo matiz y
  croma, solo cambia la luminosidad (OKLCH).
* Tema oscuro sin color propio: se parte del primario claro y se sube su luminosidad solo si
  no llega a 3:1 sobre la tarjeta oscura.
* Acento vacío: se deriva girando el matiz del primario 150°.
* Colores semánticos (error / aviso / éxito): conservan su matiz salvo que caigan a menos de
  25° del primario, en cuyo caso se apartan para no confundirse con la marca.

Sin dependencias: solo `math`. Las superficies son las de `theme/static_src/src/styles.css`.
"""
import math

# Superficies de los temas (base-100 / base-200) — mantener sincronizado con styles.css
SUPERFICIES = {
    'light': ('#ffffff', '#f2f2f7'),
    'dark': ('#1c1c1e', '#000000'),
}
MIN_TEXTO = 4.6      # AA con margen (4.5)
MIN_RELLENO = 3.0    # componentes gráficos (WCAG 1.4.11)
DISTANCIA_SEMANTICA = 25
ROTACION_ACENTO = 150
CROMA_MINIMO_MARCA = 0.04   # por debajo es un gris: no tiene matiz que evitar

# Semánticos por defecto (los de styles.css): nombre → (claro, oscuro)
SEMANTICOS = {
    'error': ('#D70015', '#FF453A'),
    'warning': ('#FF9500', '#FF9F0A'),
    'success': ('#248A3D', '#30D158'),
}


# ── conversión de color ──────────────────────────────────────────────────────────
def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _hex(r, g, b):
    return '#' + ''.join(f'{round(min(1, max(0, c)) * 255):02x}' for c in (r, g, b))


def a_oklch(hex_color):
    r, g, b = (_lin(c) for c in _rgb(hex_color))
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b2 = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, math.hypot(a, b2), math.degrees(math.atan2(b2, a)) % 360


def _oklch_lineal(L, C, h):
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
            -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
            -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)


def de_oklch(L, C, h):
    """OKLCH → hex. Si el color cae fuera de sRGB se reduce el croma (mantiene L y h)."""
    L = min(1.0, max(0.0, L))
    en_gamut = lambda c: all(-1e-4 <= x <= 1 + 1e-4 for x in _oklch_lineal(L, c, h))
    if not en_gamut(C):
        lo, hi = 0.0, C
        for _ in range(24):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if en_gamut(mid) else (lo, mid)
        C = lo
    return _hex(*(_gam(max(0.0, min(1.0, x))) for x in _oklch_lineal(L, C, h)))


# ── contraste ────────────────────────────────────────────────────────────────────
def luminancia(hex_color):
    r, g, b = (_lin(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


MIN_BLANCO = 4.0   # el texto de un botón es corto y semibold: se prefiere blanco si llega a ~AA (rojos, verdes)


def texto_contraste(hex_color):
    """Texto (blanco/negro) legible sobre `hex_color`. Blanco si contrasta al menos `MIN_BLANCO` (así un rojo de
    marca como #F40009 lleva texto blanco, no negro); si no, negro."""
    return '#ffffff' if contraste(hex_color, '#ffffff') >= MIN_BLANCO else '#000000'


def _mezcla(color, base, peso=0.10):
    c, b = _rgb(color), _rgb(base)
    return _hex(*(x * peso + y * (1 - peso) for x, y in zip(c, b)))


def _fondos(color, tema):
    """Superficies sobre las que irá el texto de `color`: planas y con su tinte del 10 %."""
    planas = SUPERFICIES[tema]
    return [*planas, *(_mezcla(color, s) for s in planas)]


def ajustar(hex_color, tema, minimo=MIN_TEXTO, fondos=None):
    """Devuelve `hex_color` si ya cumple `minimo`; si no, el color de menor cambio de
    luminosidad (mismo matiz y croma) que lo cumple: más oscuro en claro, más claro en oscuro."""
    fondos = fondos or (lambda c: _fondos(c, tema))
    L, C, h = a_oklch(hex_color)
    cumple = lambda c: min(contraste(c, f) for f in fondos(c)) >= minimo
    if cumple(hex_color):
        return hex_color.lower()
    claro = tema == 'dark'
    lo, hi = (L, 1.0) if claro else (0.0, L)
    for _ in range(24):
        mid = (lo + hi) / 2
        ok = cumple(de_oklch(mid, C, h))
        if claro:
            lo, hi = (lo, mid) if ok else (mid, hi)
        else:
            lo, hi = (mid, hi) if ok else (lo, mid)
    return de_oklch(hi if claro else lo, C, h)


# ── paleta ───────────────────────────────────────────────────────────────────────
def derivar_acento(primario, tema):
    """Acento por defecto: matiz del primario girado 150°, croma moderado."""
    _, C, h = a_oklch(primario)
    return de_oklch(0.74 if tema == 'light' else 0.80, min(0.15, max(0.07, C * 0.9)), (h + ROTACION_ACENTO) % 360)


def _separar_semantico(hex_color, matiz_marca):
    """Aparta el matiz de un color semántico si cae a < 25° de la marca."""
    L, C, h = a_oklch(hex_color)
    d = (h - matiz_marca + 180) % 360 - 180
    if abs(d) >= DISTANCIA_SEMANTICA:
        return None
    return de_oklch(L, C, (matiz_marca + math.copysign(DISTANCIA_SEMANTICA, d or 1)) % 360)


def _vars_tema(tema, primario, acento):
    v = {}
    if primario:
        v['--color-primary'] = primario
        v['--color-primary-content'] = texto_contraste(primario)
        v['--p-text'] = ajustar(primario, tema)
        # Semánticos que chocarían con la marca (solo se emiten los que cambian)
        _, croma, matiz = a_oklch(primario)
        for nombre, pares in (SEMANTICOS.items() if croma > CROMA_MINIMO_MARCA else ()):
            nuevo = _separar_semantico(pares[tema == 'dark'], matiz)
            if nuevo:
                v[f'--color-{nombre}'] = nuevo
                v[f'--color-{nombre}-content'] = texto_contraste(nuevo)
                if nombre == 'error':   # «eliminar» es un error más oscuro (más claro en tema oscuro)
                    L, C, h = a_oklch(nuevo)
                    delete = de_oklch(L + (0.06 if tema == 'dark' else -0.12), C, h)
                    v['--color-delete'] = delete
                    v['--color-delete-content'] = texto_contraste(delete)
    if acento:
        v['--color-accent'] = acento
        v['--color-accent-content'] = texto_contraste(acento)
        v['--a-text'] = ajustar(acento, tema)
    return v


def generar_tema(primario='', primario_oscuro='', acento='', acento_oscuro=''):
    """Variables CSS por tema a partir de los colores de la empresa (hex `#rrggbb` o vacío).

    Devuelve `{'light': {...}, 'dark': {...}}`; vacío si la empresa no definió ningún color
    (se conserva el tema por defecto)."""
    primario, primario_oscuro = primario.lower(), primario_oscuro.lower()
    acento, acento_oscuro = acento.lower(), acento_oscuro.lower()
    if not (primario or primario_oscuro or acento or acento_oscuro):
        return {'light': {}, 'dark': {}}

    p_claro = primario
    # Tema oscuro sin primario propio: el claro, subido de luminosidad solo si hace falta.
    p_oscuro = primario_oscuro or (ajustar(primario, 'dark', MIN_RELLENO, lambda c: SUPERFICIES['dark']) if primario else '')

    a_claro = acento or (derivar_acento(p_claro, 'light') if p_claro else '')
    a_oscuro = acento_oscuro or (
        ajustar(acento, 'dark', MIN_RELLENO, lambda c: SUPERFICIES['dark']) if acento
        else derivar_acento(p_oscuro, 'dark') if p_oscuro else '')

    return {'light': _vars_tema('light', p_claro, a_claro), 'dark': _vars_tema('dark', p_oscuro, a_oscuro)}


def a_css(tema):
    """`generar_tema(...)` → texto CSS (un bloque por tema con variables)."""
    bloques = []
    for nombre, selector in (('light', 'html[data-theme="light"]'), ('dark', 'html[data-theme="dark"]')):
        reglas = ''.join(f'{k}:{val};' for k, val in tema[nombre].items())
        if reglas:
            bloques.append(f'{selector}{{{reglas}}}')
    return '\n'.join(bloques)
