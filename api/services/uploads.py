"""Validacion y procesamiento de imagenes subidas."""

import os

# Firmas de los formatos de imagen permitidos.
_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_GIF87 = b"GIF87a"
_GIF89 = b"GIF89a"


def is_imagen_valida(file_storage):
    """Devuelve True si el stream empieza con una firma de PNG/JPEG/GIF."""
    if not file_storage:
        return False

    stream = file_storage.stream
    pos = stream.tell()
    header = stream.read(12)
    stream.seek(pos)

    is_webp = header.startswith(b"RIFF") and header[8:12] == b"WEBP"

    return (
        header.startswith(_PNG)
        or header.startswith(_JPEG)
        or header.startswith(_GIF87)
        or header.startswith(_GIF89)
        or is_webp
    )


def save_imagen_optimizada(file_storage, dest_dir, base_name, max_dim=1600, quality=82):
    """Redimensiona y convierte a WebP. Devuelve el nombre de archivo final.

    base_name: nombre sin extension. Si el origen es GIF animado se guarda tal cual
    para preservar la animacion.
    """
    from PIL import Image, ImageOps

    stream = file_storage.stream
    stream.seek(0)
    img = Image.open(stream)

    if getattr(img, "is_animated", False):
        ext = (file_storage.filename.rsplit(".", 1)[-1] or "gif").lower()
        final = f"{base_name}.{ext}"
        stream.seek(0)
        with open(os.path.join(dest_dir, final), "wb") as f:
            f.write(stream.read())
        return final

    img = ImageOps.exif_transpose(img)
    img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")

    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)

    final = f"{base_name}.webp"
    img.save(os.path.join(dest_dir, final), "WEBP", quality=quality, method=6)
    return final
