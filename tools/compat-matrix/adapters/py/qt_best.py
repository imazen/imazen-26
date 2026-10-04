# Qt best mode: autoTransform (EXIF) + convertToColorSpace(sRGB).
import sys
from PyQt6.QtGui import QImageReader, QColorSpace

inp, out = sys.argv[1], sys.argv[2]
r = QImageReader(inp)
r.setAutoTransform(True)
img = r.read()
if img.isNull():
    raise SystemExit("QImageReader failed: " + r.errorString())
img.convertToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
if not img.save(out, "PNG"):
    raise SystemExit("QImage.save failed")
