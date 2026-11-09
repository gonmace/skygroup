"""Plantilla de pasos ESTÁNDAR de «Supervisión Campo» (`construccion-base`).

Está definida en código y se copia a cada empresa (como pasos y plantilla editables): la empresa puede ajustar su
copia y volver al estándar con `sembrar_estandar(empresa, restaurar=True)`. Los pasos llevan subtítulo y NO se
numeran; los opcionales (instrucciones y libro de obras) vacíos no dejan la visita incompleta.
Cada widget de un paso es un BOTÓN de la línea de tiempo del registro.
"""
from django.db import transaction

CLAVE = 'construccion-base'
NOMBRE_PLANTILLA = 'Supervisión Campo (estándar)'
# (nombre, título, descripción, [(widget_slug, config), …]) en el orden de la plantilla. Cada widget es un BOTÓN del paso.
PASOS = [
    ('cb_datos', 'Datos de la visita', 'Motivo de la visita y ubicación de llegada.', [
        ('form_dinamico_widget', {'label': 'Motivo de la visita', 'solo_obligatorios': True, 'campos': (
            'motivo | select | Motivo de la visita | Rutinaria,Inspección de actividad,Recepción,'
            'Prueba o ensayo,Verificación de observaciones,Otro | *\n'
            'comentario | textarea | Comentario')}),
        ('ubicacion_widget', {'label': 'Ubicación GPS de llegada', 'opcional': True}),
    ]),
    ('cb_actividades', 'Actividades', 'Lo que se está ejecutando en el frente, con sus imágenes.', [
        ('lista_widget', {'label': 'Actividades en ejecución', 'numerada': False, 'max_items': 50,
                          'placeholder': 'Una actividad por línea'}),
        # Mínimo 4 imágenes y cada una con fecha y ubicación (EXIF): así se descartan las reenviadas por WhatsApp.
        ('camera_widget', {'label': 'Imágenes de las actividades', 'foto_min': 4, 'exigir_metadatos': True}),
    ]),
    ('cb_recursos', 'Recursos presentes', 'Personal y equipo pesado que se vio en el frente.', [
        ('form_dinamico_widget', {'label': 'Recursos', 'solo_obligatorios': True, 'campos': (
            'trabajadores | number | Número de trabajadores (aprox.) | | *\n'
            'equipo_pesado | text | Equipo pesado | Ej.: 1 retroexcavadora, 1 grúa')}),
    ]),
    ('cb_hallazgos', 'Hallazgos y observaciones',
     'Lo encontrado en esta visita: código, descripción, tipo, severidad, responsable y plazo.', [
        ('hallazgos_widget', {'label': 'Hallazgos de esta visita'}),
        ('camera_widget', {'label': 'Imágenes', 'foto_min': 0, 'opcional': True}),
    ]),
    ('cb_seguimiento', 'Verificación de observaciones previas',
     'Estado de las observaciones abiertas en visitas anteriores.', [
        ('seguimiento_widget', {'label': 'Observaciones de visitas anteriores'}),
        ('camera_widget', {'label': 'Imágenes de respaldo', 'foto_min': 0, 'opcional': True}),
    ]),
    ('cb_instrucciones', 'Instrucciones y acuerdos en sitio', 'Opcional: lo que se indicó y se acordó, y el libro de obras.', [
        ('lista_widget', {'label': 'Instrucciones y acuerdos', 'numerada': True, 'max_items': 50, 'opcional': True,
                          'placeholder': 'Una instrucción o acuerdo por línea'}),
        ('camera_libro_widget', {'label': 'Imágenes del libro de obras', 'foto_min': 0, 'etapa': 'cb_libro',
                                 'opcional': True}),
    ]),
]


def _modelos(modelos):
    if modelos:
        return modelos['Paso'], modelos['PasoWidget'], modelos['Plantilla'], modelos['PasoAsignado']
    from reg_actividades.models import Paso, PasoAsignado, PasoWidget, Plantilla
    return Paso, PasoWidget, Plantilla, PasoAsignado


@transaction.atomic
def sembrar_estandar(empresa, restaurar=False, modelos=None):
    """Crea (idempotente) los pasos `cb_*` y la plantilla «Supervisión Campo (estándar)» de la empresa.

    - Un paso que ya existe NO se toca, salvo con `restaurar=True`: entonces se reescriben su título, descripción y
      componentes con los del estándar, se vuelven a asignar a la plantilla los pasos que le falten, se QUITAN de la
      plantilla los pasos `cb_*` que ya no son del estándar (el paso y sus datos no se borran) y se deja el orden
      estándar. Los pasos propios de la empresa (otro prefijo) se conservan.
    - Si la empresa ya tiene una plantilla general ACTIVA de este tipo no se crea otra (se completa esa).
    - `modelos`: diccionario con los modelos históricos (para usarla desde una migración de datos).

    Devuelve `(pasos_nuevos, plantilla_creada)`."""
    Paso, PasoWidget, Plantilla, PasoAsignado = _modelos(modelos)
    pasos, nuevos = {}, 0
    for nombre, titulo, descripcion, widgets in PASOS:
        paso, creado = Paso.objects.get_or_create(empresa=empresa, nombre=nombre,
                                                  defaults={'titulo': titulo, 'descripcion': descripcion})
        nuevos += creado
        pasos[nombre] = paso
        if creado or restaurar:
            if not creado:
                paso.titulo, paso.descripcion = titulo, descripcion
                paso.save()
                paso.widgets.all().delete()
            for orden, (slug, config) in enumerate(widgets, start=1):
                PasoWidget.objects.create(paso=paso, widget_slug=slug, orden=orden, config=config)

    plantilla = Plantilla.objects.filter(empresa=empresa, tipo_registro=CLAVE, tipo_proyecto__isnull=True,
                                         activa=True).first()
    creada = plantilla is None
    if creada:
        plantilla = Plantilla.objects.create(
            empresa=empresa, nombre=NOMBRE_PLANTILLA, tipo_registro=CLAVE,
            descripcion='Reporte de visita de supervisión de obra. Plantilla estándar: ajústala a tu empresa.')
    if creada or restaurar:
        if restaurar:
            PasoAsignado.objects.filter(plantilla=plantilla, paso__nombre__startswith='cb_').exclude(
                paso__nombre__in=[n for n, *_ in PASOS]).delete()
        asignados = set(PasoAsignado.objects.filter(plantilla=plantilla).values_list('paso_id', flat=True))
        siguiente = (PasoAsignado.objects.filter(plantilla=plantilla).order_by('-orden').values_list('orden', flat=True)
                     .first() or 0)
        for nombre, *_ in PASOS:
            if pasos[nombre].pk not in asignados:
                siguiente += 1
                PasoAsignado.objects.create(plantilla=plantilla, paso=pasos[nombre], orden=siguiente)
        if restaurar:   # orden del estándar para sus pasos
            for orden, (nombre, *_) in enumerate(PASOS, start=1):
                PasoAsignado.objects.filter(plantilla=plantilla, paso=pasos[nombre]).update(orden=orden)
    return nuevos, creada
