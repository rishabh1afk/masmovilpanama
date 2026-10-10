"""Theme and ask rules, tuned for Panamanian Spanish + English. Patterns run on
lower-cased, accent-stripped text."""
import re, unicodedata


def norm(t):
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


# Ordered by priority: the first matching theme becomes the item's primary theme.
THEMES = [
    ("Login, security & app blocks", r"opciones de desarrollador|modo desarrollador|depuracion|app modificada|modificaciones|ciberseguridad|error de seguridad|\bvpn\b|rooteado|\busb\b|\broot|modo dev|seguridad|bloque[oa]|iniciar sesion|inicio de sesion|\blogin|contrasena|\bclave\b|codigo de verific|verificacion|\botp\b|no (me )?deja (entrar|ingresar|iniciar|acceder)|no puedo (entrar|ingresar|acceder)|mi cuenta|crear (una )?cuenta|registr|sign in|log in|password|developer"),
    ("Payments & recharge", r"recarg|\bpag(o|os|ar|ue|ando|ado)\b|tarjeta|yappy|clave dinamica|auto ?pago|metodo de pago|transaccion|\bpay(ment)?\b|recharge|top.?up"),
    ("Billing & charges", r"factur|\bcobr|cargo|me robaron|robo|me quitaron|descont|reembols|devolucion|subieron|aumento|\bbill(ing)?\b|overcharg|charged"),
    ("App performance & bugs", r"no abre|se cierra|crash|\blent[ao]|error|falla|\bbug|no carga|cargando|actualiza|no funciona|se traba|se pega|se congela|pantalla en blanco|no sirve|slow|freez"),
    ("Network & coverage", r"senal|\bred\b|cobertura|internet|datos moviles|\b5g\b|\b4g\b|llamada|sin servicio|caida|fibra|wifi|conexion|terremoto|sismo|starlink|satelit|network|coverage|signal|outage"),
    ("Data plans & pricing", r"\bplan(es)?\b|paquete|precio|\bcaro|tarifa|megas|\bgb\b|prepago|postpago|ilimitad|bolsa de datos|price|expensive"),
    ("Customer service", r"atencion|servicio al cliente|agente|asesor|call ?center|whatsapp|sucursal|tienda|reclamo|queja|soporte|\bchat\b|nadie (responde|contesta)|customer service|support"),
    ("Promotions, rewards & content", r"promo|premio|puntos|beneficio|recompens|fan ?zone|disney|\bmax\b|paramount|universal\+|sorteo|concurso|oferta|regalo|futbol|reward|giveaway"),
]
THEMES_RX = [(n, re.compile(p)) for n, p in THEMES]
OTHER = "General / other"

# What users are asking for (pain point -> implied request).
ASKS = [
    ("Stop false security blocks (USB debugging, 'modified app', VPN)", r"opciones de desarrollador|modo desarrollador|depuracion|\busb\b|developer option|app modificada|apps? modificada|detectad[oa]s? modificaciones|modificaciones no autorizadas|ciberseguridad|error de seguridad|\bvpn\b|rooteado"),
    ("Fix sign-in, verification codes & account access", r"no (me )?(deja|permite) (entrar|ingresar|iniciar|acceder|registr)|no puedo (entrar|ingresar|acceder|iniciar|registr)|iniciar sesion|inicio de sesion|contrasena|codigo|verificacion|\botp\b|\blogin\b|sign in|password"),
    ("Fix failed payments, recharges & card errors", r"(pago|pagar|recarga|recargar|tarjeta|yappy|transaccion)[^.]{0,50}(no |error|falla|rechaz|declin|problema)|no (me )?(deja|permite|puedo) (pagar|recargar|hacer (el|la|un|una) (pago|recarga))|(error|falla|problema)[^.]{0,30}(pago|pagar|recarga|tarjeta)|cobr[^.]{0,20}(doble|dos veces)"),
    ("Stop price hikes / unexpected charges without notice", r"subieron|aumento|aumentaron|me (robaron|quitaron|descontaron)|cobr(o|an|aron) (de mas|indebid)|sin avisar|cargos? (extra|no autorizad)|robo"),
    ("Improve signal & coverage, fix outages", r"senal|cobertura|sin servicio|se va la (senal|red|internet)|caida|no hay (internet|senal|servicio)|internet (lento|malo|pesimo)|red (lenta|mala|pesima)|no tengo (internet|senal|servicio)|outage|no signal"),
    ("Faster, more helpful customer service", r"atencion|servicio al cliente|nadie (responde|contesta|atiende)|no (responden|contestan|atienden)|agente|asesor|call ?center|horas? esperando|customer service"),
    ("Make the app faster & more stable", r"no abre|se cierra|\blent[ao]|no carga|cargando|se traba|se pega|se congela|crash|no funciona|no sirve|error|falla|slow|freez"),
    ("Cheaper plans / more data & better offers", r"\bcaro|mas datos|mejores? (planes|ofertas|precios|promociones)|baj(en|ar) (el |los )?precio|precio|megas|expensive|cheaper"),
    ("Show balance, usage & invoices correctly", r"(saldo|consumo|factura|datos)[^.]{0,30}(no (aparece|muestra|sale|carga|actualiza)|incorrect|mal)|no (me )?(aparece|muestra|sale) (el|mi) (saldo|consumo|factura)"),
]
ASKS_RX = [(n, re.compile(p)) for n, p in ASKS]
REQUEST_MARKERS = re.compile(r"deberian|por favor|porfa|\bpls\b|please|quisiera|me gustaria|ojala|necesito|pongan|agreguen|arreglen|solucionen|mejoren|habiliten|quiten|should|would be nice|add an option|need")


APP_ONLY = {"App performance & bugs", "Make the app faster & more stable"}
APP_WORD = re.compile(r"\bapp|aplicacion")
STORES = {"google_play", "app_store"}


def _ok(name, t, channel):
    # On social/X, "no funciona" usually means the line/service, so app-specific labels need the word "app".
    return name not in APP_ONLY or channel in STORES or bool(APP_WORD.search(t))


def themes_for(text, channel=None):
    t = norm(text)
    hits = [n for n, rx in THEMES_RX if rx.search(t) and _ok(n, t, channel)]
    return hits or [OTHER]


def asks_for(text, channel=None):
    t = norm(text)
    return [n for n, rx in ASKS_RX if rx.search(t) and _ok(n, t, channel)]


def has_request(text):
    return bool(REQUEST_MARKERS.search(norm(text)))
