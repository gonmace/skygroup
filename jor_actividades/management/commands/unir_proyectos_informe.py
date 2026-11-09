"""Une las etiquetas de proyecto de Jornadas con los proyectos del informe de supervisión y crea los `Proyecto`.

    python manage.py unir_proyectos_informe emb             # solo muestra qué haría
    python manage.py unir_proyectos_informe emb --aplicar   # guarda

Fuente: informe RL-EMB-SUPPROY-07 (Certificado 7, 21/09–20/10/2026). Por cada proyecto del informe:
  · `principal`: la etiqueta de proyecto (raíz) que lo representa; si es una raíz sin proyecto, se vincula.
  · `variantes`: otras etiquetas raíz cuyo nombre (normalizado) coincide con alguna expresión de `claves` y con
    ninguna de `excluir`; se fusionan bajo la principal (fusión no destructiva: `Etiqueta.canonica`).
  · El `Proyecto` se crea con el nombre del informe y el código de la principal (si está libre) o se reutiliza si
    ya existe uno activo con ese nombre. Idempotente: lo ya fusionado/vinculado no se vuelve a tocar.
Una etiqueta que encaja en dos proyectos se deja sin fusionar y se avisa. Los proyectos dudosos del informe
(compresores, K140, portones, K-108, SIDEL…) no están aquí a propósito: se resuelven a mano.
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from empresas.models import Empresa
from jor_actividades.models import Etiqueta
from jor_actividades.servicios import fusionar
from jor_actividades.texto import normalizar

# (nombre del informe, nombre de la etiqueta principal, expresiones de variantes, expresiones a excluir)
PROYECTOS = [
    ('Pozo Profundo PPA09', 'Pozo profundo de agua "PPA-09"', [r'ppa[- ]?0?9\b'], []),
    ('Taller Electromecánico', 'Taller Central Electromecanico', [r'taller electromecanico'], []),
    ('Montaje de Tanques de Jarabe Simple – Fase 2', 'Montaje de tanque de jarabe simple y disolutor Fase 2',
     [r'jarabe simple'], [r'sala de jarabe', r'encalado', r'enfriamiento']),
    ('Obras Playa Este Piñami 2', 'Construcción Nave Gemela Piñami 2', [r'playa este', r'nave gemela'], []),
    ('Pavimento Rígido Av. Elías Meneses', 'PAVIMENTO ELIAS MENESES', [r'mene[sczn]es', r'elias men'], []),
    ('Cerramiento del Predio El Paso y Sede del Complejo Deportivo', 'cerramiento el paso', [r'cerramiento'], []),
    ('Módulo de Servicios (Piñami 1)', 'Módulo de Servicios', [r'modulo de servicios'], [r'tesoreria', r'liquidacion']),
    ('Bodegas de Sacaba y KM 10', 'CD Sacaba', [r'sacaba'], []),
    ('Adecuación de Tanque Enchaquetado', 'Adecuacion de tanque enchaquetado', [r'enchaquetado'], []),
    ('Sistema de Tratamiento de Efluentes PTAR MBR', 'Tratamiento Efluentes+Montaje',
     [r'tratamiento efluentes', r'planta efluentes'], []),
    ('Perforación de Pozo Profundo PPA-08', 'PPA8', [r'ppa[- ]?0?8\b', r'incremento agua cruda'], []),
    ('Subestación Eléctrica 5.5 MVA (Fases I y II)', 'Subestacion EE LPZ FASE 1', [r'subestacion ee lpz'], []),
    ('CD El Alto', 'CD el Alto', [r'cd el alto'], [r'aduccion']),
    ('Módulo de Tesorería / Liquidación Praxair', 'Módulo liquidación tesorería',
     [r'praxair', r'liquidacion', r'modulo de tesoreria', r'tesoreria'], []),
    ('Centro de Distribución Sur', 'CD SUR', [r'cd sur', r'centro de distribucion sur'], []),
    ('Rehabilitación de Pisos en Picking (PI06)', 'Rehabilitación de pisos en Picking predio PI06',
     [r'picking'], [r'automatizacion', r'porton']),
    ('Línea de Soplado PI-51 – Sopladora REF-PET', 'Sopladora REF PET', [r'ref[- ]?pet'], [r'restauracion', r'compresor', r'torre']),
    ('Sistema de pre-encalado de la planta de agua (Fase 1)', 'Sistema de pre encalado para la planta de agua F1',
     [r'encalado'], []),
    ('Nueva Línea K-168', 'nueva linea K168', [r'k[- ]?168'], []),
    ('Sistema CIP – Fase 3', 'Aux. Montaje de Sistema CIP Fase 3', [r'\bcip\b'], [r'fase 2', r'\bcbb\b', r'central']),
    # Segunda tanda (cruce con las órdenes de compra de EMBOL y los informes de abril a octubre de 2026):
    ('Tratamiento de Efluentes + PEM', 'Efluentes +PEM', [r'\bpem\b'], []),                              # OC 4928, CMT.LPZ.MQ.2754
    ('Checkmat Fase 2 – Unidad de Inspección de Botellas (K-108)', 'Montaje de Checkmat K-108 Fase 2',
     [r'checkmat'], []),                                                                                # OC 4720, CMT.CBB.MQ.2732
    ('Incremento de Capacidad OW – Líneas K140 y C380', 'incremento de capacidad K140', [r'k[- ]?140', r'c380'],
     [r'restauracion', r'compresor']),                                                                  # OC 4719
    ('Aducción de Agua – Pozo #6 (ex Hilandería)', 'aduccion pozo ex hilanderia a planta el alto', [r'hilanderia'], [r'150 ?kva', r'transformador']),   # OC 4981
    ('Reposición de Pisos Piñami 3', 'Reposicion Pisos Piñami 3', [r'pinami 3'], [r'cubierta', r'nave', r'porton']),
    ('Túnel Subterráneo de Pallets (TSPP) y Ampliación de Pisos Piñami 1', 'TSPP', [r'tspp', r'tunel', r'ampp'], []),
    ('Montaje de Compresor de Aire 7 Bar', 'Montaje de compresor 7 bar', [r'7 bar'], []),
    ('Remodelación de Oficinas OFCOM y Oficina Central', 'Remodelación de oficinas OFCOM', [r'ofcom'], []),
]

# Estado según el último informe consolidado (RL-EMB-SUPPROY-07, 21/09–20/10/2026) y los informes individuales.
# Sin entrada = sin dato (Pre-encalado: «sin actividad reportada»; OFCOM: sin estado en los informes).
E = 'CONSTRUCCION'
ESTADOS = {
    'Pozo Profundo PPA09': E, 'Taller Electromecánico': 'CONCLUIDO', 'Montaje de Tanques de Jarabe Simple – Fase 2': E,
    'Obras Playa Este Piñami 2': 'INGENIERIA', 'Pavimento Rígido Av. Elías Meneses': E,
    'Cerramiento del Predio El Paso y Sede del Complejo Deportivo': 'INGENIERIA', 'Módulo de Servicios (Piñami 1)': 'INGENIERIA',
    'Bodegas de Sacaba y KM 10': 'INGENIERIA', 'Adecuación de Tanque Enchaquetado': 'CONCLUIDO',
    'Sistema de Tratamiento de Efluentes PTAR MBR': 'PARALIZADO', 'Perforación de Pozo Profundo PPA-08': E,
    'Subestación Eléctrica 5.5 MVA (Fases I y II)': E, 'CD El Alto': E, 'Módulo de Tesorería / Liquidación Praxair': 'INGENIERIA',
    'Centro de Distribución Sur': 'CONCLUIDO', 'Rehabilitación de Pisos en Picking (PI06)': 'CONCLUIDO',
    'Línea de Soplado PI-51 – Sopladora REF-PET': E, 'Nueva Línea K-168': 'INGENIERIA', 'Sistema CIP – Fase 3': E,
    'Tratamiento de Efluentes + PEM': 'PARALIZADO', 'Checkmat Fase 2 – Unidad de Inspección de Botellas (K-108)': 'CONCLUIDO',
    'Incremento de Capacidad OW – Líneas K140 y C380': 'INGENIERIA', 'Aducción de Agua – Pozo #6 (ex Hilandería)': 'INGENIERIA',
    'Reposición de Pisos Piñami 3': 'CONCLUIDO', 'Túnel Subterráneo de Pallets (TSPP) y Ampliación de Pisos Piñami 1': 'INGENIERIA',
    'Montaje de Compresor de Aire 7 Bar': 'CONCLUIDO',
}


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('slug')
        parser.add_argument('--estados', action='store_true',
                            help='también fija el estado de los proyectos YA existentes (por defecto solo al crear)')
        parser.add_argument('--aplicar', action='store_true', help='guarda los cambios (sin esto solo se muestran)')

    def handle(self, *args, slug, aplicar, estados=False, **opts):
        try:
            empresa = Empresa.objects.get(slug=slug)
        except Empresa.DoesNotExist:
            raise CommandError(f'No existe la empresa «{slug}».')
        try:
            with transaction.atomic():
                self.ejecutar(empresa, estados)
                if not aplicar:
                    raise _Deshacer
        except _Deshacer:
            self.stdout.write(self.style.WARNING('\nSimulación: no se guardó nada. Usa --aplicar para guardar.'))

    def ejecutar(self, empresa, actualizar_estados=False):
        from proyectos.models import Proyecto
        raices = list(Etiqueta.objects.filter(empresa=empresa, tipo=Etiqueta.Tipo.PROYECTO, canonica__isnull=True,
                                              ignorada=False))
        por_nombre = {}
        for e in raices:
            por_nombre.setdefault(normalizar(e.nombre), e)
        principales = {normalizar(p): por_nombre.get(normalizar(p)) for _, p, _, _ in PROYECTOS}
        ids_principales = {e.pk for e in principales.values() if e}

        # Qué proyectos reclama cada etiqueta (para no fusionar una que encaja en dos).
        reclamos = {}
        for nombre, principal, claves, excluir in PROYECTOS:
            for e in raices:
                n = normalizar(e.nombre)
                if e.pk in ids_principales or not any(re.search(c, n) for c in claves) or any(re.search(x, n) for x in excluir):
                    continue
                reclamos.setdefault(e.pk, []).append(nombre)

        activos = {normalizar(p.nombre): p for p in Proyecto.objects.de_empresa(empresa).activos()}
        codigos = {c.lower() for c in Proyecto.objects.de_empresa(empresa).activos().exclude(codigo='').values_list('codigo', flat=True)}
        creados = fusionadas = 0
        for nombre, principal, claves, excluir in PROYECTOS:
            e = principales[normalizar(principal)]
            if e is None:
                self.stdout.write(self.style.ERROR(f'\n✗ {nombre}: no hay etiqueta principal «{principal}» (¿ya fusionada?)'))
                continue
            proyecto = e.proyecto or activos.get(normalizar(nombre))
            accion = 'ya vinculado'
            if proyecto is None:
                codigo = e.codigo if e.codigo and e.codigo.lower() not in codigos else ''
                proyecto = Proyecto.objects.create(empresa=empresa, nombre=nombre[:160], codigo=codigo[:40])
                activos[normalizar(nombre)] = proyecto
                if codigo:
                    codigos.add(codigo.lower())
                creados += 1
                accion = f'proyecto NUEVO{f" [{codigo}]" if codigo else " (sin código)"}'
            elif e.proyecto_id is None:
                accion = 'se vincula a un proyecto existente'
            if e.proyecto_id != proyecto.pk:
                e.proyecto = proyecto
                e.save(update_fields=['proyecto'])
            estado = ESTADOS.get(nombre)
            if estado and proyecto.estado != estado and (accion.startswith('proyecto NUEVO') or actualizar_estados):
                proyecto.estado = estado
                proyecto.save(update_fields=['estado'])
                accion += f'; estado {estado}'
            self.stdout.write(f'\n✓ {nombre}  ←  «{e.nombre}»  ({accion})')
            for v in raices:
                if v.pk in ids_principales or v.pk not in reclamos or nombre not in reclamos[v.pk]:
                    continue
                if len(reclamos[v.pk]) > 1:
                    self.stdout.write(self.style.WARNING(f'    ? «{v.nombre}» encaja en {len(reclamos[v.pk])} proyectos: se deja sin fusionar'))
                    continue
                if v.proyecto_id and v.proyecto_id != proyecto.pk:
                    self.stdout.write(self.style.WARNING(f'    ? «{v.nombre}» ya está vinculada a otro proyecto: se deja'))
                    continue
                fusionar(v, e)
                fusionadas += 1
                self.stdout.write(f'    + fusiona «{v.nombre}»')
                if not proyecto.codigo and v.codigo and v.codigo.lower() not in codigos:
                    proyecto.codigo = v.codigo[:40]
                    proyecto.save(update_fields=['codigo'])
                    codigos.add(v.codigo.lower())
                    self.stdout.write(f'      (el proyecto hereda el código {v.codigo})')
        self.stdout.write(f'\nResumen: {creados} proyectos nuevos, {fusionadas} etiquetas fusionadas.')


class _Deshacer(Exception):
    pass
