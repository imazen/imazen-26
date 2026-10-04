# Pillow viewer mode: exif_transpose (what most apps do) + ICC honoured by
# Pillow only when converting modes — keep native output but apply EXIF.
import sys
from PIL import Image, ImageOps

inp, out = sys.argv[1], sys.argv[2]
img = Image.open(inp)
img = ImageOps.exif_transpose(img)
if img.mode == "P":
    img = img.convert("RGBA")
img.save(out, "PNG")
