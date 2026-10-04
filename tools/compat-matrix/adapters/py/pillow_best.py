# Pillow best mode: EXIF transpose + lcms2 -> sRGB when the file has ICC.
import io, sys
from PIL import Image, ImageOps, ImageCms

inp, out = sys.argv[1], sys.argv[2]
img = Image.open(inp)
icc = img.info.get("icc_profile")
img = ImageOps.exif_transpose(img)
if img.mode == "P":
    img = img.convert("RGBA")
if icc:
    src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
    dst = ImageCms.createProfile("sRGB")
    rgb = img.convert("RGB")
    out_img = ImageCms.profileToProfile(
        rgb, src, dst, outputMode="RGB",
        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)
    if img.mode == "RGBA":
        out_img = out_img.convert("RGBA")
        out_img.putalpha(img.getchannel("A"))
    img = out_img
img.save(out, "PNG")
