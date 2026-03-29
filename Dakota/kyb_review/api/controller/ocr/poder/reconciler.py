from comparator import comparar

def reportar(user: dict, doc: dict):
    print("\n=== Conciliación ===\n")
    for campo, v in user.items():
        d = doc.get(campo, "")
        match, score = comparar(v, d)
        status = '[OK]' if match else '[X]'
        print(f"{campo}: Usuario='{v}' Doc='{d}' => {status} (score={score})")
