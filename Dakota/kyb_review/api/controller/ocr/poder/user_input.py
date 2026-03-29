# user_input.py

import re

def pedir_datos_usuario() -> dict:
    # Solicita los datos clave del Poder Notarial al usuario
    datos = {}
    datos["ocupacion"] = input("Ocupación: ").strip()
    datos["nacionalidad"] = input("Nacionalidad: ").strip()
    datos["pais_nacimiento"] = input("País de nacimiento: ").strip()
    datos["telefono"] = input("Teléfono (opcional): ").strip()
    datos["correo_electronico"] = input("Correo electrónico (opcional): ").strip()
    return datos
