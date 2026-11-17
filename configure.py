import getpass
import os
from pathlib import Path
import tempfile


def main():
    token = getpass.getpass("Dán token Discord rồi nhấn Enter (ký tự được ẩn): ").strip()
    if not token or any(character.isspace() for character in token):
        raise SystemExit("Token trống hoặc chứa khoảng trắng. Hãy nhập lại.")
    directory = Path.home() / ".config/capri-anthem"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    descriptor, temporary_path = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(token + "\n")
        os.replace(temporary_path, directory / "token")
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
    print("Đã lưu token. Chạy ~/capri-anthem/anthem start để bật bot.")


if __name__ == "__main__":
    main()
