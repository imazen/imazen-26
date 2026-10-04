# OpenCV: cv2.imread ignores ICC entirely (BGR, untagged output).
# Default mode (IMREAD_COLOR) applies EXIF orientation; 'unchanged' mode
# (IMREAD_UNCHANGED) skips it by design and keeps alpha/extra channels.
import sys
import cv2

inp, out, mode = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "color")
flag = cv2.IMREAD_UNCHANGED if mode == "unchanged" else cv2.IMREAD_COLOR
img = cv2.imread(inp, flag)
if img is None:
    raise SystemExit("cv2.imread returned None")
cv2.imwrite(out, img)
