# FIREBRIDGE field dictionary

The original bytes remain in the ZIP archives. Every derived regional row retains `archive`, `member`, and `source_row` (CSV line number, header is line 1).

| Native field | MODIS | VIIRS | Landsat | Analysis rule |
|---|---|---|---|---|
| latitude / longitude | WGS84 pixel center, degrees | WGS84 pixel center, degrees | Detection location, degrees | Not necessarily ignition location; validate latitude ±90, longitude ±180 |
| acq_date / acq_time | UTC date / HHMM | Same | Same | Keep time as text; zero-pad before constructing UTC timestamp |
| satellite | Aqua / Terra | SNPP / N20 / N21 in these files | L8 / L9 | Preserve platform; never pool all VIIRS as one instrument instance |
| instrument | MODIS | `SNPP` in S-NPP archive, `VIIRS` in NOAA files | OLI / OLI-2 | Preserve native label; derive a separate family |
| confidence | 0–100 numeric confidence | `l`, `n`, `h` categories | `L`, `M`, `H` categories | Native confidence is not calibrated fire probability |
| brightness | 21/22 channel pixel brightness temperature, K | I4 brightness temperature, K | Absent in supplied files | Do not pool channels as one thermometer |
| bright_t31 | Channel 31 brightness temperature, K | Generic exported column for I5 brightness, K | Absent | Preserve name and document sensor-specific interpretation |
| scan / track | Pixel footprint dimensions, km | Pixel footprint dimensions, km | LOS cross-/along-track pixel positions | Landsat values cannot be multiplied as km² |
| frp | Pixel radiative power, MW | Retrieved pixel radiative power, MW | Absent | Power, not energy or burned area; don't sum across overpasses as if simultaneous |
| daynight | D / N | D / N | D / N | Native day/night flag retained; daytime regimes need actual time checks |
| version | Collection/processing revision | Collection/processing revision | Absent in supplied files | Retain strings such as `61.03`, `2`, `2.0NRT`; NRT stays separate |
| type | Standard: 0 vegetation, 1 volcano, 2 static land source, 3 offshore | Present in supplied standard files; absent in NOAA-21 NRT | Absent | Presumed source type; vegetation does not establish wildfire cause |

## Derived fields

| Field | Definition |
|---|---|
| stream | `standard` or `NRT`, based on CSV archive/nrt member identity, checked against native versions |
| acq_utc | Timezone-aware UTC date and zero-padded acquisition time |
| sensor_family | MODIS for Aqua/Terra, VIIRS for SNPP/N20/N21 in the regional subset |
| confidence_class | MODIS [0,30) low, [30,80) nominal, [80,100] high; VIIRS l/n/h mapped to native categories |
| retained | True for nominal/high; exploratory sensitivity filter, not deletion from raw tables |
| solar_hour | (UTC fractional hour + longitude/15) modulo 24; approximate solar time, not civil time |
| x_m / y_m | EPSG:6933 equal-area projected center coordinates, meters |
| grid_x_5km / grid_y_5km | floor(x/5000), floor(y/5000), origin (0,0); center-based assignment, not footprint intersection |
| pilot | In the inclusive rectangle −6.4,34.5,−4.5,35.9 (west,south,east,north) |
| morocco_context_rectangle | In the inclusive rectangle −13.5,27,−0.9,36.1; not a national boundary |
| southern_spain_rectangle | In the inclusive rectangle −7.5,36,−1,38.5; not a national boundary |

## Important quantities that do not exist yet

Usable/cloud/invalid land fractions, valid reference negatives, shared observation support, true incident identifiers, ignition cause, fire perimeter, burned hectares from hotspots, model probabilities, and observation-normalized calendar activity. Missing values for these quantities must remain unavailable.

Sources: [NASA MODIS/VIIRS attributes](https://www.earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs), [MODIS guide, confidence table](https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf), [Landsat FAQ](https://forum.earthdata.nasa.gov/viewtopic.php?t=5197). NASA documentation is cached in `data/external/`.
