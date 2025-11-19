import asyncio
import json
import logging
from pathlib import Path

import numpy as np
import openslide
from skimage.measure import regionprops

try:
    from instanseg.inference_class import InstanSeg
except Exception as exc:  # pragma: no cover - depends on runtime env
    InstanSeg = None
    logging.warning("InstanSeg import failed; falling back to stubbed inference: %s", exc)

from .models import Job

TILE_SIZE = 512
TILE_OVERLAP = 64
TISSUE_INTENSITY_THRESHOLD = 240
MIN_TISSUE_RATIO = 0.05
MAX_CONCURRENT_INFERENCE = 4

_instanseg_model = None


def _get_instanseg_model():
    """Lazily construct the InstanSeg model."""
    global _instanseg_model
    if _instanseg_model is not None:
        return _instanseg_model
    if InstanSeg is None:
        return None
    try:
        _instanseg_model = InstanSeg(
            "brightfield_nuclei",
            image_reader="tiffslide",
            verbosity=0,
        )
    except Exception as exc:  # pragma: no cover - depends on runtime env
        logging.error("Unable to initialize InstanSeg, continuing with stub: %s", exc)
        _instanseg_model = None
    return _instanseg_model


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
    Run InstanSeg on a single RGB tile and return a list of polygons.

    Call eval_small_image() to get an instance label mask, then convert each
    labeled region into a simple bounding-box polygon:
      [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    Returns:
        List[dict]: [{"points": [(x1, y1), ...], "label": int, "area": float}, ...]
    """
    model = _get_instanseg_model()
    if model is None:
        return []

    pixel_size = 0.25

    try:
        labeled_output, _ = model.eval_small_image(
            tile_array,
            pixel_size,
        )
    except Exception as exc:
        logging.error("InstanSeg inference failed; skipping tile: %s", exc)
        return []

    labeled_np = labeled_output.detach().cpu().numpy()
    labels = labeled_np[0, -1, :, :].astype(np.int32)

    polys = []
    if labels.max() == 0:
        return polys

    for region in regionprops(labels):
        y0, x0, y1, x1 = region.bbox

        points = [
            (int(x0), int(y0)),
            (int(x1), int(y0)),
            (int(x1), int(y1)),
            (int(x0), int(y1)),
        ]

        polys.append(
            {
                "points": points,
                "label": int(region.label),
                "area": float(region.area),
            }
        )

    return polys


def contains_tissue(tile_array: np.ndarray) -> bool:
    """Quick heuristic to skip background tiles."""
    gray = tile_array.mean(axis=2)
    tissue_ratio = np.mean(gray < TISSUE_INTENSITY_THRESHOLD)
    return tissue_ratio >= MIN_TISSUE_RATIO


async def instanseg_process_wsi(job: Job, wsi_path: str):
    """Process a WSI with InstanSeg to segment cells."""
    slide = openslide.OpenSlide(wsi_path)
    try:
        width, height = slide.dimensions

        tiles = generate_tiles(width, height, tile_size=TILE_SIZE, overlap=TILE_OVERLAP)
        total_tiles = len(tiles)
        if total_tiles == 0:
            job.progress = 100.0
            return

        logging.info(f"Processing {total_tiles} tiles for job {job.job_id}")

        polygons = []
        tiles_processed = 0
        pending_tasks = []

        async def infer_tile(tile_array, meta):
            """Run InstanSeg inference on a tile in executor."""
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, run_instanseg_on_tile, tile_array)
                return meta, result, None
            except Exception as exc:
                logging.error(f"Tile inference failed at {meta}: {exc}")
                return meta, [], exc

        async def drain_pending(force: bool = False):
            """Process completed inference tasks."""
            nonlocal pending_tasks, tiles_processed
            if not pending_tasks:
                return
            
            # Wait for tasks to complete
            if force:
                # Wait for all to complete
                done_set, pending_set = await asyncio.wait(
                    pending_tasks,
                    return_when=asyncio.ALL_COMPLETED,
                )
            else:
                # Wait for at least one to complete
                done_set, pending_set = await asyncio.wait(
                    pending_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            
            # Process completed tasks
            for task in done_set:
                try:
                    # Task is already done, get result directly
                    meta, tile_polygons, error = task.result()
                    x, y = meta["x"], meta["y"]
                    
                    if error is None:
                        # Add polygons to results
                        for poly in tile_polygons:
                            adjusted_points = [(px + x, py + y) for (px, py) in poly["points"]]
                            polygons.append(
                                {
                                    "points": adjusted_points,
                                    "label": poly.get("label"),
                                    "area": poly.get("area"),
                                    "tile_origin": {"x": x, "y": y},
                                }
                            )
                    # Count as processed even if it failed (we skip it)
                    tiles_processed += 1
                    job.progress = min(tiles_processed / total_tiles * 100.0, 100.0)
                except Exception as exc:
                    logging.error(f"Error processing completed tile task: {exc}")
                    tiles_processed += 1
                    job.progress = min(tiles_processed / total_tiles * 100.0, 100.0)
            
            # Update pending list (convert set back to list)
            pending_tasks = list(pending_set)

        for (x, y, w, h) in tiles:
            try:
                # Read tile from the WSI
                tile_img = slide.read_region((x, y), 0, (w, h))  # returns RGBA
                tile_rgb = tile_img.convert("RGB")
                tile_array = np.array(tile_rgb)

                # Quick tissue check to skip background tiles
                if not contains_tissue(tile_array):
                    tiles_processed += 1
                    job.progress = min(tiles_processed / total_tiles * 100.0, 100.0)
                    # Free memory immediately
                    del tile_array, tile_rgb, tile_img
                    continue

                # Submit for inference
                pending_tasks.append(
                    asyncio.create_task(
                        infer_tile(
                            tile_array,
                            {"x": x, "y": y},
                        )
                    )
                )
                
                # Free tile memory after submitting (task holds reference)
                del tile_array, tile_rgb, tile_img

                # Drain when we hit the concurrency limit
                if len(pending_tasks) >= MAX_CONCURRENT_INFERENCE:
                    await drain_pending()

            except Exception as exc:
                logging.error(f"Error processing tile at ({x}, {y}): {exc}")
                tiles_processed += 1
                job.progress = min(tiles_processed / total_tiles * 100.0, 100.0)

        # Wait for all remaining tasks
        await drain_pending(force=True)

        logging.info(f"Job {job.job_id} completed: {len(polygons)} polygons from {tiles_processed} tiles")

        # Export polygons to JSON file
        out_dir = Path("results")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{job.job_id}_cells.json"
        with out_path.open("w") as f:
            json.dump({"job_id": job.job_id, "polygons": polygons}, f)
    except Exception as exc:
        logging.error(f"Fatal error processing WSI {wsi_path} for job {job.job_id}: {exc}", exc_info=True)
        raise
    finally:
        slide.close()


async def generate_tissue_mask(job: Job, wsi_path: str):
    """Generate a binary tissue mask from a WSI."""
    slide = openslide.OpenSlide(wsi_path)
    try:
        width, height = slide.dimensions

        tiles = generate_tiles(width, height, tile_size=TILE_SIZE, overlap=TILE_OVERLAP)
        total_tiles = len(tiles)
        if total_tiles == 0:
            job.progress = 100.0
            return

        mask_tiles = []

        for i, (x, y, w, h) in enumerate(tiles):
            tile_img = slide.read_region((x, y), 0, (w, h))
            tile_rgb = tile_img.convert("RGB")
            tile_array = np.array(tile_rgb)

            # Simple heuristic tissue mask
            gray = tile_array.mean(axis=2)
            tissue_mask = (gray < 240).astype(np.uint8)

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
