from thefuzz import fuzz
import re

NULL_TOKENS = {"N/A","NA","SIN NUMERO","S/N","SN",""}
DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}$")

def comparar(u,d,umbral=80):
    U,D=u.strip().upper(),d.strip().upper()
    if DATE_PATTERN.match(U) and DATE_PATTERN.match(D):
        return (U==D),100 if U==D else 0
    if U in NULL_TOKENS and D in NULL_TOKENS: return True,100
    if (U in NULL_TOKENS)^(D in NULL_TOKENS): return False,0
    score=fuzz.ratio(u,d)
    return score>=umbral,score



