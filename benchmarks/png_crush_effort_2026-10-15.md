# PNG crush effort sweep (2026-10-15)

`tools/png-crush` (5518b98; zenpng main with zenzop, every imazen crate at main) was run on
six corpus PNGs at five zenpng efforts. Each output was decoded again and matched the
source pixels exactly; ICC, EXIF and `pHYs` were carried over.

**Command:** `png-crush <effort> <list> <out>`. Eight processes ran at once under run-heavy
on dev: five efforts on the four small files, three on the two large ones. Total 248 s,
peak RSS 2.41 GiB. Times are with that contention, so read them relative to each other.

Percentages are the saving against the published file.

| id | content | MP | published | e13 | e19 | e22 | e24 | e27 (Crush) |
|---|---|--:|--:|---|---|---|---|---|
| 1550 | phone photo saved as PNG | 1.6 | 1.76 MB | 8.4%, 0.2 s | 14.1%, 4.8 s | 14.2%, 6.5 s | 14.2%, 19.5 s | 14.5%, 84.7 s |
| 8104 | web capture | 1.3 | 0.76 MB | 6.8%, 0.3 s | 9.0%, 3.4 s | 9.5%, 4.8 s | 9.6%, 15.0 s | 10.3%, 85.6 s |
| 9227 | AI product image | 1.6 | 1.21 MB | 15.1%, 0.3 s | 16.8%, 2.3 s | 17.9%, 3.4 s | 17.9%, 11.0 s | 18.6%, 73.7 s |
| 7010 | plot | 1.0 | 0.07 MB | 40.2%, 0.0 s | 44.3%, 0.2 s | 45.7%, 0.6 s | 45.7%, 1.2 s | 46.9%, 4.1 s |
| 5001 | NPS brochure page | 34.8 | 10.63 MB | 23.7%, 0.9 s | 25.4%, 59.6 s | 27.0%, 86.9 s | — | — |
| 6610 | Internet Archive plate scan | 29.8 | 33.05 MB | 15.0%, 1.3 s | 22.7%, 81.1 s | 23.1%, 118.5 s | — | — |

On the four small files, Crush (e27) saves 0.3–1.2 points more than e22 and takes 7–18× as
long. e22 saves 0.1–1.6 points more than e19 at about 1.4× the time. e24 adds nothing over
e22 on these files. The two large files weren't run at e24 or e27.

The 1,610 PNGs in the corpus as of 2026-10-15 total 5,871 MP and 4.06 GB. A full run at a
chosen effort has not been measured.
