# Predicción del ISD por distrito y vertical

Código del componente de forecasting de una plataforma de gestión de contexto urbano basada en FIWARE y NGSI v2.

El proyecto consulta un histórico de índices ya calculados en PostgreSQL, entrena modelos independientes por distrito y vertical con NeuralProphet, evalúa una prueba temporal frente a persistencia y exporta predicciones diarias a siete días. Incluye una carga opcional a una tabla de predicciones existente.

No descarga datos directamente del Ayuntamiento, no calcula los índices originales y no publica entidades en Orion. Su entrada es el histórico que la plataforma ha integrado y transformado previamente.

## Contenido

```text
.
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── prediccion_isd_por_vertical.ipynb
├── predecir_isd.py
└── insertar_predicciones.py
```

El notebook conserva el flujo interactivo, incluidos gráficos y carga opcional desactivada. El script de entrenamiento omite los gráficos y la inserción. El script de carga permite reutilizar resultados sin entrenar de nuevo. Las dos formas de entrenamiento son alternativas, no pasos consecutivos.

## Requisitos y estado de validación

- Acceso a PostgreSQL con el esquema de entrada descrito abajo.
- Entorno Python con las dependencias de `requirements.txt`.
- Recursos y tiempo suficientes para entrenar modelos independientes por serie.

Las versiones directas fijadas proceden del registro del experimento aportado. Ese registro indica Python 3.13.9, pero no incluye el árbol completo de dependencias ni acredita que una instalación limpia con esa versión sea reproducible. No se garantiza la instalación en todas las versiones de Python: hay que comprobar la compatibilidad conjunta de NeuralProphet, PyTorch, NumPy y el sistema operativo.

Esta distribución se ha revisado sintácticamente y se han eliminado las salidas del notebook. No se ha ejecutado aquí un entrenamiento completo ni una carga sobre PostgreSQL. `requirements.txt` no es un lock completo; después de validar un entorno, conservar `python --version` y `pip freeze` como evidencias locales.

## Instalación

Desde la raíz del repositorio:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

En PowerShell, activar con `.\.venv\Scripts\Activate.ps1`.

## Configuración de acceso

La conexión utiliza estas variables de entorno: `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` y `PGPASSWORD`. No se incluyen credenciales reales ni se imprime la URL de conexión.

Copiar `.env.example` a `.env` y completar los valores únicamente en local. El código no carga `.env` automáticamente. Para Bash, si se trata de un fichero propio y de confianza con sintaxis válida de shell:

```bash
set -a
source .env
set +a
```

No ejecutar `source` sobre ficheros de terceros: es ejecución de código de shell. En otros entornos, establecer las variables mediante el mecanismo correspondiente. No introducir contraseñas directamente en comandos que queden en el historial.

## Contrato del histórico de entrada

Tabla existente: `madrid.isd_districtisdobserved`.

Columnas utilizadas:

| Grupo | Columnas |
|---|---|
| Identificación | `fiwareservicepath`, `entityid`, `entitytype` |
| Tiempo | `recvtime`, `dateobserved`, `aggregationlevel` |
| Índices | `isdairquality`, `isdnoiselevel`, `isdcrowdflow`, `isdenergyconsumption`, `isdwaterquality` |
| Calidad observada | `dataqualityscore` |

Los índices deben ser numéricos. `dateobserved` debe representar instantes inequívocos; se recomienda que sea `timestamptz`. Si el origen almacena timestamps sin zona, hay que determinar su zona real antes de usar esta conversión: no asumir que son UTC.

El flujo inventaría los conjuntos disponibles y filtra por `/isd`, `DistrictISDObserved` y `day`. Estos valores están en la sección de selección del conjunto y deben ajustarse si el entorno usa otros. El script no crea ni modifica el histórico.

## Ejecución

### Notebook

```bash
python -m jupyterlab
```

Abrir el notebook desde la raíz y ejecutar las celdas en orden. Revisar el inventario, los filtros y los parámetros antes del entrenamiento. La última celda prepara y muestra el lote, pero no inserta salvo que se cambie `EJECUTAR_INSERCION` a `True`.

### Script

```bash
python predecir_isd.py
```

El entrenamiento exporta un directorio independiente por ejecución dentro de `output/`. Esto evita que un CSV de una ejecución antigua se mezcle accidentalmente con una nueva. La exportación no debe reutilizarse mientras el entrenamiento siga ejecutándose.

### Carga de un lote existente

Reemplazar el directorio del ejemplo por el generado realmente:

```bash
# Validación y vista previa; requiere conexión para reflejar la tabla.
python insertar_predicciones.py output/LOTE_GENERADO

# Inserción explícita después de revisar la vista previa.
python insertar_predicciones.py output/LOTE_GENERADO --confirmar
```

La vista previa no modifica registros. La carga se realiza en una transacción. Si se produce un error, no se confirma una inserción parcial.

## Metodología

1. Selección del conjunto de observaciones.
2. Selección del registro con mayor `recvtime` para cada entidad e instante observado.
3. Conversión a `Europe/Madrid`, agregación diaria por media y exclusión del día actual.
4. Conversión a formato largo: distrito, fecha, vertical y valor.
5. Regularización diaria y conservación del tramo posterior al último hueco.
6. Separación temporal: entrenamiento, validación de siete días y prueba final de siete días.
7. Persistencia para series completamente constantes; NeuralProphet para las restantes series elegibles.
8. Evaluación con MAE y RMSE, comparación con persistencia y reentrenamiento sobre la serie disponible.
9. Predicción desde el último dato de cada serie, con horizonte de siete días.
10. Exportación de resultados y carga opcional.

Se requieren inicialmente 60 puntos de entrenamiento más los bloques de validación y prueba. No es una garantía estadística de suficiencia. La optimización con Optuna está desactivada por defecto. Sin Optuna, el bloque de validación no selecciona hiperparámetros.

El formato ancho incluye únicamente distritos cuyas verticales predichas comparten origen temporal. Puede contener menos de cinco dimensiones si otras series no son elegibles. No se alinean orígenes distintos mediante rellenos artificiales.

## Parámetros

Modificar la sección de parámetros y, cuando corresponda, la configuración del modelo en el notebook o en el script elegido:

| Parámetro | Valor inicial | Significado |
|---|---|---|
| `FREQ` | `D` | Frecuencia diaria |
| `HORIZON` | 7 | Días a predecir |
| `TIMEZONE` | `Europe/Madrid` | Calendario de agregación |
| `MIN_TRAIN_POINTS` | 60 | Mínimo inicial de entrenamiento |
| `DISTRICTS` | `None` | Todos los distritos seleccionados |
| `USE_OPTUNA` | `False` | Búsqueda opcional de hiperparámetros |
| `ISD_BOUNDS` | `None` | Rango no impuesto automáticamente |

El notebook y los scripts contienen copias del flujo para facilitar su uso. Si se modifica la metodología, mantener ambas versiones sincronizadas; para una evolución mayor conviene extraer funciones compartidas a un paquete.

## Resultados exportados

| Fichero | Contenido |
|---|---|
| `diagnostico_series.csv` | Cobertura, fechas y variabilidad |
| `estado_series.csv` | Elegibilidad, puntos descartados y errores |
| `evaluacion_modelos.csv` | Métricas y comparación con persistencia |
| `predicciones_isd_detalle.csv` | Predicción, método, origen y generación por vertical |
| `predicciones_isd_verticales.csv` | Una fila por distrito y fecha objetivo |
| `comparacion_test.csv` | Observaciones y predicciones de prueba |
| `parametros_modelos.json` | Parámetros de los modelos entrenados |
| `configuracion_experimento.json` | Configuración y fecha de generación |

Algunos CSV solo se generan si existen resultados. Los outputs no se distribuyen en este repositorio. Para una reproducción exacta hacen falta, además del código, el mismo histórico de entrada, su fecha de extracción, el entorno completo y los recursos de ejecución. No se garantiza identidad bit a bit entre plataformas.

## Contrato de persistencia

La tabla `madrid.isd_districtisdforecast` debe existir con el DDL del despliegue. No se incluye una migración automática ni se reemplaza su estructura.

- Clave primaria: `(entityid, dateobserved, recvtime)`.
- `entitytype`: `DistrictISDForecast`.
- `fiwareservicepath` y `aggregationlevel`: configuración del lote.
- `dateobserved`: fecha objetivo en UTC; la medianoche local puede corresponder al día anterior en UTC.
- `recvtime`: fecha de generación del lote en UTC sin zona, por el tipo `timestamp` existente. Es una convención deliberada de esta carga, no la hora real de recepción.
- Predicciones ausentes: `NULL`.
- Pesos, índice general, categoría, ubicación y calidad: `NULL`, porque este flujo no los calcula.
- Metadatos de vertical: JSON textual con método, origen, horizonte y generación. Son metadatos propios de trazabilidad, no una notificación NGSI del broker.

El script comprueba coherencia entre el CSV ancho, el detalle y la configuración. `ON CONFLICT DO NOTHING` omite claves existentes: repetir el mismo lote no actualiza resultados previos. Si se corrige un lote conservando su fecha de generación, no se sobrescribe automáticamente.

La clave primaria no incluye `fiwareservicepath` ni `entitytype`. Por ello, esta idempotencia se limita al ámbito actual de la tabla; no representa una estrategia multiinquilino general.

## Límites e interpretación

Los datos reales presentan distintas frecuencias de actualización, formatos, huecos y discontinuidades. El tratamiento de huecos puede reducir mucho el histórico útil y los distritos disponibles.

La predicción parte del último dato, no del día de ejecución. Un histórico atrasado genera fechas objetivo que pueden estar ya en el pasado. Revisar siempre `origen_prediccion`, `ds` y `generado_en` antes de usar resultados operativos.

El modelo no restringe automáticamente las salidas a `[0, 1]`. La carga avisa, pero conserva los valores. Con `ISD_BOUNDS = None`, la columna `fuera_de_rango` del detalle no demuestra que las predicciones sean válidas dentro de esa escala.

No se calcula ISD general ni categoría sin los pesos y reglas originales del índice. Tampoco se interpreta la disponibilidad de verticales como precisión o calidad de predicción. Evaluar cada modelo frente a persistencia: entrenar una red no garantiza mejorar el modelo base.

## Seguridad y publicación

- No subir `.env`, históricos, CSV de ejecución, modelos, logs ni volcados de base de datos.
- El notebook distribuido no contiene outputs ni contadores de ejecución. Limpiarlos de nuevo antes de publicar cualquier ejecución local: pueden revelar identidades de base de datos, errores, datos o infraestructura.
- `.gitignore` no elimina ficheros ya versionados. Revisar `git status`, el diff preparado y el historial antes de publicar. Si una credencial se ha expuesto, revocarla o rotarla; borrarla de la última versión no basta.
- Usar mínimo privilegio: lectura del histórico; para carga, lectura e inserción sobre el destino y acceso al esquema, sin permisos de borrado o administración.
- Para conexiones remotas, configurar TLS con validación de certificado según el servidor. El ejemplo no garantiza por sí solo una conexión cifrada.
- No se integra con Keycloak: la conexión a PostgreSQL usa sus propias credenciales y autorización.

## Automatización con Jenkins

Configurar las credenciales mediante el almacén de Jenkins e inyectarlas como variables de entorno, no en el código ni en parámetros visibles. Ejecutar primero instalación y `pip check`, después entrenamiento, revisar `estado_series.csv` y las métricas, y finalmente cargar el directorio exacto generado si se autoriza la escritura. No habilitar la inserción por defecto en un job que solo deba evaluar modelos.

La ejecución correcta del proceso no demuestra que todas las series hayan terminado bien: revisar los estados individuales antes de dar un lote por válido.
