from comparator import comparar

def reportar(user,doc):
    print("\n=== Conciliación ===\n")
    for campo,v in user.items():
        d=doc.get(campo,"")
        m,s=comparar(v,d)
        print(f"{campo}: Usuario='{v}' Doc='{d}' => {'[OK]' if m else '[X]'} (score={s})")
