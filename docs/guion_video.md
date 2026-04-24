# Guion del video explicativo — AgroSmart Digital Twin

Duración estimada: 4 minutos.
Audiencia: no técnica (agricultores, tutores, público general del curso).
Autor: Andrés Camilo Briñez Núñez.
Proceso: primera versión generada con apoyo de Claude AI (Anthropic, 2026), revisada y ajustada manualmente para precisión técnica y tono local.

---

## Bloque 0 — Apertura (0:00 – 0:20)

Plano: cultivo con riego por inundación, agua escurriendo por el suelo.
Texto en pantalla: «El 70 % del agua dulce del planeta se usa en la agricultura».

Narración:

> «De cada diez baldes de agua dulce que el planeta tiene disponibles, siete se van a la agricultura. Y en América Latina, más de la mitad de esa agua se pierde por métodos de riego que desperdician el recurso. En Colombia, esto impacta directamente al pequeño agricultor, que tiene que producir más con menos agua cada año. Hoy les quiero mostrar una idea sencilla para resolver ese problema».

---

## Bloque 1 — Qué es AgroSmart (0:20 – 1:00)

Plano: diagrama animado: sensor en el suelo → ESP32 → LoRa → coordinador → válvula.
Texto en pantalla: «AgroSmart · riego inteligente de bajo costo».

Narración:

> «AgroSmart es un sistema pensado para el agricultor. La idea es simple: en vez de regar por reloj, que rieguen los sensores. Cada zona del cultivo tiene un pequeño dispositivo, del tamaño de un celular, que mide qué tan húmeda está la tierra cada 15 minutos. Si la tierra está seca, abre el riego por goteo. Si la tierra ya tiene agua suficiente, espera. Y si el pronóstico del tiempo dice que va a llover, también espera. Todo esto funciona con paneles solares, sin necesidad de internet permanente, y se puede instalar en una finca pequeña en un fin de semana».

---

## Bloque 2 — El prototipo digital que construí (1:00 – 2:00)

Plano: captura de la terminal ejecutando `docker compose up -d`.
Texto en pantalla: «Gemelo digital — el sistema completo en una computadora».

Narración:

> «Para mostrar cómo funcionaría AgroSmart en la vida real, construí lo que se llama un gemelo digital: una copia del sistema que vive dentro de una computadora. Cada parte real del sistema — los sensores, el coordinador, la válvula, el panel, el pronóstico del tiempo — está representada por un programa pequeño. Todos esos programas hablan entre sí con los mismos mensajes que usarían si fueran aparatos de verdad. De esta forma puedo probar que las reglas de decisión funcionan sin haber comprado todavía un solo ESP32 ni instalado una sola tubería».

Plano: panel de operador con las tres tarjetas de zonas y sus barras de humedad animadas.

> «En esta pantalla ven las tres zonas del cultivo. Cada una tiene su propia humedad en vivo. La barra azul sube cuando la tierra tiene agua y baja cuando el sol la evapora. Las decisiones del coordinador aparecen en el panel de abajo: si mantiene, si riega o si decide esperar porque se espera lluvia».

---

## Bloque 3 — El ahorro en acción (2:00 – 3:00)

Plano: zoom a una zona cuya barra está cayendo. Cuando cruza el umbral, aparece el mensaje «REGAR».

Narración:

> «Miren la zona dos. Su humedad viene bajando porque el sol lleva horas pegando fuerte. Cuando cruza el umbral mínimo, el coordinador lo detecta y envía la orden de regar. En pocos segundos, la barra sube y el sistema anota cuánta agua se entregó. Esto es lo que ahorra: riega solo cuando hace falta y solo lo que hace falta».

Plano: el presentador hace clic en el botón «Inyectar pronóstico de lluvia». El panel cambia a estado «lluvia».

> «Ahora les muestro la parte más interesante. Le decimos al sistema que se espera lluvia en las próximas seis horas. El coordinador no reacciona al miedo, reacciona al dato: cambia todas sus decisiones a esperar. Ninguna válvula se va a abrir mientras dure la ventana de lluvia pronosticada. Esto evita que riegue justo antes de que llueva y se pierda todo el aporte en exceso».

---

## Bloque 4 — Por qué es ético y escalable (3:00 – 3:35)

Plano: dashboard de Grafana con gráficas largas y números grandes.

Narración:

> «El sistema no solo ahorra agua. También guarda un historial completo de cada decisión y cada riego. Esto le permite al agricultor saber exactamente cuánta agua ahorró al mes y por qué. No hay algoritmos misteriosos: cada riego tiene una razón clara y la pueden ver. Y si el finquero quiere crecer, basta con agregar un nodo más al sistema. Lo mismo que corre en tres zonas puede correr en veinte, sin cambiar nada de la arquitectura».

---

## Bloque 5 — Cierre y llamada a la acción (3:35 – 4:00)

Plano: logo AgroSmart sobre fondo verde. Texto del equipo.
Texto en pantalla: «AgroSmart — Grupo 302 — UNAD — Proyecto de Ingeniería I — 2026».

Narración:

> «Este prototipo demuestra que la tecnología para cuidar el agua ya existe, ya es accesible y ya se puede construir paso a paso. El siguiente paso es llevarlo al campo, con un nodo físico real y un agricultor que nos ayude a validarlo. Si conoces a alguien que esté enfrentando escasez de agua en su cultivo, cuéntanos. Gracias por ver».

---

## Notas de producción

- Herramientas recomendadas: Loom o OBS Studio para la grabación; Canva o CapCut para la edición final.
- Voz en off: tono cálido, ritmo pausado, 110 a 120 palabras por minuto.
- Duración objetivo: 3:50 a 4:10 minutos; si excede, recortar la parte del dashboard de Grafana.
- Subtítulos: en español, con términos técnicos en cursiva la primera vez que aparecen.
- Música de fondo: suave, sin letras, volumen al 15 %.
- Llamada a la acción final: opcional incluir un correo o enlace al foro del curso.

## Anexo — Prompt utilizado con la IA

```
Actúa como guionista técnico. A partir de la descripción del prototipo
AgroSmart Digital Twin (3 nodos ESP32 simulados, broker MQTT, coordinador
con motor de decisión, TimescaleDB y Grafana), redacta un guion de video
de 4 minutos para una audiencia no técnica que explique cómo el sistema
ahorra agua cuando se pronostica lluvia. Mantén un tono claro, usa
analogías concretas y cierra con una llamada a la acción.
```

La salida de la IA fue revisada para:

- Ajustar nombres técnicos a términos que entienda un agricultor.
- Sustituir analogías genéricas por referencias al contexto colombiano.
- Verificar que cada afirmación técnica corresponda a lo que realmente hace el prototipo.
- Añadir las notas de producción y los planos sugeridos.
