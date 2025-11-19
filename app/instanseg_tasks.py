import asyncio
import json
from pathlib import Path

import numpy as np
import openslide

from .models import Job


def generate_tiles(width: int, height: int, tile_size: int = 512, overlap: int = 64):
    """Generate tile coordinates for a WSI with overlap."""
    tiles = []
    step = tile_size - overlap
    y = 0
    while y < height:
        x = 0
        h = min(tile_size, height - y)
        while x < width:
            w = min(tile_size, width - x)
            tiles.append((x, y, w, h))
            x += step
        y += step
    return tiles


def run_instanseg_on_tile(tile_array: np.ndarray):
    """
    Run InstanSeg inference on a tile.
    
    TODO: Replace with real InstanSeg inference.
    For the take-home, this returns an empty result or a simple placeholder.
    Structure: list of polygons, each polygon is {"points": [(x1, y1), (x2, y2), ...]}
    
    Real integration would look like:
        from instanseg import InstanSeg
        model = InstanSeg()
        result = model.predict(tile_array)
        return result.polygons
    """
    # Placeholder: return empty list
    # In production, this would call the actual InstanSeg model
    return []


async def instanseg_process_wsi(job: Job, wsi_path: str):
    """Process a WSI with InstanSeg to segment cells."""
    slide = openslide.OpenSlide(wsi_path)
    try:
        width, height = slide.dimensions

        tiles = generate_tiles(width, height, tile_size=512, overlap=64)
        total_tiles = len(tiles)
        if total_tiles == 0:
            job.progress = 100.0
            return

        polygons = []

        for i, (x, y, w, h) in enumerate(tiles):
            # Read tile
            tile_img = slide.read_region((x, y), 0, (w, h))  # returns RGBA
            tile_rgb = tile_img.convert("RGB")
            tile_array = np.array(tile_rgb)

            # Run InstanSeg (placeholder)
            tile_polygons = run_instanseg_on_tile(tile_array)

            # Adjust coordinates to slide space
            for poly in tile_polygons:
                adjusted_points = []
                for px, py in poly["points"]:
                    adjusted_points.append((px + x, py + y))
                polygons.append({"points": adjusted_points})

            # Update progress
            job.progress = (i + 1) / total_tiles * 100.0

            # Yield control to event loop
            await asyncio.sleep(0)

        # Export polygons to JSON file
        out_dir = Path("results")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{job.job_id}_cells.json"
        with out_path.open("w") as f:
            json.dump({"job_id": job.job_id, "polygons": polygons}, f)
    finally:
        slide.close()


async def generate_tissue_mask(job: Job, wsi_path: str):
    """Generate a binary tissue mask from a WSI."""
    slide = openslide.OpenSlide(wsi_path)
    try:
        width, height = slide.dimensions

        tiles = generate_tiles(width, height, tile_size=512, overlap=64)
        total_tiles = len(tiles)
        if total_tiles == 0:
            job.progress = 100.0
            return

        # For simplicity, we can generate a downsampled tissue mask:
        mask_tiles = []

        for i, (x, y, w, h) in enumerate(tiles):
            tile_img = slide.read_region((x, y), 0, (w, h))
            tile_rgb = tile_img.convert("RGB")
            tile_array = np.array(tile_rgb)

            # Simple heuristic: treat non-bright pixels as tissue
            gray = tile_array.mean(axis=2)
            tissue_mask = (gray < 240).astype(np.uint8)  # 1 = tissue, 0 = background

            mask_tiles.append(
                {
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                    "mask_mean": float(tissue_mask.mean()),
                }
            )

            job.progress = (i + 1) / total_tiles * 100.0
            await asyncio.sleep(0)

        out_dir = Path("results")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{job.job_id}_tissue_mask.json"
        with out_path.open("w") as f:
            json.dump({"job_id": job.job_id, "tiles": mask_tiles}, f)
    finally:
        slide.close()
