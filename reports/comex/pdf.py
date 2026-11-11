"""Conversion du COMEX PowerPoint en PDF avec LibreOffice (mode sans interface).

LibreOffice et la police Montserrat du modèle sont installés dans l'image Docker (Dockerfile).
Hors Docker, le chemin de « soffice » peut être donné par la variable LIBREOFFICE_BIN.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

TIMEOUT = 180  # secondes


class PdfUnavailable(Exception):
    """LibreOffice absent, ou conversion en échec : le PowerPoint reste téléchargeable."""


def soffice_path():
    candidates = [os.environ.get("LIBREOFFICE_BIN"), shutil.which("soffice"), shutil.which("libreoffice"),
                  r"C:\Program Files\LibreOffice\program\soffice.exe"]
    for path in candidates:
        if path and Path(path).exists():
            return path
    return None


def pptx_to_pdf(content):
    """Renvoie le PDF (octets) du PowerPoint `content`. Lève PdfUnavailable en cas d'échec."""
    binary = soffice_path()
    if not binary:
        raise PdfUnavailable("LibreOffice introuvable")
    with tempfile.TemporaryDirectory(prefix="comex-") as tmp:
        tmp = Path(tmp)
        source = tmp / "comex.pptx"
        source.write_bytes(content)
        # Profil LibreOffice propre à chaque conversion : deux exports simultanés ne se bloquent pas.
        profile = (tmp / "profil").as_uri()
        cmd = [binary, f"-env:UserInstallation={profile}", "--headless", "--norestore",
               "--convert-to", "pdf", "--outdir", str(tmp), str(source)]
        try:
            subprocess.run(cmd, check=True, timeout=TIMEOUT, capture_output=True,
                           env={**os.environ, "HOME": str(tmp)})
        except (OSError, subprocess.SubprocessError) as e:
            raise PdfUnavailable(str(e)) from e
        pdf = tmp / "comex.pdf"
        if not pdf.exists() or not pdf.stat().st_size:
            raise PdfUnavailable("aucun PDF produit")
        return pdf.read_bytes()
