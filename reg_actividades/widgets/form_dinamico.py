"""Formulario cuyos campos se definen en la configuración del widget con un mini-lenguaje de una línea por campo:

    nombre | tipo | Etiqueta | placeholder o opciones | * (obligatorio) | ayuda

Los campos se separan con salto de línea o `;`. Tipos: text, textarea, toggle, number, date, time, select (las opciones
van separadas por coma en la 4.ª columna). Las líneas que empiezan con `#` son comentarios."""
import datetime
import re

from . import registrar
from .base import WidgetBase, texto_numero

TIPOS = ('text', 'textarea', 'toggle', 'number', 'date', 'time', 'select')
_NOMBRE = re.compile(r'^[a-z0-9_]+$')


def _lineas(crudo):
    if not crudo:
        return []
    lineas = [l.strip() for l in str(crudo).replace(';', '\n').splitlines()]
    return [l for l in lineas if l and not l.startswith('#')]


def parsear_campos(crudo):
    """Lista de campos válidos; las líneas mal formadas se descartan (para reportarlas: `errores_dsl`)."""
    campos = []
    for linea in _lineas(crudo):
        partes = [p.strip() for p in linea.split('|')]
        nombre = partes[0]
        tipo = (partes[1].lower() if len(partes) > 1 and partes[1] else 'text')
        if not _NOMBRE.match(nombre) or tipo not in TIPOS:
            continue
        extra = partes[3] if len(partes) > 3 else ''
        campos.append({
            'nombre': nombre, 'tipo': tipo,
            'label': partes[2] if len(partes) > 2 and partes[2] else nombre.replace('_', ' ').capitalize(),
            'opciones': [o.strip() for o in extra.split(',') if o.strip()] if tipo == 'select' else [],
            'placeholder': '' if tipo == 'select' else extra,
            'obligatorio': len(partes) > 4 and partes[4] == '*',
            'ayuda': partes[5] if len(partes) > 5 else '',
        })
    return campos


def errores_dsl(crudo):
    errores, vistos = [], set()
    for i, linea in enumerate(_lineas(crudo), start=1):
        partes = [p.strip() for p in linea.split('|')]
        nombre = partes[0]
        if not _NOMBRE.match(nombre):
            errores.append(f"Línea {i}: nombre de campo inválido («{nombre}»). Usa minúsculas, números y guion bajo.")
            continue
        if nombre in vistos:
            errores.append(f"Línea {i}: el campo «{nombre}» está duplicado.")
        vistos.add(nombre)
        tipo = (partes[1].lower() if len(partes) > 1 and partes[1] else 'text')
        if tipo not in TIPOS:
            errores.append(f"Línea {i}: tipo «{tipo}» inválido. Usa: {', '.join(TIPOS)}.")
        elif tipo == 'select' and not [o for o in (partes[3].split(',') if len(partes) > 3 else []) if o.strip()]:
            errores.append(f"Línea {i}: el campo select «{nombre}» necesita opciones separadas por coma.")
    return errores


@registrar
class FormDinamicoWidget(WidgetBase):
    slug = 'form_dinamico_widget'
    nombre = 'Formulario dinámico'
    plantilla = 'reg_actividades/widgets/form_dinamico.html'

    def validar_config(self, config):
        errores = errores_dsl(config.get('campos', ''))
        if 'solo_obligatorios' in config and not isinstance(config['solo_obligatorios'], bool):
            errores.append('solo_obligatorios debe ser verdadero o falso.')
        if not errores and not parsear_campos(config.get('campos', '')):
            errores.append('Define al menos un campo en «campos».')
        return errores

    def leer(self, post, files, config, ctx=None):
        datos, errores = {}, []
        for c in parsear_campos(config.get('campos', '')):
            crudo = post.get(self.nombre_campo(c['nombre']), '')
            if c['tipo'] == 'toggle':
                datos[c['nombre']] = self.nombre_campo(c['nombre']) in post
                continue
            valor = str(crudo).strip()
            if not valor:
                if c['obligatorio']:
                    errores.append(f"{c['label']}: es obligatorio.")
                continue
            if c['tipo'] == 'number':
                try:
                    datos[c['nombre']] = float(valor.replace(',', '.'))
                except ValueError:
                    errores.append(f"{c['label']}: debe ser un número.")
            elif c['tipo'] == 'date':
                try:
                    datos[c['nombre']] = datetime.date.fromisoformat(valor).isoformat()
                except ValueError:
                    errores.append(f"{c['label']}: fecha inválida.")
            elif c['tipo'] == 'time':
                try:
                    datos[c['nombre']] = datetime.time.fromisoformat(valor).strftime('%H:%M')
                except ValueError:
                    errores.append(f"{c['label']}: hora inválida.")
            elif c['tipo'] == 'select':
                if valor in c['opciones']:
                    datos[c['nombre']] = valor
                else:
                    errores.append(f"{c['label']}: opción inválida.")
            else:
                datos[c['nombre']] = valor[:2000]
        return datos, errores

    def nivel(self, datos, config, ctx):
        campos = parsear_campos(config.get('campos', ''))
        if not campos:
            return 0
        datos = datos or {}

        def lleno(c):
            # Un toggle «No» cuenta como respuesta una vez guardado; los demás, si tienen valor.
            return c['nombre'] in datos if c['tipo'] == 'toggle' else datos.get(c['nombre']) not in (None, '')

        llenos = sum(lleno(c) for c in campos)
        # `solo_obligatorios`: está completo con los campos marcados «*» (los demás son opcionales).
        exigidos = [c for c in campos if c['obligatorio']] if config.get('solo_obligatorios') else []
        exigidos = exigidos or campos
        completo = all(lleno(c) for c in exigidos)
        return 1 if llenos == 0 else (3 if completo else 2)

    def contexto(self, datos, config, ctx):
        datos = datos or {}
        campos = []
        for c in parsear_campos(config.get('campos', '')):
            valor = datos.get(c['nombre'])
            if c['tipo'] == 'number':
                valor = texto_numero(valor)
            campos.append({**c, 'campo': self.nombre_campo(c['nombre']),
                           'valor': '' if valor is None else valor, 'marcado': bool(valor)})
        return {'campos': campos, 'etiqueta': config.get('label', self.nombre)}
