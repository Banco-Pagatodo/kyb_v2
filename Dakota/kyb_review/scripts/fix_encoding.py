"""
Script para reparar el mojibake en test_document_identifier_agent.py.
Las secuencias mojibake ocurren cuando bytes UTF-8 son interpretados como Latin-1/CP1252.

Por ejemplo: Ó (U+00D3) en UTF-8 = bytes 0xC3 0x93
Si esos bytes se leen como Latin-1: Ã (0xC3) + " (0x93 en CP1252 = U+201C)
Resultado en pantalla: Ã"  (mojibake)

Solución: Para cada carácter en el archivo, intentar encode(latin-1) para obtener
los bytes originales, luego decode(utf-8) para recuperar el carácter correcto.
"""

filepath = r"c:\Users\aperez\OneDrive - IBERTEL\AI Engineering\BPT\Proyectos\1. KYB\Agents\Dakota\kyb_review\tests\test_document_identifier_agent.py"

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

print(f"File length: {len(content)} chars")

# Repair mojibake by processing the content as latin-1 encoded bytes re-decoded as UTF-8
# Strategy: encode as latin-1 (which preserves all byte values 0x00-0xFF)
# then decode the resulting bytes as UTF-8
# This reverses the double-encoding

# First, check if it's safe
try:
    as_bytes = content.encode('latin-1', errors='strict')
    print("latin-1 encode: OK")
    fixed = as_bytes.decode('utf-8', errors='strict')
    print("utf-8 decode: OK")
except UnicodeDecodeError as e:
    print(f"Strict UTF-8 decode failed: {e}")
    # Use a targeted approach - only fix known mojibake patterns
    as_bytes = content.encode('latin-1', errors='replace')
    fixed = as_bytes.decode('utf-8', errors='replace')
    print("Used replace mode")
except UnicodeEncodeError as e:
    print(f"Latin-1 encode failed at: {e}")
    # Some chars are already proper unicode (not mojibake)
    # Use selective replacement for known Spanish mojibake patterns
    mojibake_map = {
        'Ã¡': 'á', 'Ã©': 'é', 'Ã­': 'í', 'Ã³': 'ó', 'Ãº': 'ú',
        '\u00c3\u0081': 'Á', '\u00c3\u0089': 'É', '\u00c3\u008d': 'Í',
        '\u00c3\u0093': 'Ó', '\u00c3\u009a': 'Ú',
        'Ã±': 'ñ', '\u00c3\u0091': 'Ñ',
        'Ã¼': 'ü', '\u00c3\u009c': 'Ü',
        '\u00c3\u00a9': 'é',
        # CP1252 specific
        'Ã\u201c': 'Ó',   # Ã + left double quotation = Ó
        'Ã\u2018': 'Á',   # Ã + left single quotation = Á
    }
    fixed = content
    for bad, good in mojibake_map.items():
        fixed = fixed.replace(bad, good)
    print(f"Used selective replacement, {sum(content.count(b) for b in mojibake_map)} chars fixed")

# Verify the fix looks right
idx = fixed.find('CONSTANCIA')
if idx >= 0:
    print(f"\nSample after fix: {repr(fixed[idx:idx+40])}")
else:
    # try lowercase
    idx = fixed.lower().find('constancia')
    if idx >= 0:
        print(f"\nSample (ci) after fix: {repr(fixed[idx:idx+40])}")

idx2 = fixed.find('COMISI')
if idx2 >= 0:
    print(f"COMISI sample: {repr(fixed[idx2:idx2+25])}")

# Write fixed file
with open(filepath, 'w', encoding='utf-8') as f:
    f.write(fixed)

print("\nFile written successfully.")
