<center><font color = "yellow"><h2><b><u>
Arbitraje de spots y futuros
</font></u></b></h2></center>

Esta es una pequeña guía cuyo objetivo es justificar las fórmulas utilizadas en la estrategia de "<code>strategies/alma.py</code>", dentro de la función "<code>Alma.calc_daily_rates(...)</code>".

<b><u><h3>Sobre las tasas</h3></u></b>

Partimos de la base de que todo contrato futuro de precio actual "$F(t)$" tiende a aproximarse al precio del instrumento subyacente "$S(t)$" al acercarse su fecha de vencimiento "$T$". Es decir que el premium "$P(t) = F(t) - S(t)$" tiende a cero:

$$lim_{t \rightarrow T} P(t) = 0$$

Existen 2 casos teóricos: 
* <b><u>Contango</b></u>: los compradores de futuros especulan con un subyacente que subirá de precio. Es decir que el precio del futuro convergerá en descenso con respecto al subyacente.
* <b><u>Backward(ation)</b></u>: los vendedores de futuros especulan con un subyacente que bajará de precio. Luego el precio del futuro convergerá en ascenso con hacia el subyacente.

La tasa de interés "$R$" es la velocidad con la que el futuro se valoriza o deprecia acercandose a la fecha de vencimiento. Supongo en primer lugar, que la tasa de interés del subyacente es nula...
* <b><u>Contango</b></u>: El futuro se deprecia. Al entrar en short, tomo prestado el valor del futuro, y pago su tasa "$R_P$": mi rol es de "<b><u>P</u>ayer</b>".
* <b><u>Backward</b></u>: El futuro se valoriza. Al entrar en long, alguien toma prestado su valor, y me paga la tasa "$R_T$": mi rol es de "<b><u>T</u>aker</b>".

Por otro lado, teóricamente:
* Bajo condición de "<b><u>Contango"</u></b>: "$F(t) > S(t)$"...<br>A mas lejana la fecha de vencimiento, mas elevado es el valor del futuro: <br>"$lim_{t \rightarrow - ∞} F(t) = +∞$".<br>Luego: "$lim_{t \rightarrow - ∞} P(t) = ∞ - S(t) = ∞$"
* Bajo condición de "<b><u>Backward</u></b>": "$F(t) < S(t)$"...<br>A mas lejana la fecha de vencimiento, mas cercano a cero es el valor del futuro:
<br>"$lim_{t \rightarrow - ∞} F(t) = 0$".<br>Luego: "$lim_{t \rightarrow - ∞} P(t) = 0 - S(t) = - S(t)$"

Puede hallarse que las expresiones que determinan al premium en cada caso, son las siguientes:
<br>$\fbox{Eqs. 1}$
* <b><u>Contango</b></u>:
"$\fbox{Eq. 1a} \; P(t) = S(e^{+R_P(T - t)} - 1)$".
<br>Notar que: "$P(t \rightarrow -∞) \Rightarrow F - S = +∞ \Rightarrow F = +∞$"
* <b><u>Backward</b></u>:
"$\fbox{Eq. 1b} \; P(t) = S(e^{-R_T(T - t)} - 1)$"
<br>Notar que: "$P(t \rightarrow -∞) \Rightarrow F - S = -S \Rightarrow F = 0$"

También, en ambos casos: "$P(t = T) \Rightarrow F - S = 0$"

Despejando las tasas "$R$", puedo hallar que:
* <b><u>Contango</b></u>:
"$\fbox{Eq. 2a} \; R_P = + \ln{(F/S)} / (T - t)$"
<br>De modo que si "$F > S \Rightarrow R_P > 0$"
* <b><u>Backward</b></u>:
"$\fbox{Eq. 2b} \; R_T = - \ln{(F/S)} / (T - t)$"
<br>De modo que si "$F < S \Rightarrow R_T > 0$"

Para normalizar los cálculos, suponemos que "$t$" y "$T$" se mide en <u><b>días</b></u>. Luego, la tasa puede expresarse en "<b>%/día</b>". A futuro tendría que ser una unidad consistente con el marco temporal de la frecuencia de ejecución y/o rebalanceo de las posiciones.

<b><u><h3>Efecto del bid-ask spread</h3></u></b>

Como hipótesis previas, se debe establecer que tanto las <u>tasas</u> como los <u>precios</u> del subyacente, se mantienen deseablemente <u><b>constantes</b></u> dentro del marco temporal establecido (en este caso, un <u>día</u>). Si bien esto es una idealización y es altamente ineficaz en la realidad, se hace para que los siguientes cálculos tengan sentido teórico.

Según la <b><u>ecuación 1</b></u>
para cualquier caso "<b>a</b>" o "<b>b</b>":<br>
$\Rightarrow F - S = S(e^{\pm R(T - t)} - 1)$<br>
Si el exponente es pequeño, por aproximación de Taylor:<br>
$\Rightarrow F - S = \pm SR(T - t)$<br>
Ahora bien: suponer 2 momentos próximos en el tiempo:<br>
$\Rightarrow F_1 - S_1 = \pm S_1R(T - t_1)$<br>
$\Rightarrow F_2 - S_2 = \pm S_2R(T - t_2)$<br>
Restando ambos premiums, y suponiendo "$S_1 = S_2 = S$":<br>
$\Rightarrow (F_2 - F_1) - (S - S) = \pm SR((T - t_2) - (T - t_1))$<br>
Cancelando "$S$" y "$T$":
"$\fbox{Eq. 3} \; F_1 - F_2 = \pm SR(t_2 - t_1)$"

Esto solo es posible si la distancia temporal entre operaciones es lo suficientemente proximo como para que las hipótesis establecidas se mantengan válidas.

<b><u><h3>Sobre los retornos</h3></u></b>

Para neutralizar el riesgo, se cubre a la posición del futuro con la posición opuesta del subyacente. De modo que el premium tienda a cero hacia la fecha de vencimiento "$T$".

En el caso de "<b><u>Contango</u></b>", al instante "$t_E$" se entra en short premium: "$P = F - S > 0$". <br> Es decir:
* Se cobra "$+F_{BE}$", siendo el precio <b><u>B</u>id</b> al que se vende el futuro.
* Se paga "$-S_{AE}$", siendo el precio <b><u>A</u>sk</b> al que se compra el subyacente.
* Se cierra la posición en el instante "$t_C$", en los lados opuestos de cada instrumento. Es decir: "$-F_{AC}$" y "$+S_{BC}$" respectivamente.

La <u><b>ganancia</b></u> "$G$" sería igual a:
"$G = F_{BE} - S_{AE} - F_{AC} + S_{BC}$"
<br>A precio subyacente constante:
"$G = F_{BE} - F_{AC} - S_A + S_B$"
<br>Agrupando por instrumento:
"$G = (F_{AC} - F_{BE}) - (S_A - S_B)$"
<br>Aplicando la <u>ecuación 3</u>, dada la cercanía entre "$t_E$" y "$t_C$":<br>
$\Rightarrow G = R_P (t_C - t_E) (F_A - F_B) - (S_A - S_B)$
<br>Midiendo la duración de la posición como "$n$" días:
$$ \fbox{Eq. 4a} \; G_P = n R_P (F_A - F_B) - (S_A - S_B) $$

El caso de "<b><u>Backwardation</u></b>" es similar, pero se entra en long premium: "$P = F - S < 0$". El resultado es exactamente similar, solo que con los signos invertidos ya que las posiciones se componen de las entradas/salidas opuestas:
* Se paga "$-F_{AE}$", siendo el precio <b><u>B</u>id</b> al que se compra el futuro.
* Se cobra "$+S_{BE}$", siendo el precio <b><u>A</u>sk</b> al que se vende el subyacente.
* Se cobra "$+F_{BC}$", siendo el precio <b><u>A</u>sk</b> al que se vende el futuro.
* Se paga "$-S_{AC}$", siendo el precio <b><u>B</u>id</b> al que se compra el subyacente.

$$ \fbox{Eq. 4b} \; G_T = n R_T (F_B - F_A) - (S_B - S_A) $$

