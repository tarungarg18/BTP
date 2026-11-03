# How the river is extracted (short)

The map must sit on the **visible Brahmaputra**, not on a sketched corridor.

1. **Search path only:** a Brahmaputra centreline from Sadiya to Dhubri is buffered by 11 km. That belt is a clip window. It is not drawn as the river.
2. **Water from satellites:** Sentinel-2 MNDWI = (Green − SWIR1)/(Green + SWIR1); water if MNDWI > 0.1. Sentinel-1: VV darker than −16 dB. Never MNDWI on radar.
3. **Collections:** GEE `COPERNICUS/S2_SR_HARMONIZED` and `COPERNICUS/S1_GRD` when `GEE_PROJECT` is set. Otherwise the same Copernicus Sentinel-2 L2A / Sentinel-1 family via Planetary Computer STAC.
4. **River-only:** water pixels inside the belt, small ponds dropped, sandbars kept as holes.
5. **Outer banks:** fill the holes to get the corridor envelope; split the outer ring at the upstream and downstream ends into left/right looking downstream.
6. **Centreline:** skeleton of that envelope, then the shortest path from Sadiya to Dhubri.
7. **Width:** every 300 m on a frozen centreline from the first date.
8. **Change:** Δd = d_B − d_A (outward +). Envelope difference = candidate expansion/contraction. Water level can mimic erosion. Unvalidated.
