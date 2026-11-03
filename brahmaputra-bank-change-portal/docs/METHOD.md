# Method (short)

Study area: Assam main-stem Brahmaputra, Sadiya → Dhubri (NW-2). Not the old GEE rectangle. Not the whole basin.

Acquire: GEE Sentinel-1 GRD, Sentinel-2 SR, Landsat C2. Process usable scenes only.

Optical water: MNDWI/NDWI. SAR water: VV/VH backscatter. Never MNDWI on SAR. Fusion only if times are close.

Geometry: corridor association → RiverOnly + RiverEnvelope → principal centerline (endpoint path) → split envelope at endpoints into left/right proxy banks (looking downstream) → 300 m widths on a frozen reference network.

Change: Δd = d_B − d_A (outward +) → candidate erosion / accretion / stable. Envelope difference → corridor expansion / contraction. Not proven geomorphic erosion.

CRS: Assam Albers (lon0=93). Distortion vs geodesic at Sadiya/Guwahati/Dhubri is stored in study-area metadata.

Portal talks to FastAPI. Bootstrap epochs exist so the app runs before GEE credentials are attached; they are labelled `bootstrap_pending_gee`.
