# gdk-pixbuf: no EXIF orientation applied by Pixbuf.new_from_file (stored pixels —
# measured: jpeg-exif-o* all land orient1 in the matrix).
import sys
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

inp, out = sys.argv[1], sys.argv[2]
pb = GdkPixbuf.Pixbuf.new_from_file(inp)
pb.savev(out, "png", [], [])
