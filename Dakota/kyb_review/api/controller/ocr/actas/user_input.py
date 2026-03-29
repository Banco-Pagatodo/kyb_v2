import re

def pedir_datos_usuario() -> dict:
#Solicita los datos clave del acta constitutiva al usuario."""
    datos = {}
    def validar_fecha(f): return bool(re.match(r"^\d{2}/\d{2}/\d{4}$", f))

    datos["numero_escritura_poliza"] = input("Número escritura/póliza: ").strip()
    while True:
        f = input("Fecha Constitución (dd/mm/aaaa): ").strip()
        if validar_fecha(f): datos["fecha_constitucion"] = f; break
        print("Formato inválido")
    datos["folio_mercantil"] = input("Folio Mercantil: ").strip()
    while True:
        f = input("Fecha Expedición (dd/mm/aaaa): ").strip()
        if validar_fecha(f): datos["fecha_expedicion"] = f; break
        print("Formato inválido")
    datos["numero_notaria_correduria"] = input("Número Notaría/Correduría: ").strip()
    datos["estado_notaria_correduria"] = input("Estado Notaría/Correduría: ").strip()
    print("Nombre fedatario:")
    datos["primer_nombre_fedatario"] = input("Primer nombre: ").strip()
    datos["segundo_nombre_fedatario"] = input("Segundo nombre: ").strip()
    datos["primer_apellido_fedatario"] = input("Primer apellido: ").strip()
    datos["segundo_apellido_fedatario"] = input("Segundo apellido: ").strip()
    return datos
