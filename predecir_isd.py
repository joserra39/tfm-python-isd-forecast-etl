"""Entrenamiento y exportación. No inserta en PostgreSQL."""

def main():
    # ============================================================
    # 2. Importaciones, configuración y versiones
    # ============================================================

    import sys
    import logging
    import warnings
    from pathlib import Path

    # ------------------------------------------------------------
    # Filtrar únicamente las advertencias conocidas.
    # No se ocultan errores reales del entrenamiento.
    # ------------------------------------------------------------

    warnings.filterwarnings(
        "ignore",
        message=r"pkg_resources is deprecated as an API.*",
        category=UserWarning,
        module=r"lightning_fabric(\..*)?",
    )

    warnings.filterwarnings(
        "ignore",
        message=(
            r"DataFrameGroupBy\.apply operated on the grouping columns.*"
        ),
        category=FutureWarning,
        module=r"neuralprophet(\..*)?",
    )

    warnings.filterwarnings(
        "ignore",
        message=r"Series\.view is deprecated.*",
        category=FutureWarning,
        module=r"neuralprophet(\..*)?",
    )

    # ------------------------------------------------------------
    # Preparar los directorios de trabajo.
    # ------------------------------------------------------------

    Path("output").mkdir(parents=True, exist_ok=True)
    Path("lightning_logs").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------
    # Configurar el log del proyecto sin mensajes duplicados.
    # ------------------------------------------------------------

    logger = logging.getLogger("tfm-isd-forecast")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.disabled = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console_handler = logging.StreamHandler(sys.stdout)

    console_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    logger.addHandler(console_handler)

    # Evitar que las advertencias capturadas por logging
    # se impriman dos veces.
    warnings_logger = logging.getLogger("py.warnings")

    if warnings_logger.handlers:
        warnings_logger.propagate = False

    logger.info("Entorno configurado.")

    # ============================================================
    # 3. Parámetros generales
    # ============================================================

    VERTICALES = [
        "isdairquality",
        "isdnoiselevel",
        "isdcrowdflow",
        "isdenergyconsumption",
        "isdwaterquality",
    ]

    FREQ = "D"
    HORIZON = 7

    # Tres bloques temporales:
    # entrenamiento | validación de 7 días | prueba final de 7 días
    VALIDATION_DAYS = HORIZON
    TEST_DAYS = HORIZON

    # Umbral inicial para este experimento, no garantía estadística.
    MIN_TRAIN_POINTS = 60
    MIN_TOTAL_POINTS = (
        MIN_TRAIN_POINTS + VALIDATION_DAYS + TEST_DAYS
    )

    TIMEZONE = "Europe/Madrid"

    # La guía utiliza un entorno distinto.
    # Este valor debe comprobarse con el diagnóstico de la celda 5.
    SERVICE_PATH = "/isd"

    # Se configura después de consultar los valores reales.
    AGGREGATION_LEVEL = None
    ENTITY_TYPE = None

    # Para probar primero una sola serie:
    # DISTRICTS = ["Centro"]
    DISTRICTS = None

    # No asumir la escala del índice.
    # Configurar, por ejemplo, (0.0, 1.0) SOLO si está confirmado.
    ISD_BOUNDS = None

    # Empezar sin optimización automática.
    USE_OPTUNA = False
    N_TRIALS = 10

    # Conexión sin credenciales incrustadas ni salida de identidad del servidor.
    import os
    import pandas as pd
    from IPython.display import display
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL

    required = ["PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Faltan variables de entorno: " + ", ".join(missing))
    url = URL.create(
        "postgresql+psycopg2",
        username=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        host=os.environ["PGHOST"], port=int(os.environ["PGPORT"]),
        database=os.environ["PGDATABASE"],
    )
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)


    # ============================================================
    # 5. Inventario del histórico
    # ============================================================

    query_inventory = text("""
        SELECT
            fiwareservicepath,
            entitytype,
            aggregationlevel,
            count(*) AS registros,
            count(DISTINCT entityid) AS distritos,
            min(dateobserved) AS primera_observacion,
            max(dateobserved) AS ultima_observacion
        FROM madrid.isd_districtisdobserved
        GROUP BY
            fiwareservicepath,
            entitytype,
            aggregationlevel
        ORDER BY
            fiwareservicepath,
            entitytype,
            aggregationlevel
    """)

    with engine.connect() as conn:
        inventario = pd.read_sql(query_inventory, conn)

    display(inventario)

    # ============================================================
    # 6. Configuración de parámetros generales
    # ============================================================

    ENTITY_TYPE = 'DistrictISDObserved'
    AGGREGATION_LEVEL = 'day'
    SERVICE_PATH = '/isd'

    seleccion = inventario[
        inventario["fiwareservicepath"].eq(SERVICE_PATH)
    ].copy()

    if ENTITY_TYPE is not None:
        seleccion = seleccion[
            seleccion["entitytype"].eq(ENTITY_TYPE)
        ]

    if AGGREGATION_LEVEL is not None:
        seleccion = seleccion[
            seleccion["aggregationlevel"].eq(AGGREGATION_LEVEL)
        ]

    display(seleccion)

    if len(seleccion) != 1:
        raise ValueError(
            "Selecciona un único conjunto coherente mediante "
            "SERVICE_PATH, ENTITY_TYPE y AGGREGATION_LEVEL."
        )

    # ============================================================
    # 7. Consulta la extracción
    # ============================================================
    import numpy as np
    import pandas as pd

    from sqlalchemy import text
    from IPython.display import display

    conditions = [
        "fiwareservicepath = :service_path",
    ]

    params = {
        "service_path": SERVICE_PATH,
    }

    if ENTITY_TYPE is not None:
        conditions.append("entitytype = :entity_type")
        params["entity_type"] = ENTITY_TYPE

    if AGGREGATION_LEVEL is not None:
        conditions.append(
            "aggregationlevel = :aggregation_level"
        )
        params["aggregation_level"] = AGGREGATION_LEVEL

    where_sql = " AND ".join(conditions)

    query = text(f"""
        SELECT DISTINCT ON (
            fiwareservicepath,
            entityid,
            dateobserved
        )
            recvtime,
            fiwareservicepath,
            entityid,
            entitytype,
            dateobserved,
            aggregationlevel,
            isdairquality,
            isdnoiselevel,
            isdcrowdflow,
            isdenergyconsumption,
            isdwaterquality,
            dataqualityscore
        FROM madrid.isd_districtisdobserved
        WHERE {where_sql}
        ORDER BY
            fiwareservicepath,
            entityid,
            dateobserved,
            recvtime DESC
    """)

    with engine.connect() as conn:
        raw = pd.read_sql(query, conn, params=params)

    if raw.empty:
        raise ValueError(
            "No hay observaciones para los filtros seleccionados."
        )

    raw["dateobserved"] = pd.to_datetime(
        raw["dateobserved"],
        utc=True,
    )

    for col in VERTICALES + ["dataqualityscore"]:
        raw[col] = pd.to_numeric(
            raw[col],
            errors="coerce",
        )

    raw[VERTICALES] = raw[VERTICALES].replace(
        [np.inf, -np.inf],
        np.nan,
    )

    if DISTRICTS is not None:
        raw = raw[raw["entityid"].isin(DISTRICTS)].copy()

    if raw.empty:
        raise ValueError(
            "No quedan datos tras seleccionar los distritos."
        )

    display(raw.head())
    display(raw[VERTICALES].describe())

    # ============================================================
    # 8. Agregación diaria y formato largo
    # ============================================================

    # Primero se asigna cada observación al día local de Madrid.
    # Después se elimina la zona horaria para trabajar con fechas diarias.
    raw["ds"] = (
        raw["dateobserved"]
        .dt.tz_convert(TIMEZONE)
        .dt.tz_localize(None)
        .dt.normalize()
    )

    # Excluir el día actual: podría estar incompleto.
    today_local = (
        pd.Timestamp.now(tz=TIMEZONE)
        .tz_localize(None)
        .normalize()
    )

    raw = raw[raw["ds"] < today_local].copy()

    daily = (
        raw.groupby(
            ["entityid", "ds"],
            as_index=False,
        )[VERTICALES]
        .mean()
        .sort_values(["entityid", "ds"])
    )

    long_df = daily.melt(
        id_vars=["entityid", "ds"],
        value_vars=VERTICALES,
        var_name="vertical",
        value_name="y",
    )

    display(long_df.head(10))

    # ============================================================
    # 9. Diagnóstico de las series
    # ============================================================
    from pathlib import Path

    OUTPUT_DIR = Path("output") / pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%S%fZ")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    diagnosticos = []

    for (district, vertical), group in long_df.groupby(
        ["entityid", "vertical"]
    ):
        valid = (
            group[["ds", "y"]]
            .dropna(subset=["y"])
            .sort_values("ds")
        )

        if valid.empty:
            diagnosticos.append({
                "entityid": district,
                "vertical": vertical,
                "observaciones": 0,
                "dias_calendario": 0,
                "cobertura": np.nan,
                "valores_distintos": 0,
                "primera_fecha": pd.NaT,
                "ultima_fecha": pd.NaT,
            })
            continue

        calendar_days = (
            valid["ds"].max() - valid["ds"].min()
        ).days + 1

        diagnosticos.append({
            "entityid": district,
            "vertical": vertical,
            "observaciones": len(valid),
            "dias_calendario": calendar_days,
            "cobertura": len(valid) / calendar_days,
            "valores_distintos": valid["y"].nunique(),
            "primera_fecha": valid["ds"].min(),
            "ultima_fecha": valid["ds"].max(),
        })

    diagnostico = pd.DataFrame(diagnosticos)

    display(diagnostico)

    diagnostico.to_csv(
        OUTPUT_DIR / "diagnostico_series.csv",
        index=False,
    )

    # ============================================================
    # 10. Función para preparar la serie
    # ============================================================

    def preparar_serie(group):
        serie = (
            group[["ds", "y"]]
            .dropna(subset=["y"])
            .sort_values("ds")
            .drop_duplicates("ds")
            .reset_index(drop=True)
        )

        if serie.empty:
            return serie, 0

        regular = (
            serie.set_index("ds")
            .asfreq(FREQ)
            .reset_index()
        )

        missing_positions = np.flatnonzero(
            regular["y"].isna().to_numpy()
        )

        start = (
            int(missing_positions[-1]) + 1
            if len(missing_positions)
            else 0
        )

        tramo = regular.iloc[start:].reset_index(drop=True)

        discarded = len(serie) - len(tramo)

        return tramo, discarded

    # ============================================================
    # 11. Configuración del modelo
    # ============================================================

    import logging

    from neuralprophet import (
        NeuralProphet,
        set_random_seed,
        set_log_level,
    )

    BASE_PARAMS = {
        "n_lags": 14,
        "n_changepoints": 5,
        "learning_rate": 0.01,
        "ar_reg": 0.1,
        "epochs": 100,
    }


    def crear_modelo(params):
        set_random_seed(42)

        model = NeuralProphet(
            n_lags=params["n_lags"],
            n_forecasts=HORIZON,

            n_changepoints=params["n_changepoints"],

            weekly_seasonality=True,
            daily_seasonality=False,
            yearly_seasonality=False,

            ar_layers=[32],
            ar_reg=params["ar_reg"],

            learning_rate=params["learning_rate"],
            epochs=params["epochs"],
            batch_size=16,

            loss_func="MAE",

            # Evitar la ruta problemática observada al preparar
            # la predicción con impute_missing=False.
            impute_missing=True,

            # Cada modelo recibe una única serie.
            global_normalization=True,
        )

        # Aplicar el nivel después de construir el modelo.
        set_log_level("ERROR")

        return model

    # ============================================================
    # 12. Predicción desde un único origen
    # ============================================================

    def predecir_desde_origen(model, history):
        last_date = history["ds"].max()

        future = model.make_future_dataframe(
            history,
            periods=HORIZON,
            n_historic_predictions=False,
        )

        forecast = model.predict(future)

        expected_dates = pd.date_range(
            start=last_date + pd.Timedelta(days=1),
            periods=HORIZON,
            freq=FREQ,
        )

        forecast = forecast.copy()
        forecast["ds"] = pd.to_datetime(forecast["ds"])
        forecast = forecast.set_index("ds")

        rows = []

        for step, target_date in enumerate(
            expected_dates,
            start=1,
        ):
            col = f"yhat{step}"

            if col not in forecast.columns:
                raise ValueError(
                    f"No aparece la columna {col}."
                )

            if target_date not in forecast.index:
                raise ValueError(
                    f"No aparece la fecha {target_date}."
                )

            value = forecast.loc[target_date, col]

            if not np.isscalar(value) or not np.isfinite(value):
                raise ValueError(
                    f"Predicción no válida para "
                    f"{target_date}, {col}: {value}"
                )

            rows.append({
                "ds": target_date,
                "horizonte_dias": step,
                "prediccion": float(value),
            })

        return pd.DataFrame(rows)

    # ============================================================
    # 13. Métricas y evaluación
    # ============================================================

    def calcular_metricas(real, pred):
        real = np.asarray(real, dtype=float)
        pred = np.asarray(pred, dtype=float)

        return {
            "mae": float(np.mean(np.abs(real - pred))),
            "rmse": float(
                np.sqrt(np.mean((real - pred) ** 2))
            ),
        }


    def evaluar_bloque(history, target, params):
        model = crear_modelo(params)

        model.fit(
            history,
            freq=FREQ,
        )

        pred = predecir_desde_origen(model, history)

        comparison = target.merge(
            pred,
            on="ds",
            how="left",
            validate="one_to_one",
        )

        if (
            len(comparison) != HORIZON
            or comparison["prediccion"].isna().any()
        ):
            raise ValueError(
                "El bloque de evaluación no tiene "
                "las siete predicciones esperadas."
            )

        metrics = calcular_metricas(
            comparison["y"],
            comparison["prediccion"],
        )

        return model, comparison, metrics

    # ============================================================
    # 14. Optimización con Optuna
    # ============================================================

    def buscar_parametros(train, validation):
        def objective(trial):
            params = {
                "n_lags": trial.suggest_categorical(
                    "n_lags",
                    [7, 14, 21],
                ),
                "n_changepoints": trial.suggest_int(
                    "n_changepoints",
                    0,
                    8,
                ),
                "learning_rate": trial.suggest_float(
                    "learning_rate",
                    0.001,
                    0.03,
                    log=True,
                ),
                "ar_reg": trial.suggest_float(
                    "ar_reg",
                    0.001,
                    1.0,
                    log=True,
                ),
                "epochs": 100,
            }

            _, _, metrics = evaluar_bloque(
                train,
                validation,
                params,
            )

            return metrics["mae"]

        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.TPESampler(seed=42),
        )

        study.optimize(
            objective,
            n_trials=N_TRIALS,
        )

        return {
            **BASE_PARAMS,
            **study.best_params,
        }

    # ============================================================
    # 15. Entrenar y predecir las cinco verticales por distrito
    #    15.1 Comprueba cada serie.
    #    15.2 Descarta las que no tienen histórico suficiente.
    #    15.3 Trata explícitamente las constantes.
    #    15.4 Evalúa NeuralProphet.
    #    15.5 Lo compara con repetir el último valor observado.
    #    15.6 Reentrena con todo el histórico.
    #    15.7 Genera siete predicciones futuras.
    # ============================================================

    import warnings

    # Silenciar únicamente este aviso de concatenación de NeuralProphet.
    warnings.filterwarnings(
        action="ignore",
        message=(
            r"The behavior of DataFrame concatenation "
            r"with empty or all-NA entries is deprecated.*"
        ),
        category=FutureWarning,
        module=r"neuralprophet\.data\.split",
        append=False,
    )

    resultados = []
    evaluaciones = []
    estados = []
    comparaciones_test = []

    parametros_por_serie = {}

    generated_at = pd.Timestamp.now(tz="UTC")

    for (district, vertical), group in long_df.groupby(
        ["entityid", "vertical"],
        sort=True,
    ):
        logger.info(
            "Procesando distrito=%s vertical=%s",
            district,
            vertical,
        )

        serie, discarded = preparar_serie(group)

        estado_base = {
            "entityid": district,
            "vertical": vertical,
            "puntos_utilizados": len(serie),
            "puntos_descartados_por_huecos": discarded,
        }

        if serie.empty:
            estados.append({
                **estado_base,
                "estado": "sin_datos",
            })
            continue

        origin = serie["ds"].max()

        estado_base["origen_prediccion"] = origin

        if len(serie) < MIN_TOTAL_POINTS:
            estados.append({
                **estado_base,
                "estado": "historico_insuficiente",
            })
            continue

        try:
            train = serie.iloc[
                :-(VALIDATION_DAYS + TEST_DAYS)
            ].copy()

            validation = serie.iloc[
                -(VALIDATION_DAYS + TEST_DAYS):-TEST_DAYS
            ].copy()

            train_plus_validation = serie.iloc[
                :-TEST_DAYS
            ].copy()

            test = serie.iloc[-TEST_DAYS:].copy()

            if serie["y"].nunique() == 1:
                value = float(serie["y"].iloc[-1])

                future_pred = pd.DataFrame({
                    "ds": pd.date_range(
                        origin + pd.Timedelta(days=1),
                        periods=HORIZON,
                        freq=FREQ,
                    ),
                    "horizonte_dias": range(1, HORIZON + 1),
                    "prediccion": value,
                })

                method = "persistencia_serie_constante"

                evaluaciones.append({
                    "entityid": district,
                    "vertical": vertical,
                    "metodo": method,
                    "mae_test": 0.0,
                    "rmse_test": 0.0,
                    "mae_persistencia": 0.0,
                    "mejora_mae_pct": np.nan,
                })

            else:
                # Evitar un ajuste autorregresivo sobre un bloque
                # de entrenamiento completamente constante.
                if train["y"].nunique() < 2:
                    estados.append({
                        **estado_base,
                        "estado": "entrenamiento_sin_variabilidad",
                    })
                    continue

                params = (
                    buscar_parametros(train, validation)
                    if USE_OPTUNA
                    else BASE_PARAMS.copy()
                )

                parametros_por_serie[
                    f"{district}|{vertical}"
                ] = params

                _, comparison, test_metrics = evaluar_bloque(
                    train_plus_validation,
                    test,
                    params,
                )

                baseline = np.repeat(
                    float(train_plus_validation["y"].iloc[-1]),
                    len(test),
                )

                baseline_metrics = calcular_metricas(
                    test["y"],
                    baseline,
                )

                baseline_mae = baseline_metrics["mae"]

                improvement = (
                    100 * (
                        baseline_mae - test_metrics["mae"]
                    ) / baseline_mae
                    if baseline_mae > 0
                    else np.nan
                )

                comparison["persistencia"] = baseline
                comparison["entityid"] = district
                comparison["vertical"] = vertical

                comparaciones_test.append(comparison)

                evaluaciones.append({
                    "entityid": district,
                    "vertical": vertical,
                    "metodo": "NeuralProphet",
                    "mae_test": test_metrics["mae"],
                    "rmse_test": test_metrics["rmse"],
                    "mae_persistencia": baseline_mae,
                    "mejora_mae_pct": improvement,
                })

                final_model = crear_modelo(params)

                final_model.fit(
                    serie,
                    freq=FREQ,
                )

                future_pred = predecir_desde_origen(
                    final_model,
                    serie,
                )

                method = "NeuralProphet"

            future_pred["entityid"] = district
            future_pred["vertical"] = vertical
            future_pred["metodo"] = method
            future_pred["origen_prediccion"] = origin
            future_pred["generado_en"] = generated_at

            resultados.append(future_pred)

            estados.append({
                **estado_base,
                "estado": "ok",
                "metodo": method,
            })

        except Exception as exc:
            logger.exception(
                "Error en %s / %s",
                district,
                vertical,
            )

            estados.append({
                **estado_base,
                "estado": "error",
                "detalle": str(exc),
            })

    estados_df = pd.DataFrame(estados)
    evaluacion_df = pd.DataFrame(evaluaciones)

    predicciones = (
        pd.concat(resultados, ignore_index=True)
        if resultados
        else pd.DataFrame()
    )

    test_df = (
        pd.concat(comparaciones_test, ignore_index=True)
        if comparaciones_test
        else pd.DataFrame()
    )

    display(estados_df)
    display(evaluacion_df)
    display(predicciones.head(15))

    # ============================================================
    #  16. Resumen de la evaluación
    # ============================================================

    if not evaluacion_df.empty:
        display(
            evaluacion_df.sort_values(
                ["vertical", "mae_test"]
            )
        )

        neural_results = evaluacion_df[
            evaluacion_df["metodo"].eq("NeuralProphet")
        ]

        if not neural_results.empty:
            resumen_evaluacion = (
                neural_results.groupby("vertical")
                .agg(
                    series_evaluadas=("entityid", "count"),
                    mae_medio=("mae_test", "mean"),
                    rmse_medio=("rmse_test", "mean"),
                    mae_persistencia_medio=(
                        "mae_persistencia",
                        "mean",
                    ),
                )
            )

            display(resumen_evaluacion)

    # ============================================================
    #  19. Control de valores fuera de rango
    # ============================================================

    if not predicciones.empty:
        predicciones["fuera_de_rango"] = False

        if ISD_BOUNDS is not None:
            lower, upper = ISD_BOUNDS

            predicciones["fuera_de_rango"] = (
                ~predicciones["prediccion"].between(
                    lower,
                    upper,
                )
            )

            display(
                predicciones[
                    predicciones["fuera_de_rango"]
                ]
            )

    # ============================================================
    #  20. Formato ancho con las cinco verticales
    # ============================================================

    if not predicciones.empty:
        # No combinar como si procedieran de una misma ejecución
        # verticales cuyo último día observado es diferente.
        origenes_por_distrito = (
            predicciones.groupby("entityid")
            ["origen_prediccion"]
            .nunique()
        )

        distritos_alineados = origenes_por_distrito[
            origenes_por_distrito.eq(1)
        ].index

        aligned = predicciones[
            predicciones["entityid"].isin(
                distritos_alineados
            )
        ].copy()

        if not aligned.empty:
            predicciones_wide = (
                aligned.pivot(
                    index=["entityid", "ds"],
                    columns="vertical",
                    values="prediccion",
                )
                .reindex(columns=VERTICALES)
                .reset_index()
            )

            predicciones_wide.columns.name = None

            predicciones_wide = (
                predicciones_wide.rename(
                    columns={"ds": "dateobserved"}
                )
            )

            predicciones_wide["verticales_disponibles"] = (
                predicciones_wide[VERTICALES]
                .notna()
                .sum(axis=1)
            )

            display(predicciones_wide.head(20))

        else:
            predicciones_wide = pd.DataFrame()

        display(
            origenes_por_distrito[
                origenes_por_distrito.gt(1)
            ].rename("origenes_temporales_distintos")
        )

    else:
        predicciones_wide = pd.DataFrame()

    if not predicciones_wide.empty:
        predicciones_wide["dateobserved"] = (
            pd.to_datetime(
                predicciones_wide["dateobserved"]
            )
            .dt.tz_localize(TIMEZONE)
            .dt.tz_convert("UTC")
        )

    # ============================================================
    #  21. Guardar resultados y evidencias
    # ============================================================

    estados_df.to_csv(
        OUTPUT_DIR / "estado_series.csv",
        index=False,
    )

    evaluacion_df.to_csv(
        OUTPUT_DIR / "evaluacion_modelos.csv",
        index=False,
    )

    if not predicciones.empty:
        predicciones.to_csv(
            OUTPUT_DIR / "predicciones_isd_detalle.csv",
            index=False,
        )

    if not predicciones_wide.empty:
        predicciones_wide.to_csv(
            OUTPUT_DIR / "predicciones_isd_verticales.csv",
            index=False,
        )

    if not test_df.empty:
        test_df.to_csv(
            OUTPUT_DIR / "comparacion_test.csv",
            index=False,
        )

    with open(
        OUTPUT_DIR / "parametros_modelos.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            parametros_por_serie,
            f,
            indent=2,
            ensure_ascii=False,
        )

    configuracion = {
        "frecuencia": FREQ,
        "horizonte": HORIZON,
        "zona_horaria_agregacion": TIMEZONE,
        "service_path": SERVICE_PATH,
        "entity_type": ENTITY_TYPE,
        "aggregation_level": AGGREGATION_LEVEL,
        "min_train_points": MIN_TRAIN_POINTS,
        "optuna": USE_OPTUNA,
        "generado_en": generated_at.isoformat(),
    }

    with open(
        OUTPUT_DIR / "configuracion_experimento.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            configuracion,
            f,
            indent=2,
            ensure_ascii=False,
        )
    if predicciones_wide.empty:
        raise RuntimeError("No hay predicciones alineadas para persistir; revisar estado_series.csv.")

if __name__ == "__main__":
    main()
