"""
MBTiles Local Offline Tile Server.
==================================
Serves offline tiles directly from SQLite MBTiles container (ukraine.mbtiles).
Allows complete zero-internet tactical operation under mobile blackout.
"""

import os
import sqlite3
from typing import Optional
from fastapi import APIRouter, HTTPException, Response

router = APIRouter(prefix="/api/v1/tiles", tags=["offline_tiles"])

# Default paths checked for offline MBTiles container
POSSIBLE_MBTILES_PATHS = [
    "/Users/gonzo/Desktop/PXY_MAP_APP/ukraine.mbtiles",
    "/Users/gonzo/Desktop/V2/lyudyn-iskun-v2/assets/ukraine.mbtiles",
    os.getenv("MBTILES_PATH", "/app/assets/ukraine.mbtiles")
]


def get_active_mbtiles_path() -> Optional[str]:
    for p in POSSIBLE_MBTILES_PATHS:
        if os.path.isfile(p):
            return p
    return None


@router.get("/mbtiles/status")
def get_mbtiles_status():
    active_path = get_active_mbtiles_path()
    if not active_path:
        return {
            "status": "offline_bundle_missing",
            "active": False,
            "message": "ukraine.mbtiles not found locally. Live online OSM / CARTO tiles active.",
            "download_url": "https://pub-9ea24f35ecd3400394fd53bc01d5d0bf.r2.dev/ukraine.mbtiles"
        }

    try:
        conn = sqlite3.connect(active_path)
        cur = conn.cursor()
        cur.execute("SELECT value FROM metadata WHERE name='name'")
        name_row = cur.fetchone()
        cur.execute("SELECT count(*) FROM tiles")
        tile_count = cur.fetchone()[0]
        conn.close()

        return {
            "status": "online",
            "active": True,
            "path": active_path,
            "name": name_row[0] if name_row else "ukraine",
            "total_tiles": tile_count,
            "size_mb": round(os.path.getsize(active_path) / (1024 * 1024), 2)
        }
    except Exception as e:
        return {
            "status": "error",
            "active": False,
            "error": str(e)
        }


@router.get("/mbtiles/{z}/{x}/{y}")
def get_mbtile(z: int, x: int, y: int):
    active_path = get_active_mbtiles_path()
    if not active_path:
        raise HTTPException(status_code=404, detail="MBTiles container not mounted")

    # Flip Y for TMS schema if necessary: tms_y = (1 << z) - 1 - y
    tms_y = (1 << z) - 1 - y

    try:
        conn = sqlite3.connect(active_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
            (z, x, tms_y)
        )
        row = cur.fetchone()
        conn.close()

        if not row or not row[0]:
            raise HTTPException(status_code=404, detail="Tile not found")

        # Vector tiles (pbf) are typically gzipped protobuf
        return Response(content=row[0], media_type="application/x-protobuf", headers={"Content-Encoding": "gzip"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
