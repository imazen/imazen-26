#!/usr/bin/env python3
"""Visual screening grades for squintly stimulus candidates (2026-09-22 contact-sheet pass).

Grades: A engaging (lead candidate) · B acceptable · C dull for paid viewing (only if the
stratum needs it) · X exclude from paid stimuli (reason given). Screened by eye from
200px pristine_downscale thumbnails of the png-v3 renders; the 25 EPA pages were graded
from their descriptors (the renderer refused them, see SET.md). AI strata (9000/9094/9226)
are excluded wholesale, per squintly's own reasoning in build_demo_corpus.py.
"""

DEFAULT = {  # folder -> (grade, note)
    "1000": ("A", ""), "1200": ("A", ""), "1400": ("A", ""), "1600": ("A", ""),
    "2000": ("A", "professional portrait"), "2200": ("B", ""), "2400": ("B", ""),
    "3000": ("B", ""), "3300": ("B", ""), "5000": ("B", "map/brochure"),
    "5200": ("C", "report text/table page"), "5300": ("C", "report text/table page"),
    "6000": ("C", "patent text page"), "6600": ("A", "illustrated plate"),
    "6800": ("C", "manuscript text page"), "7000": ("C", "synthetic line test"),
    "8000": ("X", "license: screenshot-unverified (third-party content)"),
    "8100": ("C", "web page, text-dominant"),
    "9000": ("X", "AI-generated (excluded by squintly design)"),
    "9094": ("X", "AI-generated (excluded by squintly design)"),
    "9226": ("X", "AI-generated (excluded by squintly design)"),
}
def ids(s):
    out = []
    for part in s.split():
        if "-" in part:
            a, b = part.split("-"); out += [f"{i:04d}" for i in range(int(a), int(b) + 1)]
        else:
            out.append(part)
    return out
OVR = {}
def put(idlist, grade, note):
    for i in ids(idlist): OVR[i] = (grade, note)

# --- 1000 general (screened) ---
put("1008 1011 1028 1033 1035 1041 1044 1055 1065", "B", "")
put("1063", "C", "photo of a screen (moire), unappealing")
put("1048", "X", "private individuals as subject (no model release)")
put("1012-1018", "A", "saturated art glass (chroma stress)")
put("1019 1020", "A", "blue sky gradient (banding stress)")
put("1069 1071 1046 1002 1057", "A", "night / low light (shadow blocking)")
put("1004", "A", "saturated colour swatches (chroma subsampling)")
put("1034", "A", "saturated flat colour steps")
# --- 1200 interiors ---
put("1207 1217 1218 1219 1221 1225", "B", "plain hotel/kitchen interior")
put("1211-1214", "A", "ornate painted ceiling (fine detail)")
put("1227-1231 1235-1239 1244", "A", "Gaudi interior (texture, coloured glass)")
put("1232-1234", "A", "cathedral interior, stained glass")
# --- 1400 nature ---
put("1400 1446 1447 1456 1459 1463 1466 1468 1487 1500 1501 1541", "B", "")
put("1425", "C", "fog, very low contrast")
put("1552 1556", "C", "dark / indistinct")
put("1417 1539", "X", "private individuals as subject (no model release)")
put("1449", "B", "124 MP panorama: exceeds zenpng default 120 MP decode limit")
put("1416 1470 1474-1478 1489-1491 1493 1549 1550", "A", "sunset sky gradient (banding stress)")
put("1442 1443 1553", "A", "aurora, dark sky gradient")
put("1502 1505-1509 1546 1545", "A", "ice cave / cave, smooth blue gradients")
put("1418-1422 1427-1438 1460 1464 1503 1510-1528 1531-1537 1540 1542-1544 1547 1548 1555", "A", "flowers / foliage (saturated reds+purples, fine texture)")
put("1401 1402 1406 1407 1409-1415 1426 1450-1454 1457 1480-1486 1488 1492 1494-1499 1504 1527", "A", "landscape / seascape (sky, water, texture)")
# --- 1600 food ---
put("1608 1614 1617 1630 1631 1634 1635 1636 1640", "B", "table spread / plain plate")
put("1600-1607 1609-1613 1615 1616 1618-1629 1632 1633 1637-1639", "A", "food (texture, saturated colour)")
# --- 2200 renders / 2400 textures ---
put("2200 2202 2205 2208 2212", "A", "3D render, smooth gradients")
put("2203 2204 2210", "C", "high-contrast moire pattern (eye strain)")
put("2400 2404 2406 2408", "A", "texture, attractive")
# --- 3000 AIC / 3300 Met ---
put("3002 3004 3008 3009 3010 3013 3014", "A", "artwork reproduction")
put("3005 3006", "A", "woodblock print; Adobe RGB source (no CICP; pristine route refuses it)")
put("3300 3303 3304 3306 3309 3310 3315 3316 3317 3318 3320 3322 3323", "A", "artwork reproduction")
put("3311 3312 3313 3319 3321", "C", "dull grey object / faint drawing")
# --- 5000 NPS ---
put("5000 5002 5003 5026 5027 5028 5030", "A", "colour brochure: photos + map + text")
put("5032-5058", "C", "grayscale brochure/map (duplicative of colour set)")
# --- 5200 EPA (graded from descriptors) ---
put("5200 5202 5205 5208 5210 5211 5214 5217 5219 5220 5221 5222 5223", "B", "report figure / map page")
# --- 5300 NOAA ---
put("5302 5305 5308 5311 5314 5317 5320 5323 5326 5329 5332 5335 5338 5341", "B", "report cover with satellite image")
put("5300 5301 5313 5316 5325 5328", "B", "report chart page")
# --- 6000 patents: drawing sheets are line art worth a slot ---
put("6001-6007 6030-6036 6060-6066 6089 6092 6095 6099 6100 6106 6110", "B", "patent drawing sheet (line art)")
# --- 6600 IA illustrations ---
put("6608-6611", "B", "woodblock book spread (line art, paper texture)")
put("6618-6622 6628", "B", "pale botanical plate (low contrast)")
# --- 6800 IA text ---
put("6800 6806 6807 6808 6809 6835", "B", "title page / illustrated text page")
put("6058 6088 6825 6826", "X", "blank page (paper show-through only)")
# --- 7000 plots ---
put("7022-7036 7076-7090", "B", "saturated flat polygons (chroma edges)")
put("7037-7047 7091-7125", "B", "chart / heatmap")
# --- 8100 web ---
put("8103 8162 8222 8274 8333 8396 8397", "X", "error page (Access Denied, capture was bot-blocked)")
put("8113 8114 8171 8172 8230 8231 8282 8283 8341 8342 8414 8415", "C", "lkml 'Not Found' page + link list")
put("8285 8289 8417 8423 8425", "X", "sparse or broken-layout capture (mostly empty frame)")
put("8101 8104 8105 8106 8116 8117 8120-8126 8128 8129 8131-8134 8136 8138-8143 8145 8244-8246 8248-8261 8263 8264 8267 8270 8271 8273 8275 8286-8288 8290 8291 8389 8391-8395 8398 8400 8402 8404 8406 8407 8419 8421 8422 8426-8431 8434", "B", "web page with photos / hero image")


def grade_of(i: str, folder: str) -> tuple[str, str]:
    """(grade, note) for a corpus id: the per-id override, else the default of its class
    folder (`folder` = the folder name's 4-digit block, e.g. "1400" for ids 1400-1556)."""
    return OVR.get(i, DEFAULT[folder[:4]])
