from tkinter import Tk, filedialog

def seleccionar_archivo() -> str:
#Muestra un diálogo para seleccionar un PDF o imagen."""
    root = Tk()
    root.withdraw()
    archivo = filedialog.askopenfilename(
        title="Selecciona el documento (PDF o Imagen)",
        filetypes=[("Archivos soportados", "*.pdf *.png *.jpg *.jpeg")]
    )
    root.destroy()
    return archivo
