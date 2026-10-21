"""Tile rendered slides 2x2 into contact sheets for quick visual QA.
  python sheet.py renders 3 5 6 8 ...   -> renders/sheet_1.png, sheet_2.png, ...
"""
import pathlib
import sys

from PIL import Image

src = pathlib.Path(sys.argv[1])
nums = [int(n) for n in sys.argv[2:]]
for k in range(0, len(nums), 4):
    sheet = Image.new("RGB", (1600, 900), "white")
    for j, n in enumerate(nums[k:k + 4]):
        im = Image.open(src / f"slide{n:02d}.png").convert("RGB").resize((796, 448))
        sheet.paste(im, ((j % 2) * 804, (j // 2) * 452))
    out = src / f"sheet_{k // 4 + 1}.png"
    sheet.save(out)
    print(out, nums[k:k + 4])
