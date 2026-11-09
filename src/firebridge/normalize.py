"""Strict native-point adapters. A malformed row fails the entire snapshot."""
import csv
from datetime import datetime
import io
import math
from .catalog import PLATFORMS, source_id
from .util import digest, UTC

ALIASES = {"T":"Terra","A":"Aqua","terra":"Terra","aqua":"Aqua","N":"SNPP","S-NPP":"SNPP",
           "Suomi NPP":"SNPP","NOAA-20":"N20","NOAA-21":"N21","1":"N20","2":"N21","8":"L8","9":"L9"}
BASE = {"latitude","longitude","acq_date","acq_time","satellite","confidence","daynight"}


def number(value, *, optional=False, minimum=None, maximum=None):
    if value is None or str(value).strip() in ("", "None", "nan"):
        if optional: return None
        raise ValueError("Required numeric value missing")
    val = float(value)
    if not math.isfinite(val) or (minimum is not None and val < minimum) or (maximum is not None and val > maximum):
        raise ValueError("Numeric value outside native field bounds")
    return val


def normalize(row, stream, allowed_platforms, *, allow_historical_collections=False):
    platform = ALIASES.get(str(row["satellite"]), str(row["satellite"]))
    if platform not in allowed_platforms or platform not in PLATFORMS:
        raise ValueError("Unexpected platform for this feed")
    instrument = PLATFORMS[platform][1]
    time = str(row["acq_time"]).strip().zfill(4)
    if len(time) != 4 or not time.isdigit(): raise ValueError("Invalid HHMM acquisition time")
    acquired = datetime.strptime(str(row["acq_date"]) + time, "%Y-%m-%d%H%M").replace(tzinfo=UTC)
    lat = number(row["latitude"], minimum=-90, maximum=90)
    lon = number(row["longitude"], minimum=-180, maximum=180)
    confidence = str(row["confidence"]).strip()
    if instrument == "MODIS":
        confidence = format(number(confidence, minimum=0, maximum=100), "g")
        scheme = "MODIS_0_100"
    elif instrument == "VIIRS":
        confidence = confidence.lower()
        if confidence not in ("l","n","h"): raise ValueError("Invalid VIIRS confidence")
        scheme = "VIIRS_l_n_h"
    else:
        confidence = confidence.upper()
        if confidence not in ("L","M","H"): raise ValueError("Invalid Landsat confidence")
        scheme = "LANDSAT_L_M_H"
    dn = str(row["daynight"]).upper()
    if dn not in ("D","N"): raise ValueError("Invalid day/night flag")
    version = str(row.get("version", row.get("collection", "")))
    upper = version.upper()
    if "URT" in upper or ("RT" in upper and "NRT" not in upper):
        return None  # retained in raw payload, excluded from the NRT product
    if stream == "standard" and "NRT" in upper: raise ValueError("NRT record inside a standard feed")
    collection=upper.replace('NRT','')
    modis_c6 = ('6','006','6.0','6.02','6.03')
    if collection and instrument=='MODIS' and collection not in (*modis_c6,'61','061','6.1','61.03','6.1.03'):
        raise ValueError('Unsupported MODIS collection/version')
    if instrument=='MODIS' and collection in modis_c6 and not allow_historical_collections:
        raise ValueError('Historical MODIS Collection 6 requires the history loader')
    if collection and instrument=='VIIRS' and collection not in ('2','02','002','2.0'):
        raise ValueError('Unsupported VIIRS collection/version')
    bands = {}
    if instrument in ("MODIS","VIIRS"):
        for names, band in [(("brightness","bright_ti4"),"T21_22" if instrument=="MODIS" else "I4"),
                            (("bright_t31","bright_ti5"),"T31" if instrument=="MODIS" else "I5")]:
            value = next((row[n] for n in names if n in row), None)
            value = number(value, optional=True, minimum=0)
            if value is not None: bands[band] = {"value":value,"unit":"K"}
    scan = number(row.get("scan"), optional=True, minimum=0) if instrument in ("MODIS","VIIRS") else None
    track = number(row.get("track"), optional=True, minimum=0) if instrument in ("MODIS","VIIRS") else None
    if scan == 0 or track == 0: raise ValueError("Zero pixel footprint size")
    sample = number(row.get("sample"), optional=True, minimum=0)
    if sample is not None and not sample.is_integer(): raise ValueError("Non-integral sample index")
    raw_type = row.get("type")
    raw_type = None if raw_type is None or str(raw_type) in ("", "nan") else format(number(raw_type,minimum=0,maximum=3),"g")
    if raw_type is not None and raw_type not in ("0","1","2","3"): raise ValueError("Invalid type")
    native_collection = '6' if instrument=='MODIS' and collection in modis_c6 else None
    result = dict(source_id=source_id(platform,stream,native_collection), acquired_at=acquired,longitude=lon,latitude=lat,
        confidence_raw=confidence,confidence_scheme=scheme,type_raw=raw_type,
        day_night="day" if dn=="D" else "night",frp_mw=number(row.get("frp"),optional=True,minimum=0),
        brightness_bands=bands,scan_km=scan,track_km=track,cross_track_sample=int(sample) if sample is not None else None,
        processing_level=stream,
        native_fields={k:str(row[k]) for k in ("version","scan","track") if row.get(k) is not None})
    # Excludes file names and row positions. Retains sample/bands/version/scan semantics.
    result["record_sha256"] = digest({"contract":"native-v1",**result})
    result["native_record_key"] = str(row.get("source_row", result["record_sha256"]))
    return result


def parse_csv(body, stream, platforms):
    text = body.decode("utf-8-sig", errors="strict")
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    if not reader.fieldnames or not BASE.issubset(reader.fieldnames) or len(set(reader.fieldnames))!=len(reader.fieldnames):
        raise ValueError("Unexpected FIRMS CSV header; not a valid empty result")
    rows=[]; excluded=0
    for i,row in enumerate(reader,2):
        if None in row or any(v is None for v in row.values()): raise ValueError("Truncated or malformed CSV row")
        row["source_row"] = i
        out = normalize(row,stream,platforms)
        if out is None: excluded+=1
        else: rows.append(out)
    return rows, excluded
