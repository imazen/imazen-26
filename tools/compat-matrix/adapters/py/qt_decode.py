# Qt QImageReader with autoTransform (viewer mode).
import sys
from PyQt6.QtGui import QImageReader

inp, out = sys.argv[1], sys.argv[2]
r = QImageReader(inp)
r.setAutoTransform(True)
img = r.read()
if img.isNull():
    raise SystemExit("QImageReader failed: " + r.errorString())
if not img.save(out, "PNG"):
    raise SystemExit("QImage.save failed")
