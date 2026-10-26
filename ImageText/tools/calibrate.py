"""Prepare readable visual calibration sheets; makes no text judgments."""
from pathlib import Path
import json
from PIL import Image, ImageDraw, ImageOps

project = Path(__file__).resolve().parents[2]
source = project / 'ImageText/export_crunch_20261027'
out = project / 'ImageText/calibration_20261027'
out.mkdir(parents=True, exist_ok=True)
all_images = sorted(source.glob('*.png'))
keywords = ['logo', 'title', 'font_texture', 'journal', 'note', 'letter', 'sign', 'keyboard', 'menu', 'button']
chosen = []
for word in keywords:
    candidates = [p for p in all_images if word in p.name.lower()]
    for p in candidates[:4]:
        if p not in chosen:
            chosen.append(p)
for p in all_images[::max(1, len(all_images)//15)]:
    if len(chosen) >= 36:
        break
    if p not in chosen:
        chosen.append(p)
rows = []
for page_number in range(0, len(chosen), 6):
    page = Image.new('RGB', (1600, 1200), (220, 220, 220))
    draw = ImageDraw.Draw(page)
    for position, path in enumerate(chosen[page_number:page_number+6]):
        ordinal = page_number + position + 1
        with Image.open(path) as im:
            rgba = im.convert('RGBA')
            bg = Image.new('RGBA', rgba.size, (70, 70, 70, 255))
            bg.alpha_composite(rgba)
            preview = ImageOps.contain(bg.convert('RGB'), (780, 350))
            x, y = position % 2 * 800 + 10, position // 2 * 400 + 10
            draw.text((x, y), f'{ordinal}: {path.name[:87]}\n{im.width} x {im.height}', fill='black')
            page.paste(preview, (x, y+40))
            rows.append({'id': ordinal, 'file': path.name, 'size': list(im.size)})
    page.save(out/f'contact-{page_number//6+1}.png')
(out/'index.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
print(json.dumps({'images':len(rows), 'pages':(len(rows)+5)//6, 'directory':str(out)}))
