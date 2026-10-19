"""端到端冒烟测试：生成一张模拟报告图，调用本机 /api/extract 验证视觉识别。

用途：更换视觉模型或修改识别逻辑后，快速验证整条链路是否可用。
运行前请先启动后端（start_all.bat）。
"""

import asyncio
from io import BytesIO

import httpx
from PIL import Image, ImageDraw, ImageFont

LINES = [
    "Clinical Laboratory Report",
    "",
    "Albumin (ALB)       45.0 g/L",
    "Creatinine (CREA)   80 umol/L",
    "Glucose (GLU)       5.5 mmol/L",
    "CRP                  3.0 mg/L",
    "Lymphocyte% (LYM%)  30 %",
    "MCV                 90 fL",
    "RDW-CV              13.0 %",
    "ALP                 80 U/L",
    "WBC                  6.0 10^9/L",
]


def _make_image() -> bytes:
    img = Image.new("RGB", (1200, 620), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    y = 40
    for line in LINES:
        draw.text((60, y), line, fill="black", font=font)
        y += 52
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def main() -> None:
    payload = _make_image()
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "http://127.0.0.1:8000/api/extract",
            files=[("files", ("report.png", payload, "image/png"))],
        )
    print("HTTP", resp.status_code)
    print(resp.text[:4000])


if __name__ == "__main__":
    asyncio.run(main())
