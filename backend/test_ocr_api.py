import os
import subprocess
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont


PORT = 5001
BACKEND_URL = f"http://127.0.0.1:{PORT}/api/extract-text"
PROJECT_ROOT = Path(__file__).resolve().parent


def create_test_image(path: Path) -> None:
    img = Image.new("RGB", (600, 220), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype("C:/Windows/Fonts/calibri.ttf", 72)
    draw.text((40, 60), "HELLO OCR", fill="black", font=font)
    img.save(path)


def wait_for_server(url: str, timeout: int = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for server at {url}")


if __name__ == "__main__":
    image_path = PROJECT_ROOT / "sample_ocr.png"
    create_test_image(image_path)

    env = os.environ.copy()
    env["PORT"] = str(PORT)

    proc = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "app.py")],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )

    try:
        wait_for_server(f"http://127.0.0.1:{PORT}/api/health")

        with open(image_path, "rb") as image_file:
            response = requests.post(
                BACKEND_URL,
                files={"image": (image_path.name, image_file, "image/png")},
                timeout=30,
            )

        print("Status:", response.status_code)
        print("Body:", response.text)

        if not response.ok:
            raise SystemExit(1)

        payload = response.json()
        print("Detected text:", payload.get("text"))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)

        if image_path.exists():
            image_path.unlink()
