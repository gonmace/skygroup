"""Clasificador por palabras clave: divide el texto libre de un reporte en actividades y asigna a cada una
una categoría (primera coincidencia, en orden de prioridad). Sobre texto normalizado (sin acentos, con typos
frecuentes). Las categorías creadas por la empresa no tienen palabras: solo se asignan a mano o con el LLM."""
import re

from .models import OTROS
from .texto import normalizar

_SEPARADOR = re.compile(r'[|;*•·]+')
_ENUMERACION = re.compile(r'^\s*(?:\d{1,2}\s*[.\-)]+|[-–—•·])\s*')
LARGO_MINIMO = 4

# (código, etiqueta, color, [patrones]) — el orden es la prioridad.
BASE = [
    ('riesgos', 'Análisis de riesgos', '#ef4444', [r'riesg', r'\briegos\b', r'riezg', r'reisg']),
    ('reuniones', 'Reuniones y coordinación', '#38bdf8', [
        r'reuni', r'c?oordin', r'cordin', r'\bjunta', r'comite', r'\bllamada', r'videollamada', r'capacitacion']),
    ('cronogramas', 'Cronogramas y planificación', '#f59e0b', [
        r'cronogram', r'planificacion', r'programacion', r'\bgantt', r'\bhito', r'plan de trabajo', r'plan maestro',
        r'planes de trabajo']),
    ('actas', 'Actas y documentos de proyecto', '#2dd4bf', [
        r'\bactas?\b', r'constitucion', r'kick\s*off', r'recepcion definitiva', r'acta de entrega', r'acta de recepcion']),
    ('pliegos', 'Pliegos y especificaciones técnicas', '#a78bfa', [
        r'pliego', r'especificacion tecnic', r'especificaciones tecnic', r'\betp\b', r'memoria tecnica']),
    ('diseno', 'Diseño e ingeniería', '#6366f1', [
        r'plano', r'disen', r'diesn', r'ingenier', r'ingener', r'calculo', r'piping', r'isometric', r'autocad',
        r'\brevit', r'\bcad\b', r'memoria de calculo', r'diagrama', r'tablero', r'\bbim\b', r'\bp&id\b', r'\b3d\b',
        r'\brs-?\d', r'isometr', r'cuadro de computo']),
    ('supervision', 'Supervisión de obra y campo', '#34d399', [
        r'superv', r'\bobra\b', r'\bcampo\b', r'visita', r'relevamiento', r'inspeccion', r'fiscaliz', r'\btaller',
        r'\bconst\b', r'construccion', r'replanteo', r'montaje', r'instalacion', r'recorrido', r'\bplanta\b']),
    ('informes', 'Informes y reportes', '#fb7185', [
        r'\binforme', r'report', r'presentacion', r'estados? de situacion', r'\bres\b']),
    ('adquisiciones', 'Adquisiciones y contratos', '#f97316', [
        r'adquisicion', r'requerimiento de servicio', r'requerimiento', r'requisicion', r'\bpr\b', r'\bprs\b', r'\bpr\d',
        r'orden de compra', r'\boc\b', r'\bcompra', r'cotizacion', r'proveedor', r'licitacion', r'abastecimiento',
        r'contrat', r'precio unitario', r'\bpu\b', r'validacion tecnic', r'boletas? de garantia', r'\brs\b',
        r'listado de material', r'solicitud de loto']),
    ('seguimiento', 'Seguimiento y control', '#94a3b8', [r'seguim', r'\bcontrol', r'plan de accion', r'action log', r'monitoreo']),
    ('gestion_doc', 'Gestión documental y administrativa', '#c084fc', [
        r'document', r'ducument', r'documenacion', r'carpeta', r'sharepoint', r'archivo', r'expediente', r'administrativ',
        r'correo', r'\bmail\b', r'respaldo', r'backup', r'bandeja de entrada', r'planilla']),
    ('revision_tecnica', 'Revisión técnica de proyectos', '#d946ef', [
        r'informacion tecnica', r'revision de proyecto', r'revision proyecto', r'revision tecnica',
        r'revision de la informacion']),
]
CATEGORIA_OTROS = (OTROS, 'Otros', '#64748b')
_PATRONES = [(codigo, [re.compile(p) for p in patrones]) for codigo, _, _, patrones in BASE]


def dividir(texto):
    """Lista de actividades limpias a partir de texto libre (líneas, viñetas, «;», «|», numeración)."""
    items = []
    for linea in (texto or '').splitlines():
        for fragmento in _SEPARADOR.split(linea):
            fragmento = _ENUMERACION.sub('', fragmento).strip()
            fragmento = _ENUMERACION.sub('', fragmento).strip()      # «1.- 2.-» pegado
            if len(fragmento) >= LARGO_MINIMO:
                items.append(fragmento)
    return items


def clasificar(texto):
    """(código, patrón que coincidió). Sin coincidencia: («otros», '')."""
    norm = normalizar(texto)
    for codigo, patrones in _PATRONES:
        for p in patrones:
            if p.search(norm):
                return codigo, p.pattern
    return OTROS, ''
