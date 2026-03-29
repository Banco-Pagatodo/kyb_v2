"""
Módulo para enderezar páginas de un PDF.

Este script:
1. Rota automáticamente páginas apaisadas (landscape) para que estén en vertical.
2. Detecta y corrige páginas giradas 180° mediante una heurística visual.
3. Guarda el PDF corregido.

Requisitos:
    pip install pymupdf pillow numpy
"""

import io
import sys
import fitz  # PyMuPDF
import numpy as np
from PIL import Image
import tkinter as tk
from tkinter import filedialog, messagebox


def procesar_pdf(ruta_entrada: str, ruta_salida: str, detectar_180: bool = True) -> tuple[int, int]:
    """
    Procesa un archivo PDF, corrigiendo orientación de páginas.

    Reglas:
        - Si ancho > alto: gira 90 grados (landscape → portrait).
        - Si `detectar_180` es True: aplica heurística visual para detectar
          páginas invertidas y las rota 180°.

    Args:
        ruta_entrada (str): Ruta del archivo PDF de entrada.
        ruta_salida (str): Ruta donde se guardará el PDF resultante.
        detectar_180 (bool, opcional): Activa la detección de 180°. Por defecto True.

    Returns:
        tuple[int, int]: (número de páginas giradas, número total de páginas).
    """
    doc = fitz.open(ruta_entrada)
    total = len(doc)
    cambios = 0

    for i, pagina in enumerate(doc, start=1):
        rect = pagina.rect
        ancho, alto = rect.width, rect.height
        girado = None

        # Caso 1: página horizontal
        if ancho > alto:
            pagina.set_rotation(90)
            girado = 90
            cambios += 1

        # Caso 2: detectar 180° si no es landscape
        elif detectar_180:
            try:
                pix = pagina.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                gray = img.convert("L")
                arr = np.array(gray)

                umbral = 200
                tinta = (arr < umbral).astype(np.uint8)

                mitad = tinta.shape[0] // 2
                top_sum = tinta[:mitad, :].sum()
                bottom_sum = tinta[mitad:, :].sum()

                if bottom_sum > top_sum * 1.5 and bottom_sum > 100:
                    pagina.set_rotation(180)
                    girado = 180
                    cambios += 1
            except Exception as err:
                print(
                    f"Advertencia: no se pudo analizar la página {i}: {err}",
                    file=sys.stderr
                )

        if girado:
            print(f"[{i}/{total}] Página girada {girado}°")
        else:
            print(f"[{i}/{total}] Página sin cambio")

    doc.save(ruta_salida)
    doc.close()
    return cambios, total


def elegir_y_procesar() -> None:
    """
    Abre un cuadro de diálogo para elegir un PDF y procesarlo.

    Pasos:
        1. El usuario selecciona un PDF de entrada.
        2. El usuario elige dónde guardar el PDF procesado.
        3. Se ejecuta `procesar_pdf` y se muestra un mensaje con el resultado.
    """
    root = tk.Tk()
    root.withdraw()

    ruta_entrada = filedialog.askopenfilename(
        title="Selecciona el PDF a procesar",
        filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
    )
    if not ruta_entrada:
        return

    ruta_salida = filedialog.asksaveasfilename(
        title="Guardar PDF enderezado como...",
        defaultextension=".pdf",
        filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
    )
    if not ruta_salida:
        return

    try:
        cambios, total = procesar_pdf(
            ruta_entrada,
            ruta_salida,
            detectar_180=True
        )
        messagebox.showinfo(
            "Proceso completado",
            (
                f"Documento procesado correctamente.\n"
                f"Páginas procesadas: {total}\n"
                f"Páginas giradas: {cambios}\n"
                f"Archivo guardado en:\n{ruta_salida}"
            )
        )
    except Exception as err:
        messagebox.showerror(
            "Error",
            f"Ocurrió un error al procesar el PDF:\n{err}"
        )


if __name__ == "__main__":
    elegir_y_procesar()
