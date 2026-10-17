"""
data_processor.py  (v2 - procesador genérico de Excel / CSV)
=============================================================

Lee CUALQUIER conjunto de archivos tabulares (.xlsx, .xlsm, .xls, .xlsb, .ods, .csv, .tsv),
descubre solo dónde están las tablas, infiere el tipo de cada columna, reconoce qué significa
cada columna (contenedor, ETA, buque, ruptura...) y cruza todo por contenedor.

Qué hace distinto a la v1
-------------------------
* NO depende de nombres de archivo, de hoja ni de columnas exactas. Detecta la fila de
  encabezado, las tablas lado a lado (varias en la misma hoja) y las tablas apiladas.
* Lee TODAS las hojas de TODOS los archivos (la v1 solo leía la primera hoja de Tracking y DIEL).
* Conserva TODAS las columnas de cada archivo (la v1 solo conservaba ~15 columnas del Tracking).
* Convierte tipos automáticamente (fechas, números, booleanos, texto), tolera "#N/D",
  "(en blanco)", "TBC", fechas 31/12/1899, fórmulas sin valor en caché, etc.
* Reconoce el rol de cada columna por nombre (sinónimos/tokens) y por contenido
  (p. ej. una columna cuyos valores parecen contenedores ISO 6346 es el identificador).
* Elige solo la tabla "maestra" (la más completa en ETA/buque/ETD) y trata las demás como apoyo.
* Descarta automáticamente hojas sin contenedores en común con la maestra (históricos).
* Mantiene la API anterior: process_real_tracking_dataframe, process_real_tracking_data,
  load_and_clean_excel y las columnas que usa el modelo (id, eta_dia, need_by_dia, family, vessel...).

Uso rápido
----------
    from data_processor import build_dataset, profile_sources

    # 1) Ver qué encontró en cada archivo/hoja (sin cruzar nada)
    print(profile_sources("Tracking.xlsx", "Programación_DIEL.xlsx", "Prioridades_CKD.xlsm"))

    # 2) Procesar todo (acepta rutas, carpetas, BytesIO, archivos subidos de Streamlit...)
    bundle = build_dataset(["Tracking.xlsx", "Programación_DIEL.xlsx", "Prioridades_CKD.xlsm"])
    bundle.master          # DataFrame: una fila por contenedor con TODA la información
    bundle.tables          # cada tabla limpia y tipada, tal cual viene en el archivo
    bundle.profile         # resumen de lo detectado
    bundle.containers()    # lista de Container para el modelo
    bundle.to_excel("consolidado.xlsx")

    # 3) Compatibilidad con la v1
    df = process_real_tracking_dataframe(tracking, diel, prio)
    containers = process_real_tracking_data(tracking, diel, prio)

Por línea de comandos:
    python data_processor.py archivo1.xlsx archivo2.csv carpeta/ --out consolidado.xlsx
"""
from __future__ import annotations

import csv
import io
import logging
import math
import os
import re
import unicodedata
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

try:  # el modelo real del proyecto
    from src.model import Container, Params  # noqa: F401  (Params se re-exporta por compatibilidad)
except ImportError:  # pragma: no cover - permite usar el módulo de forma independiente
    @dataclass
    class Container:  # type: ignore[no-redef]
        id: str
        eta: int
        need_by: int
        part_family: str = "GEN"
        vessel: str = "BUQUE_GEN"

    @dataclass
    class Params:  # type: ignore[no-redef]
        pass

logger = logging.getLogger(__name__)

FileSource = Union[str, "os.PathLike[str]", bytes, Any]  # ruta, carpeta, bytes o archivo subido

SUPPORTED_EXT = (".xlsx", ".xlsm", ".xltx", ".xltm", ".xls", ".xlsb", ".ods", ".csv", ".tsv", ".txt")

# Compatibilidad v1: antes se limitaba a estas hojas de Prioridades. Ahora es automático
# (se descartan hojas sin contenedores en común con la maestra); se conserva por si algún
# código externo la importa o quiere forzar hojas concretas con prio_sheets=.
DEFAULT_PRIO_SHEETS = ("TD", "Seguimiento PNC")


# =============================================================================
# 1. CONFIGURACIÓN: qué significa cada columna
# =============================================================================
# exact  : nombres exactos (normalizados) en orden de prioridad; si hay varios se hace
#          "coalesce" en ese orden (p. ej. ETA REAL -> ETA VTT -> ETA INICIAL).
# tokens : palabras que, si aparecen en el nombre, sugieren el rol (después de los exactos).
# exclude: palabras que descartan el rol aunque haya coincidencia de tokens.
# dtype  : tipo de dato que debe tener la columna ('date' | 'text').
ROLE_SPEC: Dict[str, Dict[str, Any]] = {
    "container": dict(
        exact=["CONTENEDOR", "CONTAINER", "CONT/RAN", "CONT", "NUM CONTENEDOR", "NO CONTENEDOR",
               "N CONTENEDOR", "CNTR", "CONTENEDORES", "CONTAINER NO", "CONTAINER NUMBER"],
        tokens=["CONTENEDOR", "CONTAINER", "CONT", "CNTR"], dtype="text"),
    "eta": dict(
        exact=["ETA REAL", "ETA VTT", "ETA INICIAL", "ETA BUQUE", "ETA PUERTO", "ETA"],
        tokens=["ETA"], exclude=["CRITICA", "TXT", "DELTA", "SEMANA", "TTO", "VS"], dtype="date"),
    "etd": dict(
        exact=["ETD REAL", "ETD INICIAL", "ETD"],
        tokens=["ETD"], exclude=["TXT", "DELTA", "SEMANA", "ATRASO"], dtype="date"),
    "vessel": dict(
        exact=["BUQUE LLEGADA REAL", "BUQUE LLEGADA INICIAL", "BUQUE", "VESSEL", "NAVE", "BARCO"],
        tokens=["BUQUE", "VESSEL", "NAVE", "BARCO"], exclude=["SALIDA", "SAP", "ETA"], dtype="text"),
    "family": dict(
        exact=["SOURCING", "PART FAMILY", "FAMILIA", "FAMILY"],
        tokens=["FAMILIA", "FAMILY", "SOURCING"], dtype="text"),
    "origin": dict(
        exact=["ORIGEN", "ORIGIN", "PAIS ORIGEN", "COUNTRY OF ORIGIN", "SUPPLIER COUNTRY", "PAIS", "COUNTRY"],
        tokens=["ORIGEN", "ORIGIN", "COUNTRY", "PAIS"], exclude=["DESTINO", "DESTINATION", "DEST"], dtype="text"),
    "ruptura": dict(
        exact=["RUPTURA", "FECHA RUPTURA", "NEED BY", "FECHA NECESIDAD", "FECHA REQUERIDA"],
        tokens=["RUPTURA", "NEED"], exclude=["DIAS", "VS"], dtype="date"),
    "em": dict(
        exact=["EM DIEL", "EM PROG", "FECHA EM PROG", "FECHA EM PLAN", "EM"],
        tokens=["EM"], exclude=["DIAS", "VS"], dtype="date"),
    "status": dict(
        exact=["STATUS", "ESTADO"], tokens=["STATUS", "ESTADO"], exclude=["ATRASO"], dtype="text"),
    "reference": dict(
        exact=["REFERENCIA", "REF", "PART NUMBER", "NUMERO DE PARTE", "SKU", "MATERIAL"],
        tokens=["REFERENCIA", "SKU"], dtype="text"),
    "comment": dict(
        exact=["COMENTARIO", "COMENTARIOS", "OBSERVACIONES", "OBSERVACION", "NOTAS"],
        tokens=["COMENTARIO", "OBSERVACIONES", "OBSERVACION", "NOTAS"], dtype="text"),
}

# Valores que Excel/los usuarios ponen cuando NO hay dato.
NULL_TOKENS = {
    "", "NAN", "NONE", "NULL", "NAT", "<NA>", "-", "--", "N/A", "#N/A", "#N/D", "#N/A N/A",
    "#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#NUM!", "#NULL!", "#¡REF!", "#¡VALOR!",
    "#¡DIV/0!", "#¿NOMBRE?", "#¡NUM!", "(EN BLANCO)", "(BLANK)", "(BLANKS)",
}

_ID_ISO = re.compile(r"^[A-Z]{4}\d{7}$")                       # contenedor ISO 6346
_ID_LOOSE = re.compile(r"^(?=.*\d)[A-Z0-9]{5,16}$")            # códigos tipo RAN, BL, etc.
_DATE_STR = re.compile(
    r"^\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}(\s+\d{1,2}:\d{2}(:\d{2})?)?$"
    r"|^\d{4}[/\-]\d{1,2}[/\-]\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?)?$")
_NUM_STR = re.compile(r"^[\-+]?(\d{1,3}([.,]\d{3})+|\d+)([.,]\d+)?\s*%?$")
_DATE_HINT = re.compile(r"(FECHA|\bFEC\b|\bETA\b|\bETD\b|RUPTURA|DATE|LLEGADA|SALIDA|VENCIM|\bEM\b|PROG|NEED)")
_CODE_NAME = re.compile(
    r"(REFERENCIA|\bREF\b|CODIGO|\bCOD\b|\bCONT\b|CONTENEDOR|CONTAINER|\bID\b|PROVEEDOR|\bTGP\b|"
    r"PEDIDO|ORDEN|FACTURA|\bASN\b|\bNIT\b|SKU|\bPARTE\b|PART NUMBER|MATERIAL|LOTE|\bBL\b|DOCUMENTO)")
_NUMLIKE = re.compile(r"^[\-+]?\d+([.,]\d+)?%?$")
_RESERVED = {"id", "fila_origen", "hoja"}
_STOP_TAG_WORDS = {"programacion", "archivo", "reporte", "informe", "datos", "data", "base", "copia",
                   "final", "nuevo", "version", "xlsx", "xlsm", "csv", "hoja"}


# =============================================================================
# 2. UTILIDADES BÁSICAS
# =============================================================================
def _norm(x: Any) -> str:
    """MAYÚSCULAS, sin tildes, espacios/saltos de línea colapsados."""
    s = unicodedata.normalize("NFKD", str(x))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip().upper()


def _snake(x: Any) -> str:
    """'ETA Real ' -> 'eta_real', 'FECHA EM\\nPLAN' -> 'fecha_em_plan'."""
    s = _norm(x).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if not s:
        return "col"
    return f"c_{s}" if s[0].isdigit() else s


def _col_letter(i: int) -> str:
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _fmt_val(v: Any) -> str:
    """Texto limpio para cualquier valor (2299.0 -> '2299', Timestamp -> '2026-10-06')."""
    if isinstance(v, (pd.Timestamp, datetime)):
        ts = pd.Timestamp(v)
        return ts.strftime("%Y-%m-%d") if ts == ts.normalize() else ts.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (float, np.floating)) and float(v).is_integer():
        return str(int(v))
    return str(v).strip()


def _rewind(src: Any) -> None:
    if hasattr(src, "seek"):
        try:
            src.seek(0)
        except Exception:  # noqa: BLE001
            pass


def _clean_cell(v: Any) -> Any:
    """Celda cruda -> valor limpio o NaN (texto vacío, errores de Excel, fórmulas sin valor...)."""
    if v is None:
        return np.nan
    if isinstance(v, str):
        s = v.strip()
        if not s or s.startswith("=") or s.upper() in NULL_TOKENS:
            return np.nan
        return s
    try:
        if pd.isna(v):
            return np.nan
    except (TypeError, ValueError):
        pass
    return v


def _parse_date(v: Any) -> pd.Timestamp:
    """Fecha desde datetime, serial de Excel o texto d/m/Y. 'TBC', 'ATRASO', 31/12/1899... -> NaT."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return pd.NaT
    if isinstance(v, (pd.Timestamp, datetime, date)):
        ts = pd.Timestamp(v)
    elif isinstance(v, (bool, np.bool_)):
        return pd.NaT
    elif isinstance(v, (int, float, np.integer, np.floating)):
        if not 20000 <= float(v) <= 80000:          # no es un serial de fecha (p. ej. flag 1.0)
            return pd.NaT
        ts = pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(v))
    else:
        s = str(v).strip()
        if not s or not re.search(r"\d", s):
            return pd.NaT
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ts = pd.to_datetime(s, dayfirst=True, errors="coerce")
    if pd.isna(ts) or ts.year < 2000:               # descarta 31/12/1899 y similares
        return pd.NaT
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.normalize()


def _to_dt(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.map(_parse_date), errors="coerce")


def _to_num(v: Any) -> float:
    if isinstance(v, (bool, np.bool_)):
        return np.nan
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace("%", "").replace(" ", "")
        if not s:
            return np.nan
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        elif "," in s:
            s = s.replace(",", "") if re.fullmatch(r"[\-+]?\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
        elif re.fullmatch(r"[\-+]?\d{1,3}(\.\d{3})+", s):
            s = s.replace(".", "")
        try:
            return float(s)
        except ValueError:
            return np.nan
    return np.nan


def _value_kind(v: Any) -> Optional[str]:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (bool, np.bool_)):
        return "bool"
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return "dt"
    if isinstance(v, (int, float, np.integer, np.floating)):
        return "num"
    if isinstance(v, str):
        if _DATE_STR.match(v):
            return "dstr"
        if _NUM_STR.match(v):
            return "numstr"
    return "text"


def _series_kind(s: pd.Series) -> str:
    """'date' | 'number' | 'bool' | 'text' según el dtype ya tipado."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date"
    if pd.api.types.is_bool_dtype(s):
        return "bool"
    if pd.api.types.is_numeric_dtype(s):
        return "number"
    return "text"


def _clean_id(s: pd.Series) -> pd.Series:
    out = s.astype("string").str.strip().str.upper()
    compact = out.str.replace(r"[\s\-.]", "", regex=True)
    is_iso = compact.str.match(_ID_ISO.pattern).fillna(False).astype(bool)
    out = out.where(~is_iso, compact)               # 'TGBU 507367-0' -> 'TGBU5073670'
    return out.where(~out.isin(["", "NAN", "NONE", "<NA>"]), other=pd.NA)


def _join_by_id(ids: pd.Series, values: pd.Series, order: Sequence[Any], cap: int = 5) -> pd.Series:
    """Une los valores únicos de texto por contenedor (rápido, sin groupby.agg con lambdas)."""
    acc: Dict[Any, List[str]] = {}
    for k, v in zip(ids.tolist(), values.tolist()):
        if v is None or v is pd.NA or (isinstance(v, float) and v != v):
            continue
        t = _fmt_val(v)
        lst = acc.setdefault(k, [])
        if t and t not in lst:
            lst.append(t)
    res = {k: (" | ".join(v[:cap]) + (f" (+{len(v) - cap})" if len(v) > cap else "")) for k, v in acc.items() if v}
    return pd.Series(res, dtype="string").reindex(list(order))


def _join_unique(s: pd.Series, cap: int = 5) -> Any:
    vals: List[str] = []
    for v in s.dropna():
        t = _fmt_val(v)
        if t and t not in vals:
            vals.append(t)
    if not vals:
        return pd.NA
    extra = len(vals) - cap
    return " | ".join(vals[:cap]) + (f" (+{extra})" if extra > 0 else "")


# =============================================================================
# 3. LECTURA DE ARCHIVOS
# =============================================================================
@dataclass
class Source:
    """Un archivo de entrada. 'tag' = prefijo de sus columnas en el consolidado ('' = sin prefijo);
    'master=True' fuerza que sea la fuente maestra (de lo contrario se detecta sola)."""
    obj: Any
    tag: Optional[str] = None
    name: Optional[str] = None
    master: bool = False


def _name_of(obj: Any, idx: int) -> str:
    if isinstance(obj, (str, os.PathLike)):
        return os.path.basename(os.fspath(obj))
    n = getattr(obj, "name", None)
    return os.path.basename(str(n)) if n else f"archivo_{idx}"


def _expand_sources(sources: Any) -> List[Source]:
    items = list(sources) if isinstance(sources, (list, tuple)) else [sources]
    out: List[Source] = []
    for it in items:
        if it is None:
            continue
        s = it if isinstance(it, Source) else Source(it)
        o = s.obj
        if isinstance(o, (str, os.PathLike)) and os.path.isdir(o):
            dir_path = str(o)
            direct_files = [f for f in os.listdir(dir_path) if not f.startswith("~$") and f.lower().endswith(SUPPORTED_EXT)]
            if not direct_files:
                subdirs = sorted([os.path.join(dir_path, d) for d in os.listdir(dir_path) if os.path.isdir(os.path.join(dir_path, d))])
                subdirs = sorted(subdirs, key=lambda p: ("2nd" in p, p), reverse=True)
                for sub in subdirs:
                    if any(not f.startswith("~$") and f.lower().endswith(SUPPORTED_EXT) for f in os.listdir(sub)):
                        dir_path = sub
                        break
            for fn in sorted(os.listdir(dir_path)):
                if not fn.startswith(("~$", ".")) and fn.lower().endswith(SUPPORTED_EXT):
                    out.append(Source(os.path.join(dir_path, fn)))
            continue
        if isinstance(o, (bytes, bytearray)):
            s = Source(io.BytesIO(bytes(o)), s.tag, s.name, s.master)
        out.append(s)
    seen: Dict[str, int] = {}
    for i, s in enumerate(out, 1):
        nm = s.name or _name_of(s.obj, i)
        if nm in seen:
            seen[nm] += 1
            stem, ext = os.path.splitext(nm)
            nm = f"{stem}_{seen[nm]}{ext}"
        else:
            seen[nm] = 1
        s.name = nm
    return out


def _peek(obj: Any, n: int = 8) -> bytes:
    if isinstance(obj, (str, os.PathLike)):
        with open(obj, "rb") as fh:
            return fh.read(n)
    pos = obj.tell() if hasattr(obj, "tell") else 0
    head = obj.read(n)
    _rewind(obj)
    if hasattr(obj, "seek"):
        obj.seek(pos)
    return head if isinstance(head, bytes) else b""


def _read_text(obj: Any) -> str:
    if isinstance(obj, (str, os.PathLike)):
        with open(obj, "rb") as fh:
            data = fh.read()
    else:
        _rewind(obj)
        data = obj.read()
        data = data.encode("utf-8") if isinstance(data, str) else data
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _read_raw(obj: Any, name: str) -> Dict[str, pd.DataFrame]:
    """Lee TODAS las hojas sin encabezado y sin convertir tipos (una sola apertura del archivo)."""
    ext = os.path.splitext(name)[1].lower()
    head = _peek(obj)
    if ext == ".xlsb":
        engine = "pyxlsb"
    elif ext == ".ods":
        engine = "odf"
    elif head.startswith(b"\xd0\xcf\x11\xe0"):
        engine = "xlrd"
    elif head.startswith(b"PK"):
        engine = "openpyxl"
    else:
        engine = None

    if engine is None:                               # CSV / TSV / TXT
        text = _read_text(obj)
        if not text.strip():
            return {}
        try:
            dialect = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = max(",;\t|", key=lambda d: text[:5000].count(d))
        rows = list(csv.reader(io.StringIO(text), dialect))
        width = max((len(r) for r in rows), default=0)
        rows = [r + [""] * (width - len(r)) for r in rows]
        return {os.path.splitext(name)[0]: pd.DataFrame(rows, dtype=object)}

    _rewind(obj)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        xl = pd.ExcelFile(obj, engine=engine)
        return {sh: xl.parse(sh, header=None, dtype=object) for sh in xl.sheet_names}


# =============================================================================
# 4. DETECCIÓN DE TABLAS
# =============================================================================
@dataclass
class Table:
    """Una tabla detectada, limpia y tipada. Conserva TODAS las columnas no vacías."""
    file: str
    sheet: str
    label: str                                   # hoja, o hoja[k] si hay varias tablas en la hoja
    df: pd.DataFrame
    labels: Dict[str, str]                       # columna snake_case -> encabezado original
    norm: Dict[str, str]                         # columna snake_case -> encabezado normalizado
    dtypes: Dict[str, str]
    roles: Dict[str, List[str]]
    header_row: Optional[int]                    # fila de Excel (1-based)
    cell_range: str
    title: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    dropped_empty: List[str] = field(default_factory=list)
    block: int = 1
    status: str = ""                             # maestra | apoyo | omitida (...) | sin_id

    @property
    def has_id(self) -> bool:
        return "id" in self.df.columns

    @property
    def ids(self) -> set:
        return set(self.df["id"].dropna()) if self.has_id else set()

    @property
    def master_score(self) -> int:
        r = self.roles
        if not self.has_id or not (r.get("eta") or r.get("etd")):
            return 0
        return 3 * bool(r.get("eta")) + 2 * bool(r.get("vessel")) + bool(r.get("etd")) + bool(r.get("family"))


def _col_blocks(has_data: np.ndarray, max_gap: int = 1) -> List[Tuple[int, int]]:
    """Grupos de columnas contiguas; 2+ columnas vacías seguidas separan tablas lado a lado."""
    idx = np.flatnonzero(has_data)
    if idx.size == 0:
        return []
    blocks, start, prev = [], int(idx[0]), int(idx[0])
    for j in idx[1:]:
        if j - prev - 1 > max_gap:
            blocks.append((start, prev))
            start = int(j)
        prev = int(j)
    blocks.append((start, prev))
    return blocks


def _is_texty(v: Any) -> bool:
    return isinstance(v, str) and not _NUMLIKE.match(v) and not _DATE_STR.match(v)


def _find_header(sub: pd.DataFrame, scan: int = 60) -> Optional[int]:
    """Primera fila que parece encabezado: casi toda la tabla llena, casi todo texto y con datos debajo."""
    m = sub.notna().to_numpy()
    n = m.shape[0]
    if n < 2:
        return None
    active = (np.cumsum(m[::-1], axis=0)[::-1] > 0).sum(axis=1)   # columnas con datos desde la fila i
    for i in range(min(n - 1, scan)):
        filled = int(m[i].sum())
        if not filled:
            continue
        need = 1 if active[i] <= 1 else max(2, math.ceil(0.5 * active[i]))
        if filled < need:
            continue
        vals = sub.iloc[i][m[i]]
        if sum(_is_texty(v) for v in vals) < 0.8 * filled:
            continue
        if any(isinstance(v, str) and _ID_ISO.match(v.strip().upper()) for v in vals):
            continue                                  # es un dato (ID de contenedor), no un encabezado
        if not m[i + 1:].any():
            continue
        return i
    return None


def _body_extent(body: pd.DataFrame, gap: int = 5) -> Tuple[int, Optional[int]]:
    """Fin de la tabla (5+ filas vacías seguidas) y comienzo de una posible tabla apilada debajo."""
    m = body.notna().any(axis=1).to_numpy()
    last, empties = -1, 0
    for i, filled in enumerate(m):
        if filled:
            # un hueco grande solo separa tablas si lo que sigue arranca con un encabezado nuevo;
            # si no, son datos que continúan (hay hojas con bloques de filas separados por huecos).
            if empties >= gap and last >= 0 and _find_header(body.iloc[i:i + 80]) == 0:
                return last + 1, i
            last, empties = i, 0
        else:
            empties += 1
    return (last + 1 if last >= 0 else 0), None


def _coerce_column(label_norm: str, s: pd.Series) -> Tuple[pd.Series, str, Optional[pd.Series]]:
    """Infiere el tipo de una columna y la convierte. Devuelve (serie, tipo, bandera_de_texto|None)."""
    nn = s.dropna()
    n = len(nn)
    if n == 0:
        return s.astype("string"), "empty", None
    kinds_full = s.map(_value_kind)
    cnt = kinds_full.value_counts().to_dict()

    def c(*k: str) -> int:
        return sum(cnt.get(x, 0) for x in k)

    hint = bool(_DATE_HINT.search(label_norm))
    n_date = c("dt", "dstr")
    is_date = n_date / n >= 0.6 or (n_date >= 1 and hint and n_date / n >= 0.05)
    if not is_date and hint and c("num") / n >= 0.8:                 # serial de Excel sin formato
        v = pd.to_numeric(nn[kinds_full[nn.index] == "num"], errors="coerce")
        is_date = bool(len(v)) and bool(v.between(20000, 80000).all())
    if is_date:
        d = _to_dt(s)
        txt = s.where(kinds_full == "text").map(lambda v: _fmt_val(v) if pd.notna(v) else pd.NA).astype("string")
        return d, "date", (txt if txt.notna().any() else None)

    if not _CODE_NAME.search(label_norm) and c("num", "numstr") / n >= 0.9:
        nums = s.map(_to_num).astype("float64")
        v = nums.dropna()
        if len(v) and (v.abs() >= 1e8).mean() > 0.5 and (v % 1 == 0).all():
            pass                                                     # códigos largos: se dejan como texto
        elif len(v) and (v % 1 == 0).all() and (v.abs() < 1e15).all():
            return nums.astype("Int64"), "int", None
        else:
            return nums, "float", None
    if c("bool") == n:
        return s.astype("boolean"), "bool", None
    return s.map(lambda v: _fmt_val(v) if pd.notna(v) else pd.NA).astype("string"), "text", None


def _assign_roles(df: pd.DataFrame, norm: Mapping[str, str]) -> Dict[str, List[str]]:
    """Detecta qué columnas cumplen cada rol (por nombre y, para el contenedor, por contenido)."""
    cols = [c for c in df.columns if c not in _RESERVED and not c.endswith("_txt")]
    kind = {c: _series_kind(df[c]) for c in cols}
    toks = {c: set(re.split(r"[^A-Z0-9]+", norm.get(c, c.upper()))) - {""} for c in cols}
    roles: Dict[str, List[str]] = {}

    # --- contenedor: nombre + contenido -------------------------------------------------
    spec = ROLE_SPEC["container"]
    cands: List[Tuple[int, float, str]] = []
    for c in cols:
        if kind[c] != "text":
            continue
        vals = _clean_id(df[c]).dropna()
        iso = float(vals.str.match(_ID_ISO.pattern).mean()) if len(vals) else 0.0
        nm = norm.get(c, "")
        rank = spec["exact"].index(nm) if nm in spec["exact"] else (
            len(spec["exact"]) if toks[c] & set(spec["tokens"]) else None)
        if rank is not None and len(vals):
            cands.append((rank, -iso, c))
        elif iso >= 0.6:
            cands.append((len(spec["exact"]) + 1, -iso, c))
    if cands:
        roles["container"] = [sorted(cands)[0][2]]

    # --- resto de roles -------------------------------------------------------------------
    for role, sp in ROLE_SPEC.items():
        if role == "container":
            continue
        want = sp["dtype"]
        ok = [c for c in cols if kind[c] == want]
        found: List[str] = []
        for ex in sp["exact"]:
            found += [c for c in ok if norm.get(c) == ex and c not in found]
        for c in ok:
            if c not in found and toks[c] & set(sp["tokens"]) and not toks[c] & set(sp.get("exclude", ())):
                found.append(c)
        found = [c for c in found if c != (roles.get("container") or [None])[0]]
        if found:
            roles[role] = found
    return roles


def _build_table(raw: pd.DataFrame, file: str, sheet: str, top: int, h: int, body_start: int,
                 body_end: int, a: int, b: int, a_blk: int, b_blk: int) -> Optional[Table]:
    hdr = raw.iloc[h, a:b + 1] if h >= 0 else pd.Series([np.nan] * (b - a + 1))   # h=-1: sin encabezado
    body = raw.iloc[body_start:body_end, a:b + 1]

    keep, labels, dropped = [], [], []
    for k, j in enumerate(range(a, b + 1)):
        hv = hdr.iloc[k]
        if body.iloc[:, k].notna().any():
            labels.append(re.sub(r"\s+", " ", _fmt_val(hv)) if pd.notna(hv) else f"col_{_col_letter(j)}")
            keep.append(k)
        elif pd.notna(hv):
            dropped.append(re.sub(r"\s+", " ", _fmt_val(hv)))
    if not keep:
        return None

    names, used = [], {}
    for lb in labels:
        s = _snake(lb)
        if s in _RESERVED:
            s += "_src"
        used[s] = used.get(s, 0) + 1
        names.append(s if used[s] == 1 else f"{s}_{used[s]}")

    data = body.iloc[:, keep].copy()
    data.columns = names
    # filas que repiten el encabezado dentro del cuerpo (tablas pegadas una tras otra)
    ln = [_norm(x) for x in labels]
    cand = data.iloc[:, 0].map(lambda v: isinstance(v, str) and _norm(v) == ln[0])
    if cand.any():
        is_hdr = data[cand].apply(lambda r: sum(_norm(v) == l for v, l in zip(r.tolist(), ln) if pd.notna(v))
                                  >= max(2, 0.6 * len(ln)), axis=1)
        data = data.drop(index=is_hdr[is_hdr].index)
    if data.empty:
        return None
    excel_rows = (data.index + 1).to_numpy()

    typed: Dict[str, pd.Series] = {}
    dtypes: Dict[str, str] = {}
    for nm, lb in zip(names, ln):
        ser, dt, flag = _coerce_column(lb, data[nm])
        typed[nm], dtypes[nm] = ser, dt
        if flag is not None:
            typed[f"{nm}_txt"], dtypes[f"{nm}_txt"] = flag, "text"
    df = pd.DataFrame(typed, index=data.index).reset_index(drop=True)
    norm = dict(zip(names, ln))
    roles = _assign_roles(df, norm)
    if roles.get("container"):
        df.insert(0, "id", _clean_id(df[roles["container"][0]]))
    df["fila_origen"] = excel_rows

    # título y metadatos (filas encima del encabezado, dentro del bloque)
    title, meta = None, {}
    for r in range(h - 1, max(top, h - 7) - 1, -1):
        seg = raw.iloc[r, a:b + 1].dropna()
        if len(seg) == 1 and _is_texty(seg.iloc[0]) and title is None:
            title = _fmt_val(seg.iloc[0])
        row = raw.iloc[r, a_blk:b_blk + 1].dropna()
        if len(row) == 2 and _is_texty(row.iloc[0]):
            meta[_fmt_val(row.iloc[0])] = row.iloc[1]

    return Table(file=file, sheet=sheet, label=sheet, df=df, labels=dict(zip(names, labels)), norm=norm,
                 dtypes=dtypes, roles=roles, header_row=(h + 1 if h >= 0 else None),
                 cell_range=f"{_col_letter(a)}{max(h + 1, 1)}:{_col_letter(b)}{body_end}",
                 title=title, meta=meta, dropped_empty=dropped)


def _tables_in_block(raw: pd.DataFrame, file: str, sheet: str, a: int, b: int) -> List[Table]:
    out: List[Table] = []
    row = 0
    while row < len(raw):
        sub = raw.iloc[row:, a:b + 1]
        if not sub.notna().any().any():
            break
        hrel = _find_header(sub)
        if hrel is None:
            # sin encabezado reconocible: si es el primer bloque con 2+ filas, se toma como tabla sin encabezado
            if row == 0 and not out and int(sub.notna().any(axis=1).sum()) >= 2:
                h = -1
            else:
                break
        else:
            h = row + hrel
        body_end_rel, nxt = _body_extent(raw.iloc[h + 1:, a:b + 1])
        body_start, body_end = h + 1, h + 1 + body_end_rel

        # varias tablas lado a lado pegadas: el primer encabezado se repite en la misma fila
        if h >= 0:
            hdr = {j: _norm(v) for j, v in zip(range(a, b + 1), raw.iloc[h, a:b + 1]) if pd.notna(v)}
            first = hdr[min(hdr)]
            starts = [j for j, nm in hdr.items() if nm == first]
        else:
            starts = [a]
        edges = [a] + starts[1:] + [b + 1]
        for lo, hi in zip(edges[:-1], edges[1:]):
            t = _build_table(raw, file, sheet, row, h, body_start, body_end, lo, hi - 1, a, b)
            if t is not None:
                out.append(t)
        if nxt is None:
            break
        row = body_start + nxt
    return out


def _detect_tables(raw_sheet: pd.DataFrame, file: str, sheet: str) -> List[Table]:
    raw = raw_sheet.apply(lambda col: col.map(_clean_cell)).reset_index(drop=True)
    raw.columns = range(raw.shape[1])
    tables: List[Table] = []
    for a, b in _col_blocks(raw.notna().any(axis=0).to_numpy()):
        tables.extend(_tables_in_block(raw, file, sheet, a, b))
    for k, t in enumerate(tables, 1):
        t.block = k
        t.label = sheet if len(tables) == 1 else f"{sheet}[{k}]"
    return tables


def read_tables(*sources: Any) -> List[Table]:
    """Lee los archivos y devuelve TODAS las tablas detectadas (limpias y tipadas)."""
    return _load(_expand_sources(list(sources) if len(sources) != 1 else sources[0]))[0]


def _load(srcs: List[Source]) -> Tuple[List[Table], List[str]]:
    tables, problems = [], []
    for s in srcs:
        try:
            sheets = _read_raw(s.obj, s.name)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            problems.append(f"{s.name}: no se pudo abrir ({e})")
            logger.error(problems[-1])
            continue
        for sh, raw in sheets.items():
            if raw.empty:
                continue
            found = _detect_tables(raw, s.name, sh)  # type: ignore[arg-type]
            if not found:
                problems.append(f"{s.name} / {sh}: sin tablas reconocibles")
            tables.extend(found)
    return tables, problems


# =============================================================================
# 5. CONSOLIDACIÓN
# =============================================================================
@dataclass
class DataBundle:
    """Resultado completo: consolidado por contenedor + todas las tablas + resumen de lo detectado."""
    master: pd.DataFrame
    tables: List[Table]
    profile: pd.DataFrame
    warnings: List[str] = field(default_factory=list)
    base_date: Optional[pd.Timestamp] = None

    def containers(self) -> List[Container]:
        df = self.master
        if df.empty:
            return []
        return [Container(id=str(r.id), eta=int(r.eta_dia), need_by=int(r.need_by_dia),
                          part_family=str(r.family), vessel=str(r.vessel))
                for r in df.itertuples(index=False)]

    def table(self, sheet: str, file: Optional[str] = None) -> Optional[pd.DataFrame]:
        for t in self.tables:
            if (t.sheet == sheet or t.label == sheet) and (file is None or file.lower() in t.file.lower()):
                return t.df
        return None

    def to_excel(self, path: Union[str, "os.PathLike[str]"]) -> str:
        """Escribe consolidado + perfil + cada tabla limpia en un Excel."""
        used: set = set()

        def sheet_name(txt: str) -> str:
            base = re.sub(r"[\[\]:*?/\\]", "_", txt)[:31]
            nm, i = base, 1
            while nm in used:
                i += 1
                nm = f"{base[:28]}_{i}"
            used.add(nm)
            return nm

        with pd.ExcelWriter(path, engine="openpyxl") as xw:
            self.master.to_excel(xw, sheet_name=sheet_name("Consolidado"), index=False)
            self.profile.to_excel(xw, sheet_name=sheet_name("Perfil"), index=False)
            for t in self.tables:
                t.df.to_excel(xw, sheet_name=sheet_name(f"{os.path.splitext(t.file)[0][:10]}_{t.label}"), index=False)
        return os.fspath(path)

    def summary(self) -> str:
        lines = [f"Contenedores consolidados: {len(self.master)}"]
        if self.base_date is not None:
            lines.append(f"Fecha base (día 0): {self.base_date.date()}")
        lines.append(self.profile.to_string(index=False))
        lines += [f"AVISO: {w}" for w in self.warnings]
        return "\n".join(lines)


def _default_tag(name: str, taken: set) -> str:
    toks = [t for t in _snake(os.path.splitext(name)[0]).split("_")
            if t and not t.isdigit() and t not in _STOP_TAG_WORDS]
    tag = (toks[0] if toks else "src")[:10]
    base, i = tag, 1
    while tag in taken:
        i += 1
        tag = f"{base}{i}"
    return tag


def _stack(tables: List[Table]) -> pd.DataFrame:
    frames = []
    for t in tables:
        d = t.df.copy()
        d["hoja"] = t.label
        frames.append(d)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.concat(frames, ignore_index=True, sort=False)


def _aggregate_support(tables: List[Table], tag: str) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
    """Una fila por contenedor para tablas de apoyo (varias filas por contenedor -> se agregan)."""
    big = _stack(tables)
    big = big[big["id"].notna()]
    roles: Dict[str, List[str]] = {}
    for t in tables:
        for r, cols in t.roles.items():
            roles.setdefault(r, [])
            roles[r] += [c for c in cols if c not in roles[r]]
    drop_cols = {c for t in tables for c in t.roles.get("container", [])} | {"fila_origen"}
    big = big.drop(columns=[c for c in drop_cols if c in big.columns])

    order = list(dict.fromkeys(big["id"].tolist()))
    hojas = _join_by_id(big["id"], big["hoja"], order)
    big = big.drop_duplicates(subset=[c for c in big.columns if c != "hoja"])
    g = big.groupby("id", sort=False)
    out: Dict[str, pd.Series] = {"n_filas": g.size().reindex(order)}
    ref = (roles.get("reference") or [None])[0]
    if ref in big.columns:
        out["n_refs"] = g[ref].nunique().reindex(order)
    for c in big.columns:
        if c in ("id", "hoja"):
            continue
        s = big[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            out[c] = g[c].min().reindex(order)
        elif pd.api.types.is_bool_dtype(s):
            out[c] = g[c].agg(lambda x: bool(x.fillna(False).any())).reindex(order)
        elif pd.api.types.is_numeric_dtype(s):
            out[c] = g[c].first().reindex(order)
        else:
            out[c] = _join_by_id(big["id"], s, order)
    out["hojas"] = hojas
    agg = pd.DataFrame(out)
    agg.index.name = "id"
    agg = agg.reset_index()
    ren = {c: f"{tag}_{c}" for c in agg.columns if c != "id"}
    agg = agg.rename(columns=ren)
    roles = {r: [ren[c] for c in cols if c in ren] for r, cols in roles.items()}
    return agg, {r: v for r, v in roles.items() if v}


def _coalesce(df: pd.DataFrame, cols: Sequence[str]) -> Optional[pd.Series]:
    out = None
    for c in cols:
        if c in df.columns:
            out = df[c] if out is None else out.combine_first(df[c])
    return out


def _set_canonical(df: pd.DataFrame, name: str, values: Any) -> None:
    if name in df.columns:                       # no pisar una columna original con el mismo nombre
        df.rename(columns={name: f"{name}_src"}, inplace=True)
    df[name] = values


def build_dataset(
    sources: Any,
    *,
    master: Optional[str] = None,
    sheets: Optional[Mapping[str, Sequence[str]]] = None,
    include_untracked: bool = False,
    skip_disjoint: bool = True,
    exclude_status: Sequence[str] = ("DESCARGADO",),
    default_buffer_days: int = 10,
    late_fix_days: int = 7,
    base_date: Optional[pd.Timestamp] = None,
) -> DataBundle:
    """
    Procesa cualquier conjunto de archivos y devuelve un DataBundle.

    sources            ruta/carpeta/archivo subido (o lista de ellos; ver también la clase Source).
    master             texto del nombre del archivo que debe ser la fuente maestra (opcional; si no
                       se indica, se elige la tabla con más ETA/buque/ETD/familia).
    sheets             {'texto_del_archivo': ['Hoja1', ...]} para limitar las hojas de un archivo.
    include_untracked  agrega contenedores que están en archivos de apoyo (con ETA, no descargados)
                       pero no en la maestra.
    skip_disjoint      omite tablas sin ningún contenedor en común con la maestra (históricos).
    default_buffer_days need_by = ETA + este valor cuando no hay fecha de ruptura.
    late_fix_days      si la ruptura es anterior a la ETA, need_by = eta + este valor
                       (la ruptura original queda en 'ruptura'; bandera 'ruptura_antes_de_eta').
    """
    srcs = _expand_sources(sources)
    tables, problems = _load(srcs)
    notes: List[str] = list(problems)
    id_tables = [t for t in tables if t.has_id]
    for t in tables:
        t.status = "" if t.has_id else "sin_id (sin columna de contenedor)"

    # ---------------- 5.1 elegir la tabla maestra ----------------
    forced = {s.name for s in srcs if s.master}
    if master:
        forced |= {s.name for s in srcs if master.lower() in str(s.name).lower()}
    pool = [t for t in id_tables if t.file in forced] if forced else id_tables
    best = max(pool, key=lambda t: (t.master_score, len(t.ids)), default=None)
    if forced and (best is None or best.master_score == 0):
        notes.append("La fuente maestra indicada no tiene ETA/ETD; se elige automáticamente.")
        best = max(id_tables, key=lambda t: (t.master_score, len(t.ids)), default=None)
    master_tables: List[Table] = []
    if best is not None and best.master_score > 0:
        sig = lambda t: set(t.df.columns) - {"fila_origen", "hoja"}  # noqa: E731
        master_tables = [t for t in id_tables if t.file == best.file and sig(t) == sig(best)]
        for t in master_tables:
            t.status = "maestra"

    # ---------------- 5.2 tablas de apoyo ----------------
    master_ids = set().union(*(t.ids for t in master_tables)) if master_tables else set()
    support: List[Table] = []
    for t in id_tables:
        if t.status == "maestra":
            continue
        allowed = next((v for k, v in (sheets or {}).items() if k.lower() in t.file.lower()), None)
        if allowed is not None and t.sheet not in allowed:
            t.status = "omitida (hoja no seleccionada)"
        elif allowed is None and skip_disjoint and master_ids and not (t.ids & master_ids):
            t.status = "omitida (sin contenedores en común con la maestra)"
            notes.append(f"{t.file} / {t.label}: omitida, no comparte contenedores con la maestra.")
        else:
            t.status = "apoyo"
            support.append(t)

    # ---------------- 5.3 base maestra ----------------
    tag_of: Dict[str, str] = {}
    taken = {(s.tag or "") for s in srcs if s.tag is not None}
    master_file = master_tables[0].file if master_tables else None
    for s in srcs:
        if s.tag is not None:
            tag_of[s.name] = s.tag  # type: ignore[index]
        elif s.name == master_file:
            tag_of[s.name] = ""     # la maestra conserva los nombres originales (sin prefijo)  # type: ignore[index]
        else:
            tag_of[s.name] = _default_tag(s.name, taken)  # type: ignore[index]
        taken.add(tag_of[s.name])  # type: ignore[index]

    if master_tables:
        mdf = _stack(master_tables) if len(master_tables) > 1 else master_tables[0].df.copy()
        if len(master_tables) > 1:
            mdf = mdf.rename(columns={"hoja": "hoja_origen"})
        mdf = mdf[mdf["id"].notna()]
        dup = int(mdf["id"].duplicated().sum())
        if dup:
            notes.append(f"Maestra: {dup} contenedores repetidos, se conserva la primera fila.")
            mdf = mdf.drop_duplicates("id", keep="first")
        df = mdf.drop(columns=["fila_origen"], errors="ignore").reset_index(drop=True)
        mfile = master_tables[0].file
        df["fuente"] = os.path.splitext(mfile)[0].upper()
        mroles = master_tables[0].roles
        mtag = tag_of[mfile]
        if mtag:
            df = df.rename(columns={c: f"{mtag}_{c}" for c in df.columns if c not in ("id", "fuente")})
            mroles = {r: [f"{mtag}_{c}" for c in cols] for r, cols in mroles.items()}
    else:
        df = pd.DataFrame({"id": sorted(set().union(*(t.ids for t in support)) if support else set())})
        df["fuente"] = "APOYO"
        mroles = {}

    # ---------------- 5.4 agregar fuentes de apoyo ----------------
    agg_roles: Dict[str, List[str]] = {}
    by_file: Dict[str, List[Table]] = {}
    for t in support:
        by_file.setdefault(t.file, []).append(t)
    aggs: List[Tuple[str, pd.DataFrame, Dict[str, List[str]]]] = []
    for f, ts in by_file.items():
        tag = tag_of[f] or _default_tag(f, set())
        agg, r = _aggregate_support(ts, tag)
        aggs.append((tag, agg, r))
        for role, cols in r.items():
            agg_roles.setdefault(role, []).extend(cols)

    if include_untracked and master_tables:
        extra_parts = []
        for tag, agg, r in aggs:
            eta_c = r.get("eta", [])
            if not eta_c:
                continue
            e = agg[~agg["id"].isin(df["id"]) & _coalesce(agg, eta_c).notna()]
            st = (r.get("status") or [None])[0]
            if st:
                e = e[~e[st].astype("string").str.upper().isin([x.upper() for x in exclude_status])]
            if not e.empty:
                extra_parts.append(pd.DataFrame({"id": e["id"], "fuente": tag.upper()}))
        if extra_parts:
            extra = pd.concat(extra_parts, ignore_index=True).drop_duplicates("id")
            extra = extra[~extra["id"].isin(df["id"])]
            df = pd.concat([df, extra], ignore_index=True, sort=False)
            notes.append(f"Se agregaron {len(extra)} contenedores solo presentes en archivos de apoyo.")

    for tag, agg, _ in aggs:
        df = df.merge(agg, on="id", how="left")
        df[f"en_{tag}"] = df[f"{tag}_n_filas"].notna()

    # ---------------- 5.5 campos canónicos ----------------
    def chain(role: str) -> List[str]:
        return [c for c in mroles.get(role, []) + agg_roles.get(role, []) if c in df.columns]

    eta = _coalesce(df, chain("eta"))
    if eta is None:                                           # sin ETA en ningún lado: EM como último recurso
        eta = _coalesce(df, chain("em"))
        if eta is not None:
            notes.append("No hay columna ETA: se usó la fecha EM como ETA.")
    if eta is None:
        notes.append("No se encontró ninguna columna de ETA; no se puede construir el consolidado para el modelo.")
        return DataBundle(df, tables, _profile(tables, tag_of), notes, None)

    vessel = _coalesce(df, chain("vessel"))
    family = _coalesce(df, chain("family"))
    origin = _coalesce(df, agg_roles.get("origin", []) + mroles.get("origin", []))
    etd = _coalesce(df, chain("etd"))
    rup_cols = chain("ruptura")

    _set_canonical(df, "eta", pd.to_datetime(eta))
    _set_canonical(df, "vessel", (vessel.astype("string") if vessel is not None
                                  else pd.Series(pd.NA, index=df.index, dtype="string")).fillna("BUQUE_GEN"))
    _set_canonical(df, "family", (family.astype("string") if family is not None
                                  else pd.Series(pd.NA, index=df.index, dtype="string")).fillna("GEN"))
    if etd is not None:
        _set_canonical(df, "etd", pd.to_datetime(etd))
    rup = df[[c for c in rup_cols if c != "ruptura"]].min(axis=1) if rup_cols else pd.Series(pd.NaT, index=df.index)
    _set_canonical(df, "ruptura", pd.to_datetime(rup))
    df["need_by_fecha"] = df["ruptura"].fillna(df["eta"] + pd.Timedelta(days=default_buffer_days))
    df["ruptura_estimada"] = df["ruptura"].isna()

    n_before = len(df)
    df = df[df["eta"].notna()].copy()
    if len(df) < n_before:
        notes.append(f"{n_before - len(df)} contenedores sin ETA fueron excluidos del consolidado.")
    if df.empty:
        return DataBundle(df, tables, _profile(tables, tag_of), notes, None)

    base = pd.Timestamp(base_date).normalize() if base_date is not None else df["eta"].min()
    df["eta_dia"] = (df["eta"] - base).dt.days.clip(lower=0).astype(int)
    need = (df["need_by_fecha"] - base).dt.days
    df["ruptura_antes_de_eta"] = need < df["eta_dia"]
    df["need_by_dia"] = np.where(need < df["eta_dia"], df["eta_dia"] + late_fix_days, need).astype(int)

    lead = ["id", "eta_dia", "need_by_dia", "family", "vessel", "eta", "ruptura", "need_by_fecha",
            "ruptura_estimada", "ruptura_antes_de_eta", "fuente"]
    df = df[lead + [c for c in df.columns if c not in lead]].reset_index(drop=True)
    df.attrs["base_date"] = base
    logger.info("Consolidado: %d contenedores (día 0 = %s). Con ruptura real: %d.",
                len(df), base.date(), int((~df["ruptura_estimada"]).sum()))
    for n in notes:
        logger.warning(n)
    return DataBundle(df, tables, _profile(tables, tag_of), notes, base)


def _profile(tables: List[Table], tag_of: Mapping[str, str]) -> pd.DataFrame:
    rows = []
    for t in tables:
        rows.append({
            "archivo": t.file, "hoja": t.label, "titulo": t.title, "rango": t.cell_range,
            "filas": len(t.df), "columnas": len([c for c in t.df.columns if c not in _RESERVED]),
            "contenedores": len(t.ids), "uso": t.status,
            "roles": ", ".join(f"{r}={'/'.join(c)}" for r, c in t.roles.items()),
            "columnas_vacias_descartadas": len(t.dropped_empty),
        })
    return pd.DataFrame(rows)


def profile_sources(*sources: Any) -> pd.DataFrame:
    """Resumen rápido de lo que se detecta en cada archivo/hoja (sin cruzar)."""
    srcs = _expand_sources(list(sources) if len(sources) != 1 else sources[0])
    tables, _ = _load(srcs)
    return _profile(tables, {})


# =============================================================================
# 6. COMPATIBILIDAD CON LA v1
# =============================================================================
def load_and_clean_excel(file_source: FileSource, header_keyword: str = "Contenedor",
                         header_row: Optional[int] = None, sheet_name: Union[int, str] = 0
                         ) -> Optional[pd.DataFrame]:
    """v1: devuelve la tabla (de la hoja indicada) cuyo encabezado contiene 'header_keyword'.
    Los nombres de columna salen normalizados en MAYÚSCULAS, igual que antes."""
    try:
        srcs = _expand_sources(file_source)
        sheets = _read_raw(srcs[0].obj, srcs[0].name)  # type: ignore[arg-type]
        name = list(sheets)[sheet_name] if isinstance(sheet_name, int) else sheet_name
        found = _detect_tables(sheets[name], srcs[0].name, name)  # type: ignore[arg-type]
        key = _norm(header_keyword)
        for t in found:
            if any(key == v for v in t.norm.values()):
                out = t.df.drop(columns=["id", "fila_origen"], errors="ignore")
                out.columns = [t.norm.get(c, c.upper()) for c in out.columns]
                return out
        logger.warning("No se encontró el encabezado '%s'.", header_keyword)
    except Exception as e:  # noqa: BLE001
        logger.error("Error al cargar archivo: %s", e)
    return None


def _legacy_aliases(df: pd.DataFrame) -> pd.DataFrame:
    """Nombres de columna que producía la v1 (para no romper código existente)."""
    def alias(new: str, old: str, fn: Any = None) -> None:
        if new not in df.columns and old in df.columns:
            df[new] = fn(df[old]) if fn else df[old]

    alias("naviera", "buque_salida_inicial")
    alias("dias_puerto_planta", "puerto_planta")
    alias("status_atraso", "status_atraso_pto")
    alias("llego", "llegada", lambda s: s.map(lambda v: _norm(v) == "LLEGO" if pd.notna(v) else False).astype(bool))
    alias("em_diel", "diel_em_diel")
    alias("em_diel_flag", "diel_em_diel_txt", lambda s: s.map(lambda v: _norm(v) if pd.notna(v) else pd.NA))
    alias("diel_obs", "diel_observaciones")
    alias("en_prioridades", "en_prio")
    # la v1 devolvía el primer valor (origen) o la lista ordenada separada por comas (tipo, hojas)
    first = lambda v: v.split(" | ")[0] if isinstance(v, str) else v  # noqa: E731
    srt = lambda v: ",".join(sorted(set(v.split(" | ")))) if isinstance(v, str) else v  # noqa: E731
    if "prio_origen" in df.columns:
        df["prio_origen"] = df["prio_origen"].map(first).astype("string")
    for c in ("prio_tipo", "prio_hojas"):
        if c in df.columns:
            df[c] = df[c].map(srt).astype("string")
    if "eta_critica" in df.columns:
        df["eta_critica"] = df["eta_critica"].fillna(False).astype(bool)
    return df


def _legacy_sources(tracking_file: Any, diel_file: Any, prio_file: Any) -> List[Source]:
    srcs: List[Source] = []
    if tracking_file is not None and isinstance(tracking_file, (str, os.PathLike)) and os.path.isdir(tracking_file):
        dir_path = str(tracking_file)
        direct_files = [f for f in os.listdir(dir_path) if not f.startswith("~$") and f.lower().endswith(SUPPORTED_EXT)]
        if not direct_files:
            subdirs = sorted([os.path.join(dir_path, d) for d in os.listdir(dir_path) if os.path.isdir(os.path.join(dir_path, d))])
            subdirs = sorted(subdirs, key=lambda p: ("2nd" in p, p), reverse=True)
            for sub in subdirs:
                if any(not f.startswith("~$") and f.lower().endswith(SUPPORTED_EXT) for f in os.listdir(sub)):
                    dir_path = sub
                    break
        for fn in sorted(os.listdir(dir_path)):
            low = fn.lower()
            p = os.path.join(dir_path, fn)
            if fn.startswith("~$") or not low.endswith(SUPPORTED_EXT):
                continue
            if "tracking" in low:
                srcs.append(Source(p, tag="", master=True))
            elif "diel" in low or "programación" in low or "programacion" in low:
                srcs.append(Source(p, tag="diel"))
            elif "prioridades" in low:
                srcs.append(Source(p, tag="prio"))
            else:
                srcs.append(Source(p))
        return srcs
    if tracking_file is not None:
        srcs.append(Source(tracking_file, tag="", master=True))
    if diel_file is not None:
        srcs.append(Source(diel_file, tag="diel"))
    if prio_file is not None:
        srcs.append(Source(prio_file, tag="prio"))
    return srcs


def process_real_tracking_dataframe(
    tracking_file: Optional[FileSource] = None,
    diel_file: Optional[FileSource] = None,
    prio_file: Optional[FileSource] = None,
    prio_sheets: Optional[Sequence[str]] = None,
    include_untracked: bool = False,
    default_buffer_days: int = 10,
    late_fix_days: int = 7,
    base_date: Optional[pd.Timestamp] = None,
    **extra: Any,
) -> pd.DataFrame:
    """
    Igual que en la v1: una fila por contenedor con TODA la información cruzada y las columnas
    del modelo (id, eta, need_by, part_family->family, vessel...). Cambios:
      * lee todas las hojas de cada archivo y conserva todas las columnas;
      * prio_sheets ya no es necesario (por defecto se omiten solas las hojas sin contenedores
        en común con el Tracking); si se pasa, limita las hojas de Prioridades.
    Se pueden pasar más archivos con extra_files=[...] para cruzarlos también.
    """
    srcs = _legacy_sources(tracking_file, diel_file, prio_file)
    srcs += _expand_sources(extra.pop("extra_files", []) or [])
    sheets = {"prioridades": list(prio_sheets)} if prio_sheets else None
    if sheets and prio_file is not None and not isinstance(prio_file, (str, os.PathLike)):
        sheets = {_name_of(prio_file, 1): list(prio_sheets)}
    elif sheets and isinstance(prio_file, (str, os.PathLike)):
        sheets = {os.path.basename(os.fspath(prio_file)): list(prio_sheets)}
    bundle = build_dataset(srcs, include_untracked=include_untracked, sheets=sheets,
                           default_buffer_days=default_buffer_days, late_fix_days=late_fix_days,
                           base_date=base_date, **extra)
    df = bundle.master
    if df.empty:
        return df
    attrs = dict(df.attrs)
    df = _legacy_aliases(df)
    df.attrs.update(attrs)
    return df


def process_real_tracking_data(tracking_file=None, diel_file=None, prio_file=None, **kwargs) -> List[Container]:
    """Igual que la v1: lista de Container (id, eta, need_by, part_family, vessel) para el modelo."""
    df = process_real_tracking_dataframe(tracking_file, diel_file, prio_file, **kwargs)
    containers: List[Container] = [
        Container(id=str(r.id), eta=int(r.eta_dia), need_by=int(r.need_by_dia),
                  part_family=str(r.family), vessel=str(r.vessel))
        for r in df.itertuples(index=False)
    ] if not df.empty else []
    logger.info("Procesamiento finalizado. Total contenedores cargados: %d", len(containers))
    return containers


# =============================================================================
# 7. LÍNEA DE COMANDOS
# =============================================================================
def _main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Procesa y cruza cualquier conjunto de Excel/CSV por contenedor.")
    ap.add_argument("archivos", nargs="+", help="archivos o carpetas")
    ap.add_argument("--master", help="texto del nombre del archivo maestro (opcional)")
    ap.add_argument("--out", help="escribe consolidado + tablas en este .xlsx")
    ap.add_argument("--include-untracked", action="store_true")
    ap.add_argument("--profile", action="store_true", help="solo muestra lo detectado en cada hoja")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 70)
    if a.profile:
        print(profile_sources(*a.archivos).to_string(index=False))
        return 0
    b = build_dataset(a.archivos, master=a.master, include_untracked=a.include_untracked)
    print(b.summary())
    if a.out:
        print("Escrito:", b.to_excel(a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())