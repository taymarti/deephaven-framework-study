"""Gather the final diagram screenshots (light theme) into deck/assets with readable names."""
import base64
import json
import pathlib
import re
import shutil
import sys

from PIL import Image

TR = pathlib.Path(r"C:\Users\tc-ma\.claude\projects\C--Users-tc-ma-dev-deephaven-compare"
                  r"\51f8dfb8-0305-46fd-a74d-a949b9c07d8e\tool-results")
OUT = pathlib.Path(__file__).with_name("assets")
OUT.mkdir(exist_ok=True)

EXISTING = {  # final screenshots already on disk
    "cycle": "vmkdlc", "hybrid": "orui19", "worker_anatomy": "n422sy", "tickets": "9k55tf",
    "barrage": "g71a5l", "two_clocks": "9a03kh", "space": "jzqtko", "hosting": "ij91v1",
    "embedded": "6pc1zw",
}
for name, tag in EXISTING.items():
    src = next(TR.glob(f"*-{tag}.png"))
    shutil.copyfile(src, OUT / f"{name}.png")

# Fresh screenshots saved as JSON by the docs reader: decode, then name by argv order.
for path, name in zip(sys.argv[1::2], sys.argv[2::2]):
    raw = pathlib.Path(path).read_text(encoding="utf-8")
    m = re.search(r'"png"\s*:\s*"([A-Za-z0-9+/=]+)"', raw) or re.search(r"([A-Za-z0-9+/]{2000,}={0,2})", raw)
    (OUT / f"{name}.png").write_bytes(base64.b64decode(m.group(1)))

for p in sorted(OUT.glob("*.png")):
    with Image.open(p) as im:
        print(f"{p.name:24} {im.size[0]}x{im.size[1]}")
