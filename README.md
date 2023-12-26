<center><font color = "yellow"><h2><b>"<u>Readme</u>"</b></h2></font></center>

El objetivo de este proyecto es diagramar una arquitectura básica de algoritmo de trading basada en WebSockets/REST-API para la adquisición de datos y para la ejecución de órdenes. Luego, implementarla con una estrategia simple de arbitraje spot/futuros para comprobar su correcto funcionamiento y la lógica de trading misma.

<h3><u><b>
Estructura
</b></u></h3>

Se basa en el uso de objetos "<code><b><u>Strategy</u></b></code>" que contienen una estructura simple de ejecución basada en eventos. El crear una nueva estrategia, implica programar una subclase de "<code>Strategy</code>", y sobreescribir (overload) 3 funciones:
<ol><li>Inicialización - "<code>on_init</code>" (<u>opcional</u>): Toda aquella acción que debe tomar lugar apenas se crea una instancia de la estrategia.
</li><li>Ejecuciónes - "<code>on_</code>": El procedimiento a seguir cuando aquel determinado evento ocurre. Toma el dato recibido hace un instante, y devuelve (o no) una o mas "señales" de trading ("<code>Signal</code>"). Hay de 3 tipos:
<ul><li>"<code>on_tick</code>" (<u>obligatorio</u>): Ante algún cambio en los mercados de interés (bids, asks, volumenes), envía (o no) alguna nueva órden.
</li><li>"<code>on_order</code>" (<u>pendiente</u>): Ante algún cambio en las órdenes pre-existentes (ya emitidas por "<code>on_tick</code>"), las puede modificar o eliminar.<br>(<i>idea próxima a programar - todavía no fue implementada</i>).
</li><li>"<code>tasks</code>" (<u>opcional</u>): Se puede crear funciones con procesos que no necesiten de datos de mercado u órdenes para ocurrir, sino que simplemente se activen cada cierta cantidad de tiempo, o a una determinada fecha/hora. Estos ocurrirán en threads paralelos (mediante "<code>Scheduler</code>") sin interrumpir a la lógica principal.
</li></ul>
</li></ol>
Las subclases de "<code>Strategy</code>" se guardan dentro de la carpeta "<code>strategies</code>". Puede verse que cualquiera dispone de la siguiente organización:

```json
    class MySuperStrategy(Strategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs,
                tasks = {
                    self.other_function: Trigger(seconds = 30)
                }
            )
        def other_function(self, ...) -> None:
            ...
        def on_init(self, ...) -> None:
            ...
        def on_tick(self, data_deriv, data_under) -> list[Signal]:
            ...
            return ...
        def on_order(self, data_order) -> list[Signal]: # Pendiente
            ...
            return ...
```

La estructura es escalable: pueden agregarse funciones adicionales tranquilamente, como unit tests, requests de datos externos, integraciones de otras APIs o servicios, dashboards o interfaces gráficas, etc; sin tener que alterar este esquema básico.

Por otro lado, el programa dispone de un objeto primario llamado "<code><b><u>Interface</u></b></code>" que gestiona toda la interacción entre el exchange y los sistemas locales. Ésta clase posee 3 tipos de funciones:

<ul><li><u>Listeners de WebSockets</u>: Sus nombres comienzan con "<code>_on_</code>". Se ejecutan de manera automática cuando el exchange nos envía un paquete de datos, actualizandonos sobre un evento. Son funciones <u>privadas</u>: su objetivo es ser utilizadas solo dentro de la instancia de clase. No deberían usarse normalmente en el "scope global", excepto durante algún tipo de testing.
</li><li><u>Gestión de estrategias</u>: Sus nombres terminan con "<code>_strategies</code>". Por ejemplo:
<ul><li>"<code>load_strategies</code>" agrega estrategias mediante objetos "<code>Strategy</code>", a la "<code>Interface</code>".
</li><li>"<code>toggle_strategies</code>" pausa/reanuda las estrategias especificadas según se desee.
</li><li>"<code>remove_strategies</code>" elimina las estrategias especificadas mediante una lista.
</li></ul>
</li><li><u>Solicitud de especificaciones de mercado</u>: Sus nombres comienzan con "<code>get_</code>". Las estrategias necesitan, además de los datos tick mas recientes de los instrumentos de interés, información adicional. Son 2:
<ul><li>"<code>get_specs_derivs</code>": Parámetros financieros de los instrumentos en cuestión. Ejemplo: "tamaño mínimo de órden", "fecha de vencimiento", "cantidad de decimales que contiene el precio", etc.
</li><li>"<code>get_specs_unders</code>": Parámetros y datos de precio para los subyacentes. Esto no debería ser realmente necesario ya que las APIs de los exchanges en general proveen de precios y volúmenes recientes para los "spot", pudiendo así suscribirse a ellos de igual manera que a los feeds de los derivados. Como ReMarkets no cuenta con ello, usamos un request mediante REST API de manera periódica (por defecto, cada un minuto) a Yahoo Finance para actualizar precios y volúmenes de ellos.
</li></ul>Normalmente estas funciones se ejecutan de manera regular dentro de otros métodos de "<code>Interface</code>". Sin embargo, se las propuso como funciones de clase ("<code>@classmethod</code>") para que puedan usarse en el "scope" global (ya sea para testing o para eventuales necesidades de datos fuera de este proyecto).
</li><li><u>Discrecionales</u>: Cualquier otra función que pueda usarse manualmente en el "scope" global fuera de "<code>Interface</code>". Ejemplos:
<ul><li>"<code>execute</code>": Convierte un objeto "<code>Signal</code>" en una órden de trading, o una modificación/eliminación de ella. Si bien está entendida como de uso interno, se la supone pública para poder ejecutar órdenes de manera manual si es necesario.
</li><li>"<code>shutdown</code>": Finaliza la actividad del sistema. Lo hace en 3 etapas: primero desactiva todas las estrategias (para así también finalizar los "<code>tasks</code>"), luego las elimina, y finalmente desconecta el WebSocket.
</li></ul></li></ul>

<h3><u><b>
Modo de uso
</b></u></h3>

Suponiendo que ya se tienen estrategias programadas bajo la estructura de "<code>Strategy</code>":
<ol><li>Descargar el repositorio y ejecutar la descarga de sus dependencias.

```json
    git clone https://github.com/gsolaril/test-remarkets
    pip install -r requirements.txt
```

</li><li>Escribir los datos de cuenta de ReMarkets en el archivo "<code>auth/credentials.ini</code>".
</li><li>Agregar los scripts de estrategias dentro de la carpeta "<code>strategies</code>".
</li><li>Crear una nueva instancia de "<code>Interface</code>". Puede activarse el modo "<code>debug</code>" para printear los datos de mercado y las órdenes tal cual se reciben/envían a través del WebSocket.

```json
    interface = Interface(debug = False)
```

</li><li>Crear cuantas instancias de las estrategias se deseen, dentro de una lista. Algunos ejémplos genéricos, para mostrar la variabilidad de argumentos posibles, de estrategias de la misma clase, o de distintas clases. (Leer comentarios "#")

```json
    list_strategies = [
        MACrossover(
            name = "ma_crossover_YPF", # "etiqueta" de la instancia.
            symbols = { # configuraciones particulares para cada instrumento
                "YPFD/DIC23": {"size": 0.1, "period_lag": 12, "period_lead": 4},
                "YPFD/ENE24": {"size": 0.15, "period_lag": 15, "period_lead": 6},
            },
            max_risk = 0.2, take_profit_ratio = 2.0, # configuraciones globales
            tasks = {remove_old_orders: IntervalTrigger(minutes = 15)} # tareas paralelas
        ),
        MACrossover(
            name = "ma_crossover_PAMP",
            symbols = {
                "PAMP/ENE24": {"size": 0.2, "period_lag": 15, "period_lead": 4},
                "PAMP/MAR24": {"size": 0.5, "period_lag": 20, "period_lead": 8},
            },
            max_risk = 0.3, take_profit_ratio = 1.5,
            tasks = {remove_old_orders: IntervalTrigger(minutes = 15)}
        ),
        ATRMomentum(
            name = "atr_momentum",
            symbols = {"GGAL/DIC23": None, "DLR/JUN24": None},
            period_atr = 24, period_sar = 15,
            tasks = {}
        )
    ]
```

</li><li>Cargar estrategias al modelo:

```code
interface.load_strategies(list_strategies)
```

</li><li>Por seguridad, las instancias de las estrategias inician inactivas. Se las debe activar manualmente:

```code
interface.toggle_strategies(ma_crossover_YPF = True, ma_crossover_PAMP = True, atr_momentum = True)
```

</li></ol>A partir de este momento, las estrategias deberían estar funcionando. Vigilar atentamente la consola, como los logs en la carpeta "<code>logs</code>". Hay 5 "niveles" de mensaje, de menos a mas importante:
<ol><li>"<b><font color = "blue">debug</font></b>": Datos no tan relevantes, cuando "<code>debug = True</code>". Se recomienda usar solo en tareas de testeo, ya que registra todos y cada uno de los ticks de mercado. Lo cual puede saturar la consola y los archivos log.
</li><li>"<b><font color = "gray">info</font></b>": Datos de control o de interés general. Acciones, decisiones, valores relevantes, y otra información "de rutina".
</li><li>"<b><font color = "lime">success</font></b>": Información sobre procesos finalizados exitosamente. Conexiones exitosas, descargas, terminaciones, etc. Similar a "info" en términos de prioridad.
</li><li>"<b><font color = "yellow">warning</font></b>": Advertencias y alertas sobre elementos a prestar atención. También sobre procesos cuyas decisiones se alejaron del flujo común y corriente. No se generaron inconvenientes, pero podrían hacerlo a futuro.
</li><li>"<b><font color = "red">exception</font></b>": Eventos erráticos que generan impacto en el flujo normal del programa, pudiendo provocar interrupciones o comportamientos indeseables. El traceback completo del error es printeado en detalle. Normalmente estan salvaguardados por funciones que protegen el aspecto del "trading". (falta desarrollar esto mas en profundidad)
</li></ol>

<h3><u><b>
Con respecto a la estrategia provista
</b></u></h3>

La explicación completa a nivel matemático y procedimental, está en el archivo "<code>docs/rate_arb.md</code>". En principio, la lógica de la función "<code>Alma.on_tick</code>" fue formulada para arrojar señales para todos los ticks entrantes, sin ningun tipo de bloqueo. La idea no es simular la estrategia de trading en su operatoria común y corriente, sino proveer de información sobre las potenciales señales ("<code>Signal</code>") por oportunidades de arbitraje.

En principio: cada instancia del objeto "<code>Signal</code>" tiene asociado un atributo "<code>comment</code>" para que uno pueda proveer algún tipo de descripción sobre su origen o motivo (ej: si es producida por un cruce de médias móviles, se querría saber el valor de dichos indicadores). En el caso de la estrategia "<code>Alma</code>", el "<code>comment</code>" tendrá el siguiente formato:
```json
    da: 106.0, db: 104.0, ua: 100.00, rp: 0.0011, rt: -0.0015, exp: 38.25
```
Donde:
<ul><li>"<code>da</code>" significa "<b>derivative ask</b>": Precio ask del futuro (derivado).
</li><li>"<code>db</code>" significa "<b>derivative bid</b>": Precio bid del futuro (derivado).
</li><li>"<code>ua</code>" significa "<b>underlying ask</b>": Precio ask del subyacente (spot).
</li><li>"<code>rp</code>" significa "<b>rate payer</b>": Tasa de interés "payer" (colocadora).
</li><li>"<code>rt</code>" significa "<b>rate taker</b>": Tasa de interés "taker" (tomadora).
</li><li>"<code>exp</code>" significa "<b>expiration</b>": Días restantes para el vencimiento del futuro.
</li></ul>

La instancia de "<code>Signal</code>" posee varios parámetros adicionales, descriptos en detalle dentro del docstring de "<code>Signal</code>" (parte superior del script "<code>models/strategy.py</code>"). A fines prácticos, interesan 3 de ellos:
<ul><li>"<code>side</code>": Compra (BUY) o venta (SELL). 
</li><li>"<code>price</code>": Precio de ejecución (inmediata) de la órden. Si es una compra, es el precio "ask". Si es una venta, es el "bid".
</li><li>"<code>TP</code>": Precio de cierre de la posición implicada; básicamente igual al precio proyectado al cabo de un día, teniendo en cuenta a la tasa de interés calculada:
<ul><li>Si es una compra (BUY), "TP" es el precio "<b>bid</b>" aumentado por "<b>1 + tasa de interés taker</b>".
</li><li>Si es una venta (SELL), "TP" es el precio "<b>ask</b>" disminuido por "<b>1 - tasa de interés payer</b>".
</li></ul>
</li></ul>

Como todas las operaciones son de tamaño "<code>size = 1</code>" por ahora, La ganancia o pérdida proyectada sería la diferencia entre el "TP" y el "price":
<ul><li>Si es una compra (BUY), "<code>profit = TP - price</code>".
</li><li>Si es una venta (SELL), "<code>profit = price - TP</code>".
</li></ul>

<b>En resumen, <u>para interpretar el origen y resultado proyectado de una órden</u>:
<ul><li>Leer el comentario "comment" y sus 6 valores, especialmente las tasas ("rp" y "rt").
</li><li>Leer el valor de "side" para reconocer cual tasa se tomó para ejecutar la órden.
</li><li>Leer los valores de "price" y "TP". El valor absoluto de la diferencia es el profit esperado ("<code>pft</code>").
</li></ul></b>


<h3><u><b>
Tareas pendientes
</b></u></h3>

Como proyecto de prueba, quedan varias cosas a desarrollar a futuro. Algunas de ellas:
<ul><li>Reparar cierre manual por "<font color = "red"><b>keyboard interrupt</b></font>", el cual no termina de finalizar el proceso. Puede deberse a que dentro del nivel superficial de la biblioteca "<code>pyRofex</code>" no se tiene control sobre el "cliente" del WebSocket. Teóricamente está presente en "<code>pyRofex.components.environment</code>", pero falta tiempo de investigación. Entonces no puede manipularse la conexión y los feeds de manera directa (por ejemplo: para agregar "listeners" de <code>KeyboardInterrupt</code> a los callbacks, o para tener mayor control sobre el thread que contiene el proceso del WebSocket). Por ahora, si bien el sistema no opera luego del <code>KeyboardInterrupt</code>, al proceso se lo finaliza cerrando la consola del bash (lo cual es áltamente sub-optimo).
</li><li>Completar función "<code>Interface.on_update_orders</code>" y "<code>Strategy.on_order</code>". Hasta ahora solo se trabajó con órdenes de ejecución inmediata (a mejores bid/ask); "<code>pyRofex.OrderType.MARKET</code>". Con lo cual no se vió la necesidad de modificar o cancelar órdenes, como tampoco se vieron datos de WebSocket sobre órdenes pendientes siendo actualizadas/ejecutadas.
</li><li>Mejorar error handling para casos particulares como datos tick anómalos (ej: sin bids/asks, instrumentos vencidos, etc.) u órdenes mal formuladas (ej: "sizes" menores al mínimo permisible dado por las especificaciones del instrumento).
</li><li>Mejorar estructuras de iteración sobre estrategias. Hasta ahora, la función "<code>Interface._run_strategies</code>" recorre una por una estrategia, aplicandole los datos de mercado mas recientes; lo cual puede tener ineficiencias. Por ejemplo: si 2 estrategias operan el mismo instrumento, la búsqueda y copia de ticks históricos para ese instrumento se hace 2 veces, cuando en realidad podría hacerse una.
</li><li>Probar con otros portales de acceso diferentes a ReMarkets, como Live (Rofex).
</li><li>Crear algúna funcionalidad que accione órdenes basadas en SLs y TPs dentro de "<code>Interface</code>". Como la API de "<code>pyRofex</code>" no tiene tales parámetros en su endpoint para envío de órdenes, se podría crear algo que establezca las órdenes necesarias para producir el mismo efecto (ej.: inmediatamente luego de un "buy market", ubicar un "sell limit" por encima, a precio "TP".)
</li><li>Agregar funcionalidades de "sizing" a la estrategia "<code>Alma</code>": En lugar de todas órdenes de tamaño 1, agregar algún tipo de cálculo basado en máximo riesgo permisible por posición.