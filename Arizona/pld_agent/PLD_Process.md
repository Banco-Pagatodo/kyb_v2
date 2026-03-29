# Guía completa del proceso PLD bancario en México para Personas Morales

**El proceso de Prevención de Lavado de Dinero (PLD) para Personas Morales en bancos mexicanos se estructura en ocho etapas secuenciales**: recepción del expediente, screening contra listas, verificación de datos, identificación del beneficiario controlador, búsqueda de noticias adversas, evaluación de riesgo, dictamen, y documentación. El agente Arizona debe replicar estas etapas respetando un marco regulatorio que cambió significativamente con la reforma de julio 2025 a la LFPIORPI, que redujo el umbral de beneficiario controlador de 50% a **25%**, elevó la conservación de documentos a **10 años** y aceleró los plazos de reporte a **24 horas**. La jurisdicción supervisora la comparten la CNBV (vigilancia operativa), la UIF (inteligencia financiera y lista de personas bloqueadas) y la SHCP (política normativa), con sanciones que van desde multas de hasta el 100% del monto operado hasta prisión de 5 a 15 años por el artículo 400 Bis del Código Penal Federal.

---

## A. Las ocho etapas del análisis PLD paso a paso

El flujo arranca cuando el analista PLD recibe el expediente ya validado documentalmente (en el caso de Arizona, los datos post cross_validation y KYB review). Desde ese punto, el proceso opera así:

**Etapa 1 — Recepción y verificación de completitud documental.** El analista confirma que el expediente contiene todos los elementos que exige la Disposición 4ª de las DCG del artículo 115 de la Ley de Instituciones de Crédito: denominación o razón social, RFC con homoclave, número de serie de e.firma, país de constitución, giro mercantil u objeto social, domicilio completo, fecha de constitución, y nombre completo de administradores, directores o apoderados legales que puedan obligar a la persona moral. Los documentos soporte obligatorios incluyen el testimonio de escritura constitutiva inscrita en el Registro Público de Comercio, la Cédula de Identificación Fiscal, comprobante de domicilio, testimonio del instrumento con poderes del representante legal, e identificación oficial vigente de éste. Para clientes que resulten de alto riesgo, se exigen además estados financieros de los dos últimos ejercicios, las dos últimas declaraciones anuales al SAT, y detalle de accionistas principales con nombre, nacionalidad y porcentaje de participación.

**Etapa 2 — Screening contra listas (primera barrera, completamente automatizable).** Esta es la etapa crítica para Arizona. El sistema debe cruzar **cada nombre** —razón social, apoderados, representantes legales, accionistas y beneficiarios controladores— contra todas las listas obligatorias. Una coincidencia en la Lista de Personas Bloqueadas (LPB) de la UIF provoca suspensión inmediata y reporte de 24 horas. Una coincidencia PEP activa la debida diligencia reforzada pero no impide la relación. Una coincidencia OFAC/ONU implica bloqueo. Una coincidencia en lista 69-B del SAT es señal de alerta roja que puede derivar en rechazo. El detalle completo de listas se desarrolla en la sección C.

**Etapa 3 — Verificación de datos y existencia legal.** Se valida el RFC contra el SAT (que esté activo, no cancelado, y corresponda a la razón social), la CURP de personas físicas contra RENAPO, las identificaciones oficiales contra la lista nominal del INE, y la existencia legal en el Registro Público de Comercio. Se verifica la consistencia cruzada: que la razón social del RFC coincida con la del acta constitutiva.

**Etapa 4 — Identificación del beneficiario controlador.** Se analiza la estructura accionaria para identificar a toda persona física que posea directa o indirectamente más del **25%** del capital social o derechos de voto. Si algún accionista es persona moral, se ejecuta el procedimiento de look-through (perforación de la cadena) hasta llegar a personas físicas. Si no se identifica a nadie con ≥25%, se designa al administrador o consejo de administración como beneficiario controlador. Cada beneficiario controlador identificado pasa por screening completo.

**Etapa 5 — Búsqueda de noticias adversas (adverse media).** Se consultan fuentes abiertas y bases de datos comerciales buscando vínculos con actividades criminales, corrupción, fraude, lavado de dinero, investigaciones judiciales o sanciones. Aunque no es una obligación textual explícita de las DCG, la Guía Anticorrupción de la CNBV (2020) la recomienda, y el GAFI la considera buena práctica. Se busca la razón social, cada representante, apoderado, y accionista significativo.

**Etapa 6 — Evaluación de riesgo (Enfoque Basado en Riesgos).** Se aplica la matriz de riesgo del banco considerando factores del cliente (actividad económica, nacionalidad, antigüedad de constitución, presencia de PEPs, estructura accionaria compleja, jurisdicciones de alto riesgo), del producto (tipo de cuenta, monto esperado, canales) y geográficos. El resultado clasifica al cliente en **Bajo**, **Medio** o **Alto** riesgo, determinando el nivel de debida diligencia aplicable.

**Etapa 7 — Dictamen.** El analista emite su resolución: aprobado, aprobado con condiciones (EDD), escalado a Comité de Comunicación y Control, o rechazado. Los detalles de cada dictamen posible se desarrollan en la sección F.

**Etapa 8 — Documentación y conservación.** Se registra todo: consultas realizadas, evidencia de screening, justificación del nivel de riesgo, decisión y fundamentación. El plazo de conservación es de **5 años** para el sector financiero desde la última operación, y **10 años** para actividades vulnerables tras la reforma 2025. En la práctica, el onboarding PLD estándar toma de 3 a 10 días hábiles para riesgo bajo/medio, y hasta 30-60 días cuando se aplica EDD.

---

## B. El trípode regulatorio: LFPIORPI, CNBV y UIF

### LFPIORPI: la ley marco

La Ley Federal para la Prevención e Identificación de Operaciones con Recursos de Procedencia Ilícita, publicada originalmente el 17 de octubre de 2012 y reformada significativamente el **16 de julio de 2025**, establece dos regímenes paralelos. El artículo 15 regula a las entidades financieras (bancos, casas de bolsa, aseguradoras), supervisadas por la CNBV. El artículo 17 regula las actividades vulnerables no financieras, supervisadas por el SAT. Para Arizona, aplica el régimen financiero.

Los artículos más relevantes post-reforma 2025 son: el **artículo 3, fracción III**, que redefine al beneficiario controlador con umbral de 25% (antes 50%); el **artículo 18**, que obliga a identificar clientes, solicitar información sobre actividad, identificar al beneficiario controlador y custodiar documentación; y los nuevos **artículos 33 a 33 Ter**, que crean un capítulo específico de beneficiario controlador aplicable a todas las personas morales, obligando a registrarlo en el sistema electrónico de la Secretaría de Economía. Las sanciones van de **200 a 65,000 UMA** según la infracción (aproximadamente $23,462 a $7,625,150 MXN), más consecuencias penales de 2 a 8 años de prisión por el artículo 400 Bis del Código Penal Federal.

### Disposiciones de Carácter General de la CNBV

Emitidas con fundamento en el **artículo 115 de la Ley de Instituciones de Crédito**, estas disposiciones son el reglamento operativo que define exactamente qué deben hacer los bancos. La versión vigente incorpora reformas de agosto de 2024 que exigen alertas automatizadas para la LPB, PEPs y sanciones internacionales. Obligan a elaborar una política de identificación del cliente (Disposición 3ª), integrar expediente previo a apertura de cuenta (4ª), clasificar clientes por grado de riesgo (25ª Bis), verificar expedientes de alto riesgo al menos una vez al año (21ª), contar con sistemas automatizados con listas de sanciones (51ª), designar un Oficial de Cumplimiento certificado (47ª), constituir un Comité de Comunicación y Control (43ª), y elaborar un Manual de Cumplimiento (64ª). La reforma 2024 añadió la obligación de que el expediente sea revisado por un **funcionario distinto** al que lo integró.

### UIF: el centro de inteligencia financiera

La Unidad de Inteligencia Financiera es un órgano desconcentrado de la SHCP que recibe, analiza y disemina información para combatir lavado de dinero y financiamiento al terrorismo. Administra la Lista de Personas Bloqueadas, coordina la Evaluación Nacional de Riesgos, y es el punto de contacto ante el GAFI y el Grupo Egmont. Los bancos le envían reportes por conducto de la CNBV a través del portal **SITI PLD/FT**, incluyendo Reportes de Operaciones Relevantes (operaciones en efectivo ≥USD $10,000, mensuales), Reportes de Operaciones Inusuales (plazo de 60 días naturales, o 24 horas para casos urgentes), y Reportes de Operaciones Internas Preocupantes. En 2025, los bancos y casas de bolsa entregaron **391,000 reportes de operaciones inusuales** y 9.56 millones de reportes de transferencias internacionales.

Complementan este trípode la **Ley de Instituciones de Crédito** (artículos 115 y 142 sobre secreto bancario), el **Código Fiscal de la Federación** (artículos 32-B Ter a Quinquies sobre beneficiario controlador, y 69-B sobre EFOS), y las 40 Recomendaciones del GAFI, particularmente la R.10 (debida diligencia), R.12 (PEPs), R.20 (reporte de operaciones sospechosas) y R.24 (transparencia de personas jurídicas).

---

## C. Las listas que Arizona debe consultar obligatoriamente

### Lista de Personas Bloqueadas (LPB) de la UIF

Es la lista más crítica del sistema mexicano. Fundamentada en el artículo 115 de la LIC y las Disposiciones 70ª a 73ª, incluye a personas físicas y morales vinculadas con lavado de dinero, financiamiento al terrorismo y delitos relacionados. Es **confidencial y reservada** —solo el Oficial de Cumplimiento accede vía el portal SITI de la CNBV— y está prohibido alertar al cliente sobre su inclusión (tipping off). Se actualiza de forma continua. Una coincidencia obliga a **suspender inmediatamente** toda operación, bloquear cuentas y recursos, y enviar un reporte de 24 horas. El incumplimiento conlleva multa del **10% al 100%** del monto operado. Los criterios de inclusión abarcan resoluciones de la ONU, solicitudes de autoridades extranjeras, investigaciones nacionales de la UIF, procesos penales, y contribuyentes en el artículo 69-B del CFF.

### Lista 69-B del SAT: EFOS y EDOS

Las EFOS (Empresas que Facturan Operaciones Simuladas) son contribuyentes que emiten facturas sin tener activos, personal ni infraestructura real para respaldarlas —empresas fachada para vender facturas falsas—. Las EDOS son quienes compran esas facturas para deducir gastos indebidamente. La lista contempla cuatro categorías: **presunto** (el SAT sospecha; hay 15 días para defenderse), **desvirtuado** (se probó que las operaciones eran reales), **definitivo** (confirmado; las facturas pierden validez fiscal), y **sentencia favorable** (un tribunal falló a favor). Se publica en el portal de datos abiertos del SAT y en el DOF, con actualizaciones típicamente trimestrales. Los contribuyentes definitivos pueden ser incluidos en la LPB, convirtiendo una alerta fiscal en un bloqueo financiero total. Un cliente en esta lista es señal de alerta roja que debe detonar EDD o rechazo.

### Listas internacionales

La **OFAC SDN List** (Specially Designated Nationals del Departamento del Tesoro de EE.UU.) no es obligación directa de la ley mexicana, pero es **prácticamente indispensable**: los bancos mexicanos con corresponsalía bancaria estadounidense deben cumplirla, y la Regla del 50% de OFAC bloquea automáticamente a cualquier empresa propiedad mayoritaria de un sancionado. El incumplimiento resulta en de-risking (cancelación de relaciones de corresponsalía). Se consulta en sanctionssearch.ofac.treas.gov, que incorpora fuzzy matching nativo. Las **listas del Consejo de Seguridad de la ONU** —resoluciones 1267 (Al-Qaeda/Daesh), 1373 (anti-terrorismo post 9/11) y 1540 (proliferación de armas de destrucción masiva)— sí son **obligatorias por derecho internacional**, y la UIF las incorpora a la LPB. Se consultan en un.org/securitycouncil y el SAT las publica en sppld.sat.gob.mx. Las listas de la **Unión Europea** e **INTERPOL** no son obligatorias directas, pero se consultan como buena práctica bajo el Enfoque Basado en Riesgos, y los proveedores comerciales las integran automáticamente.

### Personas Políticamente Expuestas (PEPs)

La SHCP publica una **lista de cargos** (no de nombres) que se consideran PEP. Incluye al Presidente de la República, secretarios de Estado y hasta **tres niveles jerárquicos inferiores** con poder de mando real, senadores, diputados federales y locales, ministros de la SCJN, magistrados, jueces federales, gobernadores y sus gabinetes, presidentes municipales, titulares de órganos autónomos (INE, INAI, Banxico), directores de empresas estatales (Pemex, CFE), dirigentes de partidos políticos, y militares de alto rango. La clasificación se extiende a **cónyuges, familiares de primer y segundo grado** por consanguinidad, y asociados con relación patrimonial directa. No existe base de datos nominal oficial; cada banco debe construir la propia o contratar proveedores comerciales como World-Check, Dow Jones Risk & Compliance, Regcheq o LexisNexis. Tras dejar el cargo, el GAFI recomienda mínimo 2 años, y la práctica mexicana extiende a 2-5 años con evaluación individualizada. Ser PEP **no prohíbe** la relación comercial, a diferencia de la LPB, pero obliga a aplicar EDD, obtener aprobación de alta dirección y monitoreo intensificado.

### Lista 69 del CFF y listas del GAFI

El artículo 69 del CFF publica contribuyentes con créditos fiscales firmes, exigibles no pagados, no localizados, o con sentencia condenatoria por delito fiscal. La UIF también publica las **listas públicas del GAFI** que identifican jurisdicciones de alto riesgo (lista negra) y bajo monitoreo intensificado (lista gris), relevantes para evaluar operaciones con países riesgosos.

### Proveedores comerciales consolidados

Los bancos mexicanos típicamente utilizan plataformas que consolidan todas estas listas: **World-Check** (Refinitiv/LSEG), **Dow Jones Risk & Compliance**, **Bureau van Dijk/Orbis** (Moody's) para estructuras corporativas, y proveedores mexicanos especializados como **Regcheq**, **KYC Systems** y **PLD Check** (Buró de Crédito). Estos integran LPB, OFAC, ONU, UE, INTERPOL, SAT 69/69-B, PEPs y noticias adversas en una sola consulta.

---

## D. Qué se revisa exactamente en cada campo

### Razón social

El screening busca **coincidencias exactas y variaciones**: con y sin tipo societario (S.A. de C.V., S. de R.L. de C.V., S.A.B.), abreviaciones, errores ortográficos comunes, y para nombres extranjeros, transliteraciones. Los sistemas profesionales ajustan un porcentaje de coincidencia típicamente entre **75-85%** para balancear detección contra falsos positivos. Además del screening contra listas, se verifica la existencia legal en el Registro Público de Comercio, que el RFC esté activo y corresponda a la razón social declarada, que no aparezca en lista 69-B del SAT, y se realiza búsqueda de noticias adversas. Se valida la consistencia entre la razón social del RFC, la del acta constitutiva y la declarada por el cliente.

### Apoderados

Se verifican: nombre completo sin abreviaturas, RFC, CURP, fecha de nacimiento, nacionalidad y domicilio. Se realiza screening completo contra todas las listas (LPB, PEPs, OFAC, ONU, SAT). Se verifica la vigencia del poder notarial, que no haya sido revocado, y que otorgue facultades suficientes para la operación solicitada. Se coteja la identificación oficial contra el original y se valida su autenticidad con la fuente emisora (INE, SRE). Se ejecuta búsqueda de noticias adversas.

### Representantes legales

El proceso es **idéntico al de apoderados**, con una diferencia clave: se verifica que tengan **facultades específicas** para obligar a la persona moral en la operación concreta (apertura de cuentas, contratación de productos financieros). En la práctica, representante legal y apoderado pueden ser la misma persona; si son distintos, ambos pasan por screening completo. Arizona debe tratar ambos campos con el mismo pipeline de verificación.

### Accionistas

Se revisa el **porcentaje de participación** de cada uno. El análisis profundo se enfoca en accionistas con más del **25%** (beneficiarios controladores post-reforma 2025) y en cualquiera que ejerza control por otros medios aunque tenga menor participación. Cada persona física identificada como accionista significativo pasa por screening completo. Si un accionista es persona moral, se ejecuta el **look-through** obligatorio: se perfora la cadena de titularidad hasta llegar a personas físicas, documentando toda la estructura. Excepción: si la persona moral cotiza en bolsa, se documenta el mercado de valores donde cotiza en lugar de identificar cada accionista individual. Todos los accionistas se identifican, pero los de menos del 25% y sin control efectivo reciben verificación básica contra listas sin análisis profundo.

---

## E. Beneficiario controlador: el concepto central para Arizona

México opera un **doble régimen jurídico** de beneficiario controlador. En el Código Fiscal (artículos 32-B Ter a Quinquies, vigentes desde enero 2022), la autoridad supervisora es el SAT y aplica a todas las personas morales y fideicomisos. En la LFPIORPI (artículos 3, fracción III, y 33 a 33 Ter, reformados en julio 2025), la autoridad es la SHCP/UIF y aplica universalmente. Ambos regímenes convergen en el **umbral del 25%** del capital social o derechos de voto, alineado con la Recomendación 24 del GAFI.

El beneficiario controlador es siempre una **persona física** (o grupo de personas físicas) que: (a) directa o indirectamente obtiene el beneficio último de un acto u operación, o (b) ejerce el **control efectivo en última instancia** de la persona moral. Los criterios para determinar control efectivo son: poseer más del 25% de derechos de voto o capital, imponer decisiones en asambleas generales, nombrar o destituir a la mayoría de consejeros o administradores, o dirigir directa o indirectamente la administración, estrategia o políticas principales.

Para cadenas de control indirectas, Arizona debe implementar un algoritmo de **look-through recursivo**: si el accionista directo es persona moral, se sube al siguiente nivel hasta llegar a persona física; si el administrador designado es persona moral o fideicomiso, se identifica a la persona física nombrada como administrador por dicha entidad. Si agotados estos métodos no se identifica a nadie con ≥25%, se designa al **administrador único o miembros del consejo de administración** como beneficiarios controladores. Los datos mínimos que deben conservarse de cada beneficiario controlador incluyen nombres y apellidos completos, fecha de nacimiento, CURP, país de origen, nacionalidad, país de residencia fiscal, porcentaje de participación, y descripción de la forma de control. Cualquier modificación debe actualizarse dentro de **15 días naturales** (artículo 32-B Quinquies CFF). El incumplimiento genera multas de **$1.68 a $2.24 millones de pesos** por cada beneficiario controlador no identificado.

---

## F. Los cuatro dictámenes posibles del analista PLD

**Aprobado (riesgo bajo/medio).** Sin coincidencias en listas, documentación completa y verificada, existencia legal confirmada, sin noticias adversas relevantes, perfil transaccional consistente con la actividad declarada. Lo aprueba el analista PLD o el Oficial de Cumplimiento.

**Aprobado con condiciones (riesgo alto, EDD aplicada).** Se aprueba pero con medidas de mitigación: EDD documentada, monitoreo reforzado activado, límites transaccionales, re-evaluación periódica más frecuente (semestral o trimestral). Lo aprueba el Oficial de Cumplimiento y/o el director de línea de negocio. Este dictamen aplica típicamente cuando hay PEPs entre los accionistas o representantes, estructura accionaria compleja, o jurisdicciones de riesgo elevado.

**Escalado al Comité de Comunicación y Control (CCC).** Para casos complejos, PEPs de alto nivel, coincidencias parciales que requieren análisis colectivo, o cuando el nivel de riesgo se ubica en zona gris. El CCC es un órgano colegiado con representantes de alta dirección que dictamina si se aprueba, rechaza o se aplican medidas adicionales. Sus decisiones se documentan en actas formales.

**Rechazado.** Es obligatorio cuando hay coincidencia confirmada en la LPB (bloqueo inmediato), cuando el cliente se niega a proporcionar información requerida (obligación legal de rechazo), cuando se detecta documentación falsa o fraudulenta, cuando el nivel de riesgo resulta inaceptable tras EDD, o ante sospecha razonable de vinculación con lavado de dinero o financiamiento al terrorismo. El rechazo puede ir acompañado de un ROI o reporte de 24 horas si los hallazgos lo ameritan; son **decisiones independientes**. La cancelación de la relación comercial se documenta como parte de las "gestiones realizadas" del ROI.

---

## G. El Reporte de Operaciones Inusuales (ROI): equivalente mexicano del ROS

El ROI es el mecanismo formal mediante el cual un banco comunica a la UIF, por conducto de la CNBV y a través del portal SITI PLD/FT, que ha identificado una operación que **no concuerda con los antecedentes, actividad conocida o perfil transaccional del cliente** y no tiene justificación económica o legal aparente. Es el equivalente mexicano del Suspicious Activity Report (SAR) o Reporte de Operación Sospechosa (ROS) usado en otras jurisdicciones.

El ROI puede generarse en cualquier momento: durante el onboarding si se detectan indicios, o durante el monitoreo transaccional posterior. El flujo es: la alerta se detecta (automática o manualmente), el analista la investiga, el CCC la dictamina como inusual, y se envía. El plazo es de **60 días naturales** desde que el CCC dictamina la operación como inusual, aunque la reforma 2025 estableció **24 horas** para operaciones sospechosas vinculadas directamente a terrorismo (artículo 139 CPF), financiamiento al terrorismo (148 Bis) o lavado de dinero (400 Bis). El contenido del ROI incluye descripción de la operación (conocimiento del cliente, datos del producto, perfil transaccional) y razón de la inusualidad (alerta detectada, análisis del contexto, gestiones realizadas, determinación de la inusualidad). Se clasifica como prioridad **ALTA** (vinculada a LD/FT) o sin prioridad.

México distingue además el **Reporte de Operaciones Internas Preocupantes (ROIP)**, que cubre conductas de empleados o funcionarios del banco que pudieran contravenir la ley, y el **Reporte de Operaciones Relevantes (ROR)**, que es objetivo y automático: toda operación en efectivo ≥ equivalente a USD $10,000, enviado mensualmente dentro de los primeros 10 días del mes siguiente. El ROR no requiere análisis de sospecha, solo conteo por monto.

---

## H. Cuándo se activa la debida diligencia reforzada

La EDD se activa obligatoriamente cuando el cliente se clasifica como de **alto riesgo**. Los detonadores específicos incluyen: presencia de PEPs entre accionistas, beneficiarios controladores, representantes o apoderados; constitución o residencia en jurisdicciones de alto riesgo o en lista gris/negra del GAFI; estructura de propiedad compleja, multilateral u opaca; actividad económica de alto riesgo (casinos, sector inmobiliario, joyería, comercio de arte, criptoactivos); constitución reciente de la persona moral (**menos de 3 años**); operaciones en efectivo por montos elevados; información negativa en noticias adversas; operaciones que se aparten del perfil transaccional esperado; y coincidencias parciales no resueltas en listas de sanciones.

La EDD implica recopilar información adicional (estados financieros auditados de los últimos 2 ejercicios, últimas 2 declaraciones anuales al SAT, detalle de principales accionistas, **origen documentado de los fondos y fuente de riqueza**, propósito detallado de la relación comercial), obtener aprobación de nivel superior (Oficial de Cumplimiento y/o CCC), implementar monitoreo transaccional más frecuente, programar re-evaluación periódica más frecuente, realizar visitas domiciliarias en casos de riesgo alto, y documentar exhaustivamente todo el proceso de análisis. Contrasta con la **debida diligencia simplificada**, que aplica solo a clientes de riesgo bajo como dependencias gubernamentales, entidades reguladas del sistema financiero mexicano u organismos internacionales, y permite datos básicos de identificación sin requerir documentación completa.

---

## Checklist de implementación para el agente Arizona

Para efectos del diseño del agente, el flujo automatizable se resume en el siguiente diagrama lógico que Arizona debe ejecutar secuencialmente:

1. **Recibir datos validados** del agente previo (razón social, RFC, fecha constitución, objeto social, domicilio, apoderados, representantes legales, accionistas con sus datos personales y porcentajes).

2. **Ejecutar screening contra listas** para cada entidad y persona: LPB (match = bloqueo inmediato + reporte 24h), PEPs (match = flag EDD), OFAC SDN (match = bloqueo), ONU/CSNU (match = bloqueo), SAT 69-B EFOS (match = flag alto riesgo / posible rechazo), SAT 69 incumplidos (match = flag riesgo), GAFI jurisdicciones (match = flag riesgo geográfico). El matching debe ser exacto **y** difuso (fuzzy matching al 75-85%), buscando variaciones de nombre, alias, transliteraciones, e inversiones nombre/apellido. Los falsos positivos se resuelven cruzando datos adicionales (fecha de nacimiento, CURP, RFC, nacionalidad).

3. **Verificar datos** contra fuentes autoritativas: RFC activo en SAT, CURP válida en RENAPO, existencia en Registro Público de Comercio, consistencia cruzada entre documentos.

4. **Calcular beneficiario controlador**: análisis de estructura accionaria, identificación de personas con >25% de derechos de voto, look-through recursivo de personas morales intermedias hasta persona física, screening de cada beneficiario controlador identificado. Si no se identifica por propiedad → revisar control efectivo → si tampoco → designar administrador.

5. **Ejecutar adverse media screening** para razón social, cada representante, apoderado, accionista significativo y beneficiario controlador.

6. **Calcular nivel de riesgo** aplicando matriz multifactorial (cliente + producto + geografía) → clasificar Bajo, Medio o Alto → determinar nivel de DD.

7. **Emitir dictamen**: Aprobado, Aprobado con EDD, Escalado a Comité, o Rechazado (+ ROI/24h si corresponde).

8. **Documentar** todas las consultas, evidencia, justificación y decisión. Programar re-screening periódico (diario/semanal contra actualizaciones de listas, anual para re-evaluación completa del expediente).

## Conclusión

El proceso PLD mexicano para Personas Morales es un sistema de filtros progresivos donde cada etapa puede escalar o detener la relación comercial. Arizona debe priorizar tres capacidades técnicas fundamentales: un motor de **fuzzy matching robusto** que cubra variaciones lingüísticas del español y transliteraciones, un algoritmo de **look-through recursivo** para resolver cadenas de control indirecto hasta personas físicas, y un **motor de reglas basado en riesgo** que pondere múltiples factores simultáneamente para clasificar al cliente. La reforma de julio 2025 a la LFPIORPI hizo el régimen significativamente más estricto: el umbral de beneficiario controlador al 25%, la conservación a 10 años, y los plazos de reporte a 24 horas no tienen marcha atrás. El agente debe diseñarse desde el inicio para estos parámetros, con la flexibilidad de incorporar actualizaciones regulatorias futuras, particularmente las disposiciones pendientes de la CNBV que aún están en proceso de alineación con la reforma.