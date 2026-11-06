"""Validación y carga explícita de un lote exportado."""
import argparse

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directorio", help="Directorio de un único lote exportado")
    parser.add_argument("--confirmar", action="store_true", help="Insertar realmente en PostgreSQL")
    args = parser.parse_args()
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
    #  22. Persistencia de las predicciones exportadas en PostgreSQL.
    # ============================================================

    import json
    from pathlib import Path
    from decimal import Decimal

    import numpy as np
    import pandas as pd
    from sqlalchemy import MetaData, Table, func, select
    from sqlalchemy.dialects.postgresql import insert
    from IPython.display import display

    DIRECTORIO = Path(args.directorio)
    EJECUTAR_INSERCION = args.confirmar

    VERTICALES_DB = [
        "isdairquality",
        "isdnoiselevel",
        "isdcrowdflow",
        "isdenergyconsumption",
        "isdwaterquality",
    ]

    with (DIRECTORIO / "configuracion_experimento.json").open(
        encoding="utf-8"
    ) as fichero:
        config_carga = json.load(fichero)

    wide = pd.read_csv(
        DIRECTORIO / "predicciones_isd_verticales.csv",
        dtype={"entityid": "string"},
    )
    detalle = pd.read_csv(
        DIRECTORIO / "predicciones_isd_detalle.csv",
        dtype={"entityid": "string", "vertical": "string"},
    )

    requeridas_wide = {"entityid", "dateobserved", *VERTICALES_DB}
    requeridas_detalle = {
        "entityid", "vertical", "ds", "prediccion",
        "metodo", "origen_prediccion", "horizonte_dias", "generado_en",
    }

    for nombre, df, requeridas in [
        ("predicciones_isd_verticales.csv", wide, requeridas_wide),
        ("predicciones_isd_detalle.csv", detalle, requeridas_detalle),
    ]:
        faltantes = requeridas - set(df.columns)
        if faltantes:
            raise ValueError(f"{nombre}: faltan columnas {sorted(faltantes)}")
        if df.empty:
            raise ValueError(f"{nombre} está vacío.")
        if df["entityid"].isna().any() or df["entityid"].str.strip().eq("").any():
            raise ValueError(f"{nombre}: hay identificadores de distrito vacíos.")

    if config_carga["aggregation_level"] != "day" or config_carga["frecuencia"] != "D":
        raise ValueError("Esta celda está preparada para predicciones diarias.")

    zona = config_carga["zona_horaria_agregacion"]
    service_path = config_carga["service_path"]

    if not isinstance(service_path, str) or not service_path or len(service_path) > 100:
        raise ValueError("service_path no válido.")

    if wide["entityid"].str.len().gt(255).any():
        raise ValueError("Hay identificadores que superan los 255 caracteres.")

    wide["dateobserved"] = pd.to_datetime(
        wide["dateobserved"], utc=True, errors="raise"
    )

    # ds y origen_prediccion son fechas locales sin zona en el CSV de detalle.
    detalle["ds"] = pd.to_datetime(detalle["ds"], errors="raise")
    detalle["origen_prediccion"] = pd.to_datetime(
        detalle["origen_prediccion"], errors="raise"
    )
    detalle["fecha_objetivo_utc"] = (
        detalle["ds"].dt.tz_localize(
            zona, ambiguous="raise", nonexistent="raise"
        ).dt.tz_convert("UTC")
    )
    detalle["generado_en"] = pd.to_datetime(
        detalle["generado_en"], utc=True, errors="raise"
    )

    fechas = [
        wide["dateobserved"],
        detalle["ds"],
        detalle["origen_prediccion"],
        detalle["generado_en"],
    ]
    if any(serie.isna().any() for serie in fechas):
        raise ValueError("Hay fechas vacías en los ficheros.")

    generaciones = detalle["generado_en"].drop_duplicates()
    if len(generaciones) != 1:
        raise ValueError("El detalle contiene más de un lote de generación.")

    generado = generaciones.iloc[0]
    if generado != pd.to_datetime(config_carga["generado_en"], utc=True):
        raise ValueError("La configuración y el detalle pertenecen a lotes distintos.")

    # timestamp sin zona: convención explícita UTC.
    recvtime_lote = generado.tz_convert("UTC").tz_localize(None).to_pydatetime()

    if wide.duplicated(["entityid", "dateobserved"]).any():
        raise ValueError("Hay duplicados por distrito y fecha en el CSV ancho.")

    if detalle.duplicated(["entityid", "fecha_objetivo_utc", "vertical"]).any():
        raise ValueError("Hay predicciones duplicadas en el CSV de detalle.")

    if not detalle["vertical"].isin(VERTICALES_DB).all():
        raise ValueError("El detalle contiene verticales desconocidas.")

    for columna in VERTICALES_DB:
        wide[columna] = pd.to_numeric(wide[columna], errors="raise")
        if np.isinf(wide[columna].to_numpy(dtype=float)).any():
            raise ValueError(f"{columna}: hay valores infinitos.")

    detalle["prediccion"] = pd.to_numeric(detalle["prediccion"], errors="raise")
    if not np.isfinite(detalle["prediccion"].to_numpy(dtype=float)).all():
        raise ValueError("El detalle contiene predicciones no finitas.")

    # Se comprueba que cada valor que se insertará tiene su detalle correspondiente.
    comprobacion = (
        wide.melt(
            id_vars=["entityid", "dateobserved"],
            value_vars=VERTICALES_DB,
            var_name="vertical",
            value_name="valor_csv",
        )
        .dropna(subset=["valor_csv"])
        .merge(
            detalle,
            left_on=["entityid", "dateobserved", "vertical"],
            right_on=["entityid", "fecha_objetivo_utc", "vertical"],
            how="left",
            validate="one_to_one",
            indicator=True,
        )
    )

    if not comprobacion["_merge"].eq("both").all():
        raise ValueError("Hay valores sin detalle asociado.")

    if not np.allclose(
        comprobacion["valor_csv"], comprobacion["prediccion"],
        rtol=1e-9, atol=1e-12,
    ):
        raise ValueError("Los valores de ambos CSV no coinciden.")

    origenes = comprobacion.groupby("entityid")["origen_prediccion"].nunique()
    if origenes.gt(1).any():
        raise ValueError("Hay distritos con orígenes temporales no alineados.")

    n_disponibles = wide[VERTICALES_DB].notna().sum(axis=1)
    if n_disponibles.eq(0).any():
        raise ValueError("Hay filas sin ninguna predicción disponible.")

    if "verticales_disponibles" in wide:
        declaradas = pd.to_numeric(
            wide["verticales_disponibles"], errors="raise"
        )
        if not declaradas.eq(n_disponibles).all():
            raise ValueError("El número declarado de verticales no coincide.")

    # Se conservan las salidas originales, sin recortarlas automáticamente.
    fuera_01 = ((wide[VERTICALES_DB] < 0) | (wide[VERTICALES_DB] > 1)).sum().sum()
    if fuera_01:
        print(
            f"Aviso: {int(fuera_01)} valores quedan fuera de [0, 1]. "
            "Se conservarán sin modificar."
        )

    indice_detalle = {
        (fila.entityid, fila.fecha_objetivo_utc, fila.vertical): fila
        for fila in comprobacion.itertuples(index=False)
    }

    registros = []
    for fila in wide.to_dict(orient="records"):
        registro = {
            "recvtime": recvtime_lote,
            "fiwareservicepath": service_path,
            "entityid": str(fila["entityid"]),
            "entitytype": "DistrictISDForecast",
            "dateobserved": fila["dateobserved"].to_pydatetime(),
            "aggregationlevel": config_carga["aggregation_level"],
            "dateobserved_md": json.dumps({
                "zonaHorariaAgregacion": zona,
                "generadoEn": generado.isoformat(),
            }, ensure_ascii=False),
        }

        for vertical in VERTICALES_DB:
            valor = fila[vertical]
            registro[vertical] = (
                None if pd.isna(valor) else Decimal(str(valor))
            )
            registro[f"{vertical}_md"] = None

            if pd.notna(valor):
                info = indice_detalle[
                    (fila["entityid"], fila["dateobserved"], vertical)
                ]
                registro[f"{vertical}_md"] = json.dumps({
                    "metodo": str(info.metodo),
                    "origenPrediccion": info.origen_prediccion.isoformat(),
                    "horizonteDias": int(info.horizonte_dias),
                    "generadoEn": generado.isoformat(),
                }, ensure_ascii=False, allow_nan=False)

        registros.append(registro)

    # Reflejar la tabla existente: no crear ni reemplazar su estructura.
    tabla_forecast = Table(
        "isd_districtisdforecast",
        MetaData(),
        schema="madrid",
        autoload_with=engine,
    )

    # Completar explícitamente con NULL las columnas no generadas.
    registros = [
        {columna.name: registro.get(columna.name) for columna in tabla_forecast.columns}
        for registro in registros
    ]

    print(
        f"Lote: {generado.isoformat()}\n"
        f"Filas preparadas: {len(registros)}\n"
        f"Distritos: {wide['entityid'].nunique()}\n"
        f"Destino: madrid.isd_districtisdforecast"
    )
    display(pd.DataFrame(registros).head())

    if EJECUTAR_INSERCION:
        sentencia = (
            insert(tabla_forecast)
            .values(registros)
            .on_conflict_do_nothing(
                index_elements=["entityid", "dateobserved", "recvtime"]
            )
            .returning(tabla_forecast.c.entityid)
        )

        # Una transacción: si falla la carga, se revierte íntegramente.
        with engine.begin() as conexion:
            insertadas = len(conexion.execute(sentencia).fetchall())
            total_lote = conexion.scalar(
                select(func.count())
                .select_from(tabla_forecast)
                .where(
                    tabla_forecast.c.recvtime == recvtime_lote,
                    tabla_forecast.c.fiwareservicepath == service_path,
                    tabla_forecast.c.entitytype == "DistrictISDForecast",
                )
            )

        print(
            f"Insertadas: {insertadas}\n"
            f"Omitidas por clave existente: {len(registros) - insertadas}\n"
            f"Total almacenado para este lote y ámbito: {total_lote}"
        )
    else:
        print(
            "Solo vista previa. Para insertar, establece "
            "EJECUTAR_INSERCION = True y vuelve a ejecutar esta celda."
        )

if __name__ == "__main__":
    main()
