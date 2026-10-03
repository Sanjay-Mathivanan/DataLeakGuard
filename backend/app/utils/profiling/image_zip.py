import zipfile
from typing import Dict, Any
from PIL import Image
import os

def profile_image_zip(file_path: str) -> Dict[str, Any]:
    """
    Profile a ZIP file containing images.
    Returns dict with image count, format, size stats.
    """
    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'}
            image_files = [
                f for f in zf.namelist()
                if not f.endswith('/') and
                   os.path.splitext(f)[1].lower() in image_extensions
            ]
            if not image_files:
                return {"error": "No image files found in ZIP"}

            # We'll examine first few images for basic stats
            widths = []
            heights = []
            formats = set()
            limit = min(5, len(image_files))  # sample up to 5 images
            for fname in image_files[:limit]:
                with zf.open(fname) as img_file:
                    with Image.open(img_file) as img:
                        widths.append(img.width)
                        heights.append(img.height)
                        formats.add(img.format)

            profile = {
                "image_count": len(image_files),
                "format": list(formats)[0] if len(formats) == 1 else "mixed",
                "width_min": min(widths) if widths else None,
                "width_max": max(widths) if widths else None,
                "height_min": min(heights) if heights else None,
                "height_max": max(heights) if heights else None,
                "sampled_images": limit
            }
            return profile
    except Exception as e:
        return {"error": f"Failed to profile ZIP: {str(e)}"}