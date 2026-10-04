"""生成应用图标：小红书红圆角方块 + 白色相框图案。"""
from PIL import Image, ImageDraw

S = 4  # 4x 超采样抗锯齿
size = 256 * S
img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

# 圆角方块 + 对角渐变 (#ff2442 -> #d61a56)
top, bottom = (255, 36, 66), (198, 20, 78)
grad = Image.new("RGBA", (size, size))
gd = ImageDraw.Draw(grad)
for y in range(size):
    t = y / size
    color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
    gd.line([(0, y), (size, y)], fill=color)
mask = Image.new("L", (size, size), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=56 * S, fill=255)
img.paste(grad, (0, 0), mask)

draw = ImageDraw.Draw(img)
white = (255, 255, 255, 255)
# 相框：白色圆角矩形边框
draw.rounded_rectangle(
    [58 * S, 74 * S, 198 * S, 182 * S], radius=18 * S, outline=white, width=12 * S
)
# 太阳
cx, cy, r = 96 * S, 112 * S, 13 * S
draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=white)
# 山：两座三角
draw.polygon(
    [(74 * S, 170 * S), (112 * S, 118 * S), (150 * S, 170 * S)], fill=white
)
draw.polygon(
    [(118 * S, 170 * S), (150 * S, 128 * S), (184 * S, 170 * S)], fill=white
)
# 实况圆点（右上角小圆，代表 Live）
lx, ly, lr = 186 * S, 78 * S, 17 * S
draw.ellipse([lx - lr, ly - lr, lx + lr, ly + lr], fill=white, outline=None)
draw.ellipse(
    [lx - lr + 6 * S, ly - lr + 6 * S, lx + lr - 6 * S, ly + lr - 6 * S],
    fill=(198, 20, 78, 255),
)

img = img.resize((256, 256), Image.LANCZOS)
img.save("icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save("icon.png")
print("icon.ico 生成完毕")
