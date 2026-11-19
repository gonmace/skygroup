"""Carga inicial de las plantillas de APU y sus prompts. Parte de los prompts que antes vivían en los workflows de n8n
(`semilla/prompts_base.json`, exportados tal cual) y los reparte en casillas: rol, criterios del tipo de trabajo y reglas
de respuesta. Cada plantilla cambia el dominio del rol y trae sus propios criterios de materiales, mano de obra y equipos.
Es idempotente: solo crea lo que falta, así que nunca pisa lo que el superusuario ya editó en la web."""
import json
import re
from pathlib import Path

BASE = Path(__file__).parent / 'semilla' / 'prompts_base.json'
ACTUALES = Path(__file__).parent / 'semilla' / 'plantillas_actuales.json'

# Modelo y razonamiento con que arranca cada paso (los que ya usaban los workflows).
MODELOS = {
    'coherencia': ('gpt-5.1', 'medium'), 'clasificacion': ('gpt-5.1', 'low'),
    'materiales': ('gpt-5.1', 'low'), 'mano_obra': ('gpt-5-mini', 'low'), 'equipos': ('gpt-5-mini', 'low'),
    'verificar': ('gpt-4.1-mini', ''), 'modificar': ('gpt-5.1', 'low'), 'verificar_titulo': ('gpt-5-mini', ''),
    'precios': ('gpt-5.1', 'low'),
}

PATRON_DOMINIO = re.compile(r'obras de construcción e industriales(?: \([^)]*\))?')
MARCA_REGLAS = 'REGLAS GENERALES'
MARCA_DATOS = 'Datos mínimos según la actividad'

PLANTILLAS = [
    {
        'nombre': 'Obras civiles', 'orden': 1,
        'descripcion': 'Edificación y obra civil: movimiento de tierras, hormigón, mampostería, acabados, instalaciones, vías y obras hidráulicas.',
        'unidades': 'm³, m², ml, pza, kg, ha',
        'dominio': 'obras civiles y de edificación (movimiento de tierras, hormigón, mampostería, acabados, instalaciones, vías y obras hidráulicas)',
        'datos': None,   # se usan los de la regla 8 original
    },
    {
        'nombre': 'Montaje mecánico y tuberías', 'orden': 2,
        'descripcion': 'Montaje industrial: estructuras metálicas, tuberías, equipos estáticos y rotativos, soldadura y calderería.',
        'unidades': 'kg, t, pulg-diám, ml, equipo',
        'dominio': 'montaje mecánico industrial (estructuras metálicas, tuberías, equipos estáticos y rotativos, soldadura, calderería)',
        'alternativa': 'tubería o estructura ya fabricada frente a fabricada en obra',
        'ej_unidad': 'una tubería medida en m²',
        'ej': {'a': 'Montaje de tubería de 6" sch 40', 'b': 'Montaje de tubería de 8" sch 80', 'instr': 'usa tubería de 8" sch 80',
               'c': 'Montaje de estructura metálica'},
        'clasificacion': '''Eres un especialista en montaje mecánico industrial. Clasifica técnicamente la actividad indicada en cinco campos breves:
- sistema_constructivo: p. ej. «Tubería de acero al carbono», «Estructura metálica», «Equipo rotativo».
- tipo_elemento: p. ej. «Línea de proceso», «Soporte», «Bomba», «Tanque».
- material_principal: el material que define la actividad.
- proceso_principal: el proceso de ejecución, p. ej. «Soldadura», «Izaje y montaje», «Prueba hidrostática».
- categoria: una de «Tuberías», «Estructuras metálicas», «Equipos», «Soldadura y calderería», «Pruebas», «Otros».
Usa términos técnicos habituales en obra. Responde SOLO con el JSON pedido.''',
        'datos': ('Montaje mecánico (estructuras, tuberías, equipos): especificación del material o equipo, perfiles, diámetros y espesores, '
                  'longitud o peso, tipo de unión (soldada, atornillada, bridada), protección (pintura, galvanizado, aislamiento), '
                  'altura o ubicación del trabajo, y si se incluye el suministro o solo el montaje.'),
        'criterios': {
            'materiales': """- NIVEL DE DESGLOSE: un material va al nivel en que se compra o se controla: tubería, accesorios, bridas, válvulas, perfiles y planchas llegan ya fabricados y certificados. NO los desgloses en materia prima salvo que la actividad sea de fabricación.
- Consumibles de soldadura y corte: electrodos o alambre, gas de protección, discos de corte y desbaste, gases de oxicorte. Exprésalos por unidad de la actividad (p. ej. kg de electrodo por pulgada-diámetro o por kg de acero montado) y escribe la base en «justificacion».
- Pernería, empaquetaduras, juntas, sellantes y lubricantes de montaje cuando la unión es bridada o atornillada.
- Protección y acabados cuando la especificación los pide: limpieza superficial, imprimante, pintura, galvanizado en campo, aislamiento térmico o acústico y su revestimiento.
- Pruebas: fluido de prueba, líquidos penetrantes y similares solo si se pagan con la actividad y no aparte.
- Suministro y montaje: si la actividad es solo montaje, el material principal (tubo, perfil, equipo) no se incluye. Si no consta, pregúntalo con una consulta «opciones».
- Desperdicio: recortes de perfiles, planchas y tubos según las longitudes comerciales (desperdicio_pct).
- No incluyas mano de obra, equipos, herramientas menores ni EPP.""",
            'mano_obra': """- La cuadrilla se arma por oficios de montaje (p. ej. soldador calificado, armador o ajustador, tubero, rigger, ayudante, supervisor de montaje cuando la actividad lo exige). Usa los del catálogo de la empresa.
- El rendimiento es el de la cuadrilla completa por jornada, en la unidad de la actividad (kg, t, pulgada-diámetro, ml, equipo montado…). Compruébalo con horas-hombre por unidad = personas × horas_jornada ÷ rendimiento: en montaje se razona por HH por kg, por pulgada-diámetro o por equipo.
- Incluye el personal de las tareas asociadas que se pagan con la actividad: izaje y maniobra, trazado y nivelación, soldadura, ensamble y torque, pruebas, protección.
- Condiciones que cambian el rendimiento: altura de trabajo, espacio confinado, posición de soldadura, espesor y material, acceso de la grúa, trabajo en planta en operación y permisos de trabajo. Si no constan en los «Detalles», pregúntalas.
- No incluyas inspección de calidad ni personal de gabinete salvo que los «Detalles» lo pidan.
- Usa «Referencias de mano de obra de la empresa» como punto de partida cuando existan.
- No incluyas materiales ni equipos.""",
            'equipos': """- Izaje y movimiento: grúa móvil o camión grúa (según capacidad), tecle, montacargas, plataforma elevadora.
- Soldadura y corte: máquina de soldar, equipo de oxicorte, horno de secado de electrodos, equipo de precalentamiento o tratamiento térmico.
- Ensamble y prueba: llaves de torque o tensionadores hidráulicos, bomba de prueba hidrostática, compresor, equipo de alineación láser.
- Estima las horas-máquina por unidad de la actividad a partir del rendimiento de la cuadrilla: un equipo que trabaja toda la jornada con ella son horas_jornada ÷ rendimiento. Si el uso es parcial (grúa para maniobras puntuales), justifica el tiempo en «justificacion».
- Revisa «Ya confirmado en pasos anteriores»: cada material o tarea puede requerir equipo. Incluye solo el que realmente se necesita.
- No incluyas herramientas manuales ni menores (el perfil de cálculo ya las cubre con un porcentaje), ni EPP, ni equipos de proveedores.
- Si dudas entre equipos alternativos, pregunta con una consulta «opciones».""",
        },
    },
    {
        'nombre': 'Eléctrica e instrumentación', 'orden': 3,
        'descripcion': 'Montaje eléctrico y de instrumentación: bandejas, canalizaciones, cableado, tableros, iluminación, puesta a tierra, instrumentos y lazos de control.',
        'unidades': 'ml, pto, pza, tablero, instrumento',
        'dominio': ('montaje eléctrico y de instrumentación (bandejas, canalizaciones, cableado, tableros, iluminación, puesta a tierra, '
                    'instrumentos y lazos de control)'),
        'alternativa': 'tablero ya armado frente a armado en obra',
        'ej_unidad': 'un cable medido en kg',
        'ej': {'a': 'Tendido de cable 3x2.5 mm² en bandeja', 'b': 'Tendido de cable 3x4 mm² en bandeja', 'instr': 'usa cable de 4 mm²',
               'c': 'Instalación de tablero de distribución'},
        'clasificacion': '''Eres un especialista en montaje eléctrico y de instrumentación. Clasifica técnicamente la actividad indicada en cinco campos breves:
- sistema_constructivo: p. ej. «Cableado de fuerza», «Canalización en bandeja», «Instrumentación de campo».
- tipo_elemento: p. ej. «Cable», «Bandeja», «Tablero», «Transmisor».
- material_principal: el material que define la actividad.
- proceso_principal: el proceso de ejecución, p. ej. «Tendido», «Conexionado», «Calibración».
- categoria: una de «Cableado», «Canalizaciones», «Tableros», «Instrumentación», «Puesta a tierra», «Otros».
Usa términos técnicos habituales en obra. Responde SOLO con el JSON pedido.''',
        'datos': ('Eléctrica e instrumentación: tipo y calibre del conductor o del instrumento, número de conductores o de puntos, tipo de '
                  'canalización y longitud, tensión o servicio, ubicación (área clasificada, altura, enterrado) y si se incluye el '
                  'suministro o solo el montaje.'),
        'criterios': {
            'materiales': """- NIVEL DE DESGLOSE: un material va al nivel en que se compra: conductor por metro (con su calibre y aislamiento), bandeja o canalización por metro, tableros y gabinetes completos, instrumentos y luminarias por unidad. NO desgloses un tablero ni un instrumento en sus componentes.
- Accesorios asociados: soportes, abrazaderas, uniones, curvas, conectores y prensaestopas, terminales, cintas aislantes y termocontraíbles, identificación y rotulado, borneras.
- Cables y canalizaciones: considera el recorrido real y la reserva; el desperdicio_pct cubre cortes y sobrantes de bobina.
- Puesta a tierra: conductor, varillas o electrodos, soldadura exotérmica o conectores, relleno mejorador.
- Instrumentación: instrumento, accesorios de montaje y de proceso (válvulas de aislamiento, manifolds, tubing y conexiones) y cable de señal. La calibración solo entra si se cobra con la actividad.
- Suministro y montaje: si la actividad es solo montaje, el equipo principal (tablero, motor, instrumento) no se incluye. Si no consta, pregúntalo con una consulta «opciones».
- No incluyas mano de obra, equipos, herramientas menores ni EPP.""",
            'mano_obra': """- Oficios típicos: electricista o instalador (por categoría), instrumentista, cablista, ayudante, supervisor. Usa los del catálogo de la empresa.
- El rendimiento es el de la cuadrilla completa por jornada, en la unidad de la actividad (ml de cable o bandeja, puntos, tableros, instrumentos montados…). Compruébalo con horas-hombre por unidad = personas × horas_jornada ÷ rendimiento.
- Incluye lo que se paga con la actividad: tendido y fijación, conexionado y rotulado, pruebas básicas (continuidad, aislamiento, lazo).
- Condiciones que cambian el rendimiento: altura, tipo de canalización (enterrada, aérea, en bandeja), diámetro y número de conductores, área clasificada o planta en operación. Si no constan en los «Detalles», pregúntalas.
- La puesta en marcha, calibración y comisionamiento solo entran si los «Detalles» lo piden.
- Usa «Referencias de mano de obra de la empresa» como punto de partida cuando existan.
- No incluyas materiales ni equipos.""",
            'equipos': """- Tendido y montaje: winche o malacate, tirador de cable, bobinadora, plataforma elevadora, grúa pequeña, equipo de zanjeo.
- Prueba y medición que se usa con la actividad: megóhmetro, multímetro de campo, comunicador de instrumentos, calibrador; solo si se cobran por hora.
- Estima las horas-máquina por unidad a partir del rendimiento de la cuadrilla y justifica el uso parcial en «justificacion».
- Revisa «Ya confirmado en pasos anteriores»: cada material o tarea puede requerir equipo. Incluye solo el que realmente se necesita.
- No incluyas herramientas manuales ni menores (el perfil de cálculo ya las cubre con un porcentaje), ni EPP, ni equipos de proveedores.
- Si dudas entre equipos alternativos, pregunta con una consulta «opciones».""",
        },
    },
    {
        'nombre': 'Mantenimiento', 'orden': 4,
        'descripcion': 'Mantenimiento industrial y de instalaciones: preventivo, correctivo, paradas de planta, reparación y reemplazo de equipos y componentes.',
        'unidades': 'intervención, equipo, mes, h',
        'dominio': ('mantenimiento industrial y de instalaciones (preventivo, correctivo, paradas de planta, reparación y reemplazo de '
                    'equipos y componentes)'),
        'alternativa': 'repuesto nuevo frente a componente reparado',
        'ej_unidad': 'una intervención medida en m³',
        'ej': {'a': 'Cambio de rodamientos de bomba centrífuga', 'b': 'Cambio de rodamientos y sello mecánico de bomba centrífuga',
               'instr': 'incluye también el sello mecánico', 'c': 'Lubricación de motor eléctrico'},
        'clasificacion': '''Eres un especialista en mantenimiento industrial y de instalaciones. Clasifica técnicamente la actividad indicada en cinco campos breves:
- sistema_constructivo: p. ej. «Equipo rotativo», «Sistema de tuberías», «Instalación eléctrica».
- tipo_elemento: p. ej. «Bomba», «Válvula», «Motor».
- material_principal: el componente o material que define la actividad.
- proceso_principal: el proceso de ejecución, p. ej. «Cambio de rodamientos», «Lubricación», «Inspección».
- categoria: una de «Preventivo», «Correctivo», «Parada de planta», «Reemplazo de componentes», «Otros».
Usa términos técnicos habituales en obra. Responde SOLO con el JSON pedido.''',
        'datos': ('Mantenimiento: equipo o instalación, tipo de intervención (preventiva, correctiva, reemplazo), frecuencia o alcance, '
                  'estado del equipo (en operación o detenido), repuestos incluidos o no, condiciones de acceso y de seguridad.'),
        'criterios': {
            'materiales': """- La actividad es una INTERVENCIÓN (una tarea de mantenimiento, una reparación, el reemplazo de un componente) y su unidad suele ser la intervención, el equipo, el mes o la hora. Las cantidades son por UNA unidad de intervención.
- Repuestos y componentes que se cambian (rodamientos, sellos, empaquetaduras, filtros, correas, válvulas, piezas), con su especificación. Distingue lo que se repone siempre de lo que solo se cambia si falla: en ese caso pregunta o usa una probabilidad justificada en «justificacion».
- Consumibles de la intervención: lubricantes y grasas, solventes y desengrasantes, sellantes, trapos industriales, abrasivos, pintura de retoque.
- Materiales de aislamiento y bloqueo del trabajo solo si son consumibles propios de la tarea.
- Si no consta si el repuesto lo provee el cliente o está incluido en el precio, pregúntalo con una consulta «opciones».
- No incluyas mano de obra, equipos, herramientas menores ni EPP.""",
            'mano_obra': """- Oficios típicos: técnico mecánico, eléctrico o instrumentista, soldador, lubricador, operador, ayudante, supervisor de mantenimiento. Usa los del catálogo de la empresa.
- El rendimiento es el de la cuadrilla completa por jornada, en la unidad de la actividad (intervenciones, equipos, horas…). Una intervención larga puede rendir menos de 1 por jornada (p. ej. 0.5): es válido. Compruébalo con horas-hombre por unidad = personas × horas_jornada ÷ rendimiento.
- Incluye el personal de las tareas asociadas: bloqueo y etiquetado, desmontaje y montaje, limpieza, pruebas de funcionamiento y entrega.
- Condiciones que cambian el rendimiento: equipo en operación o detenido, acceso, altura o espacio confinado, permisos de trabajo, ventana de parada. Si no constan en los «Detalles», pregúntalas.
- No incluyas ingeniería ni planificación salvo que los «Detalles» lo pidan.
- Usa «Referencias de mano de obra de la empresa» como punto de partida cuando existan.
- No incluyas materiales ni equipos.""",
            'equipos': """- Apoyo de la intervención: grúa o tecle para desmontaje, plataforma elevadora, bomba de vacío o de prueba, equipo de lavado a presión, compresor.
- Diagnóstico (analizador de vibraciones, termografía, medidor de espesores) solo si se cobra por hora de uso.
- Estima las horas-máquina por unidad de intervención y justifica el uso parcial en «justificacion».
- Revisa «Ya confirmado en pasos anteriores»: cada material o tarea puede requerir equipo. Incluye solo el que realmente se necesita.
- No incluyas herramientas manuales ni menores (el perfil de cálculo ya las cubre con un porcentaje), ni EPP, ni equipos de proveedores.
- Si dudas entre equipos alternativos, pregunta con una consulta «opciones».""",
        },
    },
]


# Ejemplos de obra civil que viven en las reglas comunes; en los demás tipos de trabajo se cambian por uno propio.
EJEMPLOS_CIVILES = [
    ('(p. ej. hormigón consolidado o por componentes)', '(p. ej. {alternativa})'),
    ('(p. ej. «elaborado en obra» implica usar los componentes; «premezclado» implica el hormigón consolidado; '
     '«incluir encofrado» implica incluirlo)',
     '(p. ej. «fabricado en obra» implica usar los componentes; «ya fabricado» implica el elemento consolidado; '
     '«incluir los trabajos de apoyo» implica incluirlos)'),
    ('(encofrado, apuntalamiento, andamios, protecciones)', '(apuntalamiento, andamios, protecciones)'),
]


def re_ejemplos(texto, ej):
    """Cambia los ejemplos de título de obra civil de los pasos de modificación por los del tipo de trabajo."""
    texto = texto.replace('p. ej. «Hormigón H21 en columnas» → «Hormigón H25 en vigas»', f'p. ej. «{ej["a"]}» → «{ej["b"]}»')
    return texto.replace('«Hormigón H21 en columnas» + «usa H25 y que sea para vigas» → «Hormigón H25 en vigas». «Muro de ladrillo» + «sube el desperdicio» → el mismo título.',
                         f'«{ej["a"]}» + «{ej["instr"]}» → «{ej["b"]}». «{ej["c"]}» + «sube el desperdicio» → el mismo título.')


def _sacar_datos_minimos(reglas):
    """Separa de las reglas los datos mínimos por tipo de actividad (regla 8): son del tipo de trabajo, no de la forma de responder.
    Devuelve (reglas sin ellos, [viñetas])."""
    lineas = reglas.split('\n')
    try:
        i = next(k for k, l in enumerate(lineas) if MARCA_DATOS in l)
    except StopIteration:
        return reglas, []
    j = i + 1
    while j < len(lineas) and re.match(r'^\s+- ', lineas[j]):
        j += 1
    viñetas = [l.strip()[2:].strip() for l in lineas[i + 1:j]]
    nuevas = lineas[:i + 1] + ['   (Los datos mínimos de cada tipo de trabajo están en los criterios del tipo de trabajo.)'] + lineas[j:]
    return '\n'.join(nuevas), viñetas


def partir(texto):
    """Reparte un prompt en (rol, criterios, reglas). El primer párrafo es el rol. Las reglas son lo que dice cómo responder:
    desde «REGLAS GENERALES» (o, si no hay, desde un párrafo que empiece por «REGLAS») y, si tampoco, la instrucción final
    «Responde SOLO con el JSON pedido». El resto son criterios."""
    partes = texto.split('\n\n')
    rol, resto = partes[0], partes[1:]
    k = next((n for n, p in enumerate(resto) if p.startswith(MARCA_REGLAS)), None)
    if k is None:
        k = next((n for n, p in enumerate(resto) if p.startswith('REGLAS')), None)
    if k is not None:
        return rol, '\n\n'.join(resto[:k]), '\n\n'.join(resto[k:])
    # Sin párrafo de reglas: la instrucción final de respuesta, aunque vaya pegada a otro texto.
    completo = '\n\n'.join(partes)
    i = completo.rfind('Responde SOLO')
    if i <= 0:
        return rol, '\n\n'.join(resto), ''
    antes, reglas = completo[:i].rstrip(), completo[i:]
    cuerpo = antes.split('\n\n')
    return cuerpo[0], '\n\n'.join(cuerpo[1:]), reglas


# Alcance del ítem (paso 1): la clasificación lo redacta y los pasos de insumos lo respetan. Son genéricos dentro de cada tipo de trabajo.
REGLA_ALCANCE_CLASIFICACION = """ALCANCE DEL ÍTEM (además de las cinco etiquetas):
- «resumen_alcance» (SIEMPRE, nunca vacío): 4 a 8 frases que dejan claro qué cubre este ítem por UNA unidad. Los pasos de materiales, mano de obra y equipos NO recibirán el proyecto ni los detalles: leerán solo este resumen, así que debe bastarles por sí solo. Reúne, de lo que recibes: qué obra es y dónde (tipo de proyecto y ciudad, solo lo que condiciona el trabajo), qué trabajo comprende y qué NO comprende (por ejemplo, si incluye el suministro de los materiales o solo la ejecución), las especificaciones y dimensiones que definen el trabajo, el método de ejecución, las condiciones que afectan el rendimiento y, si consta, la cantidad total solo como referencia para dimensionar cuadrilla y equipos. No repitas el título ni cuentes la historia del proyecto.
- No inventes datos. Lo que no conste en lo recibido no se afirma: si es esencial, pregúntalo; si no, déjalo fuera o dilo como supuesto.
- «consultas»: déjalas vacías cuando el alcance ya queda claro. Solo pregunta (máximo 3) cuando falte un dato que cambie de verdad el alcance: qué incluye o excluye (suministro y ejecución), el método, las condiciones de ejecución o una especificación que define el trabajo. Cada consulta lleva «id», «tipo» («opciones» con 2 a 4 «opciones» {clave, etiqueta}, o «dato» para respuesta abierta), «pregunta», «motivo», «recomendada» (siempre; en «dato» pon la respuesta más probable como única opción) y «por_que». No repreguntes lo que ya aparece en «Preguntas tuyas ya respondidas»: dalo por respondido e incorpóralo al resumen.
- La persona NO revisa ni edita el resumen: lo que escribas se tomará como decidido en los pasos siguientes y no se volverá a preguntar. Por eso, si algo esencial no lo sabes, pregúntalo aquí (consultas) hasta que no queden dudas, en vez de dejarlo abierto o suponerlo.
- Si «ultima_ronda» es true, no hagas consultas (devuélvelas vacías): redacta el resumen con los supuestos más razonables y escríbelos como tales («Se supone que…»)."""

REGLA_ALCANCE_INSUMOS = """ALCANCE DEL ÍTEM: recibes la actividad, su unidad y el «Alcance del ítem», un resumen ya definido (con las respuestas de la persona a las preguntas del paso 1) que reúne lo que importa del proyecto, de los detalles y de las aclaraciones. Es tu única fuente de contexto sobre la obra y el trabajo: respétalo, no propongas lo que excluye ni dejes fuera lo que incluye.

LO YA DEFINIDO NO SE PREGUNTA (manda sobre las demás reglas de preguntas, incluidas los datos mínimos, el alcance total y el rendimiento):
- Antes de hacer una consulta, revisa el «Alcance del ítem», las «aclaraciones» (también las del paso anterior) y las preguntas ya respondidas.
- Todo lo que el alcance afirma (qué incluye y qué no, suministro o solo ejecución, método, condiciones de ejecución, especificaciones y dimensiones, cantidad total) es una decisión ya tomada: aplícala sin preguntarla, ni reformulada ni como opciones. También vale lo escrito como supuesto («Se supone que…»), porque ya quedó definido.
- Pregunta solo lo que el alcance NO dice y cambia de verdad la propuesta. Una consulta que repite algo ya definido es un error.
- Si el alcance ya define lo necesario, propón directamente las filas, sin consultas."""

REGLAS_ALCANCE = {'clasificacion': REGLA_ALCANCE_CLASIFICACION, 'materiales': REGLA_ALCANCE_INSUMOS, 'mano_obra': REGLA_ALCANCE_INSUMOS,
                  'equipos': REGLA_ALCANCE_INSUMOS, 'verificar': REGLA_ALCANCE_INSUMOS}


def con_alcance(paso, reglas):
    """Las reglas con la del alcance del ítem al final (idempotente). Los pasos sin regla de alcance quedan igual."""
    regla = REGLAS_ALCANCE.get(paso)
    if not regla:
        return reglas
    reglas = reglas or ''
    i = reglas.find('ALCANCE DEL ÍTEM')
    base = reglas[:i].rstrip() if i >= 0 else reglas.rstrip()      # la regla va al final: una versión anterior se reemplaza
    return f'{base}\n\n{regla}' if base else regla


PASOS_INSUMOS = ('materiales', 'mano_obra', 'equipos', 'verificar')
_DETALLES = [   # (de, a): los pasos de insumos ya no reciben los «Detalles», solo el alcance; de lo más a lo menos específico
    ('dicen los Detalles, el proyecto, las aclaraciones', 'dicen el «Alcance del ítem» (que ya reúne el proyecto y los detalles), las aclaraciones'),
    ('los «Detalles» lo pidan', 'el «Alcance del ítem» lo pida'), ('los «Detalles» lo piden', 'el «Alcance del ítem» lo pide'),
    ('los «Detalles» lo justifican', 'el «Alcance del ítem» lo justifica'),
    ('de los «Detalles»', 'del «Alcance del ítem»'), ('los «Detalles»', 'el «Alcance del ítem»'),
    ('Si «Detalles»', 'Si el «Alcance del ítem»'), ('en «Detalles»', 'en el «Alcance del ítem»'),
    ('«Detalles»', 'el «Alcance del ítem»'),
]


def sin_detalles(texto):
    """El texto de un prompt de insumos refiriéndose al «Alcance del ítem» en vez de a los «Detalles» (que ya no se mandan). Idempotente."""
    for de, a in _DETALLES:
        texto = (texto or '').replace(de, a)
    return texto


def adaptar_a_alcance(paso, rol, criterios, reglas):
    """Las casillas de un prompt ya adaptadas al alcance: sin «Detalles» en los pasos de insumos y con la regla del alcance
    al final de las reglas. Los demás pasos solo suman su regla (si la tienen)."""
    if paso in PASOS_INSUMOS:
        rol, criterios, reglas = sin_detalles(rol), sin_detalles(criterios), sin_detalles(reglas)
    return rol, criterios, con_alcance(paso, reglas)


def armar(plantilla, paso, base):
    """Las casillas (rol, criterios, reglas) de un paso para una plantilla, a partir del prompt base."""
    rol, criterios, reglas = partir(base)
    rol = PATRON_DOMINIO.sub(plantilla['dominio'], rol)
    reglas, viñetas = _sacar_datos_minimos(reglas)
    if plantilla['nombre'] != 'Obras civiles':
        for civil, propio in EJEMPLOS_CIVILES:
            reglas = reglas.replace(civil, propio.format(alternativa=plantilla.get('alternativa', 'una alternativa u otra')))
        if paso == 'clasificacion' and plantilla.get('clasificacion'):
            rol, criterios = plantilla['clasificacion'], ''
        if plantilla.get('ej_unidad'):
            rol, criterios, reglas = (t.replace('(un muro medido en kg)', f"({plantilla['ej_unidad']})") for t in (rol, criterios, reglas))
        ej = plantilla.get('ej')
        if ej:   # ejemplos de títulos de los pasos de modificación
            rol, criterios, reglas = (re_ejemplos(t, ej) for t in (rol, criterios, reglas))
    propios = (plantilla.get('criterios') or {}).get(paso)
    if propios:   # criterios propios del tipo de trabajo, en lugar de los de obra civil
        criterios = propios
        viñetas = [plantilla['datos']] if plantilla.get('datos') else []
    else:
        viñetas = [v for v in viñetas if not v.startswith('Obras industriales')] if plantilla['nombre'] == 'Obras civiles' else []
    if viñetas and paso in ('materiales', 'mano_obra', 'equipos'):
        criterios = (criterios + '\n\n' if criterios else '') + 'DATOS MÍNIMOS QUE DEFINEN LA ACTIVIDAD (los usa la regla 8):\n' + '\n'.join(f'- {v}' for v in viñetas)
    return adaptar_a_alcance(paso, rol, criterios, reglas)


def cargar(PlantillaAPU, PromptAPU, base=None):
    """Crea las plantillas y los prompts que falten. Devuelve cuántos prompts creó."""
    base = base or json.loads(BASE.read_text(encoding='utf-8'))
    creados = 0
    for p in PLANTILLAS:
        plantilla, _ = PlantillaAPU.objects.get_or_create(nombre=p['nombre'], defaults={
            'descripcion': p['descripcion'], 'unidades_sugeridas': p['unidades'], 'orden': p['orden']})
        for paso, texto in base.items():
            if PromptAPU.objects.filter(plantilla=plantilla, paso=paso).exists():
                continue
            rol, criterios, reglas = armar(p, paso, texto)
            modelo, razonamiento = MODELOS[paso]
            PromptAPU.objects.create(plantilla=plantilla, paso=paso, rol=rol, criterios=criterios, reglas=reglas,
                                     modelo=modelo, razonamiento=razonamiento, version=1, vigente=True,
                                     comentario='Carga inicial')
            creados += 1
    return creados


CAMPOS_PROMPT = ('rol', 'criterios', 'reglas', 'notas', 'modelo', 'razonamiento')


def aplicar_actuales(PlantillaAPU, PromptAPU, datos=None):
    """Deja las plantillas y prompts como estaban al preparar el lanzamiento (`semilla/plantillas_actuales.json`, exportado de la
    base de desarrollo). Es idempotente y no pisa el trabajo del superusuario: la plantilla y el prompt que faltan se crean, y el
    que sigue siendo el de la carga inicial (versión 1 sin editar) se actualiza en el lugar. Un prompt que ya se editó en la web
    (otra versión o con otro comentario) no se toca. Devuelve cuántos prompts creó o actualizó."""
    datos = datos if datos is not None else json.loads(ACTUALES.read_text(encoding='utf-8'))
    cambios = 0
    for d in datos:
        plantilla, _ = PlantillaAPU.objects.get_or_create(nombre=d['nombre'], defaults={
            'descripcion': d['descripcion'], 'unidades_sugeridas': d['unidades_sugeridas'], 'orden': d['orden'], 'activo': d['activo']})
        for paso, campos in d['prompts'].items():
            vigente = PromptAPU.objects.filter(plantilla=plantilla, paso=paso, vigente=True).first()
            if vigente is None:
                PromptAPU.objects.create(plantilla=plantilla, paso=paso, version=1, vigente=True, comentario='Carga inicial', **campos)
                cambios += 1
            elif vigente.version == 1 and vigente.comentario == 'Carga inicial' and any(getattr(vigente, k) != campos[k] for k in CAMPOS_PROMPT):
                for k in CAMPOS_PROMPT:
                    setattr(vigente, k, campos[k])
                vigente.save(update_fields=list(CAMPOS_PROMPT))
                cambios += 1
    return cambios
