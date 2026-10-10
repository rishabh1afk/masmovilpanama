"""Product taxonomy: categories -> sub-issues (keyword seeds, Panamanian Spanish + English).
Patterns run on lower-cased, accent-stripped text (see taxonomy.norm). Bump RULES_VERSION when editing."""
RULES_VERSION = 5

APP_CATEGORIES = [
    "Bugs & Technical Issues", "Payments & Transactions", "Account & Services",
    "Connectivity & Accessibility", "UX & Navigation", "Missing Features",
]
NONAPP_CATEGORY = "Non-app / service issues"

# severity: 3 = blocker (cannot use app / cannot pay), 2 = major (feature broken / money or info wrong), 1 = minor (annoyance)
SUBISSUES = [
    # ---- Bugs & Technical Issues ----
    dict(id="bug_security_block", cat="Bugs & Technical Issues", sev=3,
         label="App blocked by security check ('modified app', USB debugging / Developer Options, VPN)",
         rx=r"opciones de desarrollador|modo desarrollador|depuracion|\busb\b|developer option|app(s|licacion)? modificada|detectad[oa]s? modificaciones|modificaciones (no autorizadas|en la app)|ciberseguridad|error de seguridad|\bvpn\b|rooteado|\broot(ed)?\b|fuente confiable|(descargarla|instalarla|descargue|descargar|instalar)[^.]{0,20}desde (el )?(google )?play|no fue instalada desde|que la descargue de google play"),
    dict(id="bug_login", cat="Bugs & Technical Issues", sev=3,
         label="Can't log in / sign-in & verification code failures",
         rx=r"no (me )?(deja|permite|dejaba) (entrar|ingresar|iniciar|acceder|loguear)|no (puedo|pude|logro) (entrar|ingresar|iniciar|acceder|registrar)|iniciar sesion|inicio de sesion|contrasena|codigo (de verificacion|no llega|nunca llega)|no (me )?llega (el|ningun) codigo|\botp\b|\blogin\b|me (saca|bota|expulsa)|cierra (la )?sesion|sign in|log in|password"),
    dict(id="bug_crash", cat="Bugs & Technical Issues", sev=3,
         label="App won't open, crashes, freezes or keeps loading",
         rx=r"no (me )?abre|no quiere abrir|se cierra|se (traba|congela|pega|queda pegad)|crash|pantalla (en )?blanc|no carga|se queda cargando|cargando y|freez"),
    dict(id="bug_errors", cat="Bugs & Technical Issues", sev=2,
         label="Errors / 'under maintenance' / features not working",
         rx=r"\berror\b|\bfalla\b|fallas|mantenimiento|no funciona|no sirve|intente (mas tarde|nuevamente)|ha ocurrido|algo salio mal|not working"),
    dict(id="bug_compat", cat="Bugs & Technical Issues", sev=2,
         label="Install / device compatibility problems",
         rx=r"no (es )?compatible|no (se )?(puede|deja|pude) instalar|no (me )?(deja|permite) (descargar|instalar)|huawei|version de android|mi (dispositivo|telefono|celular) no"),
    # ---- Payments & Transactions ----
    dict(id="pay_failed", cat="Payments & Transactions", sev=3,
         label="Payments / recharges fail or card is rejected",
         rx=r"(pago|pagar|recarga|recargar|tarjeta|transaccion)[^.]{0,50}(no (pasa|procede|se (proceso|realizo|completo))|error|falla|rechaz|declin|no (me )?(deja|permite|acepta))|no (me )?(deja|permite|puedo|pude) (pagar|recargar|hacer (el|la|un|una) (pago|recarga))|(error|falla|problema)[^.]{0,30}(pago|pagar|recarga|tarjeta)"),
    dict(id="pay_extra_day", cat="Payments & Transactions", sev=2,
         label="Recharge bonus ('día extra' / extra days) not selectable or not applied",
         rx=r"dia(s)? (extra|adicional|gratis)|un dia mas|regalan un dia|bono de (recarga|dias)"),
dict(id="pay_charged_not_applied", cat="Payments & Transactions", sev=3,
         label="Charged but recharge / package not applied, or double charge",
         rx=r"(descontaron|cobraron|cobrado|rebajaron|me cobran)[^.]{0,80}(no (me )?(activaron|llego|aplico|mandaron|dieron)|nunca|todavia)|no (me )?(activaron|mandaron|llego|llega) (el |la |mi )?(plan|paquete|data|recarga)[^.]{0,60}(cobr|descont)|no me mandaron la data y me la cobraron|todavia estoy esperando el paquete|doble cobro|cobr[a-z]* dos veces|pague y no"),
    dict(id="pay_autopay", cat="Payments & Transactions", sev=2,
         label="Auto-pay / recurring payments can't be set up or fail",
         rx=r"auto ?pagos?|pagos? recurrentes?|pago automatico|domicili"),
    dict(id="pay_balance_not_accepted", cat="Payments & Transactions", sev=2,
         label="Phone balance / scratch-card credit can't be used for promos or packages",
         rx=r"(con|usar|utilizar|canjear|comprar)[^.]{0,25}(el |mi |su )?saldo|saldo (de|en) (la )?tarjeta|tarjeta (raspa|prepago)|teniendo saldo|saldo normal|saldo que ya tienes|saldo q uno"),
    dict(id="pay_methods", cat="Payments & Transactions", sev=2,
         label="Limited payment methods (Yappy-only offers, card/ACH options)",
         rx=r"yappy|metodos? de pago|forma de pago|\bach\b|clave sistema|tarjeta de debito|agregar (una )?tarjeta|guardar (la )?tarjeta|guardar pagos|paypal"),
    dict(id="pay_billing", cat="Payments & Transactions", sev=2,
         label="Bill / invoice visibility and payment in app",
         rx=r"factura[^.]{0,40}(no (aparece|sale|muestra|carga|puedo ver)|ver|descargar|pdf)|pagar (la |mi )?factura|estado de cuenta"),
    # ---- Account & Services ----
dict(id="acct_usage", cat="Account & Services", sev=2,
         label="Can't see data / minutes usage or plan details",
         rx=r"(ver|muestra|saber|dice|veo)[^.]{0,25}(los minutos|mi consumo|el consumo|cuantos (gb|megas)|la data|mis datos)|ni (se|veo) cual es mi consumo|no dice (ni )?cuantos|info(rmacion)? (de|sobre) (mi |el )?plan|(saldo|consumo|minutos)[^.]{0,30}no (aparece|muestra|sale|actualiza)"),
    dict(id="acct_rewards", cat="Account & Services", sev=1,
         label="Rewards (premios, cupones, puntos, giros) unclear, expiring or not delivered",
         rx=r"premio|cupon|\bpuntos\b|giro gratis|jugada|recompensa|regalos"),
    dict(id="acct_plans", cat="Account & Services", sev=2,
         label="Plans / packages: can't find, buy or change in app",
         rx=r"(comprar|compra|activar|cambiar)[^.]{0,30}(paquete|plan|bolsa)|(paquete|plan)(es)?[^.]{0,30}(no (aparece|sale|deja|permite)|desaparec)|planes disponibles"),
    dict(id="acct_lines", cat="Account & Services", sev=1,
         label="Manage multiple lines / add or link a number or account",
         rx=r"(agregar|anadir|vincular|registrar)[^.]{0,20}(linea|numero|cuenta|servicio)|otras? lineas?|varias lineas|mis lineas|linea fija|cuenta (residencial|hogar)"),
    # ---- Connectivity & Accessibility ----
    dict(id="conn_data_required", cat="Connectivity & Accessibility", sev=3,
         label="App needs mobile data / doesn't work on Wi-Fi or with zero balance",
         rx=r"(necesit|requier|pide|exige)[a-z]*[^.]{0,25}(datos|data|megas|saldo)|no funciona con (el )?wi.?fi|solo (funciona )?con datos|sin (datos|data|saldo|megas)|si no (tienes|tengo|hay) (datos|data|saldo|megas)|se (me )?acab[ao] (la )?(data|datos|saldo)|con wi.?fi no"),
    dict(id="conn_update", cat="Connectivity & Accessibility", sev=2,
         label="Forced or broken updates",
         rx=r"actualiza(r|cion|ciones)[^.]{0,40}(no|obligatori|pide|cada|siempre|despues|desde)|(pide|obliga)[^.]{0,15}actualizar|despues de (la )?actualiza|desde (la )?(ultima|nueva) actualiza|update"),
    # ---- UX & Navigation ----
    dict(id="ux_ads", cat="UX & Navigation", sev=1,
         label="Too many ads, pop-ups, notifications or SMS promos",
         rx=r"(exceso de|mucha|muchas|tanta|demasiad[ao]s?) (publicidad|notificaciones|anuncios|mensajes|promociones)|notificaciones|pop.?up|\bspam\b|envian muchas publicidad|para ver publicidad"),
    dict(id="ux_confusing", cat="UX & Navigation", sev=1,
         label="Hard to use / confusing navigation / worse after redesign",
         rx=r"dificil|complicad|confus|no encuentro|no se encuentra|poco intuitiv|antes (era|estaba) mejor|nueva (version|app|aplicacion)[^.]{0,30}(peor|mala|horrible)|diseno|interfaz|navegar"),
    dict(id="ux_slow", cat="UX & Navigation", sev=1,
         label="Slow app / takes long to load",
         rx=r"\blent[ao]\b|lentitud|tarda (mucho|demasiado)|demora (mucho)?|slow"),
    # ---- Missing Features ----
    dict(id="feat_share_balance", cat="Missing Features", sev=1,
         label="Share / transfer balance or data to another line",
         rx=r"(pasar|transferir|compartir|enviar|regalar) (saldo|datos|data|megas|balance)"),
    dict(id="feat_request", cat="Missing Features", sev=1,
         label="Other explicit feature requests",
         rx=r"deberian (agregar|poner|permitir|tener|incluir|habilitar)|agreguen|pongan (la )?opcion|me gustaria que|seria (bueno|genial|excelente) (que|poder)|falta (la )?opcion|que (se )?pueda|ojala (pongan|agreguen|se pueda)|habiliten|should add|would be nice"),
]

NONAPP = [
    dict(id="svc_network", cat=NONAPP_CATEGORY, sev=2, label="Network signal, coverage & outages",
         rx=r"senal|cobertura|sin servicio|caida|no hay (internet|senal|servicio)|internet (lento|malo|pesimo)|red (lenta|mala|pesima)|no tengo (internet|senal|servicio)|5g|fibra|outage|no signal|se va la (senal|luz|red|internet)"),
    dict(id="svc_pricing", cat=NONAPP_CATEGORY, sev=2, label="Price increases, bill hikes & expensive plans",
         rx=r"subieron|aumento|aumentaron|\bcaro\b|precio|tarifa|sin (previo )?avis|me (robaron|estan robando)|cobr(o|an|aron) (de mas|indebid)|cargos? (extra|no autorizad)"),
    dict(id="svc_support", cat=NONAPP_CATEGORY, sev=2, label="Customer service & call-centre experience",
         rx=r"atencion|servicio al cliente|nadie (responde|contesta|atiende)|no (responden|contestan|atienden)|agente|asesor|call ?center|sucursal|esperando|llamadas? (de venta|para ofrecer)|me llaman"),
]

APP_WORDS = r"\bapp\b|\bapps\b|\+app|aplicacion|mi mas app|la apli"
REQUEST_MARKERS = r"deberian|por favor|porfa|\bpls\b|please|quisiera|me gustaria|ojala|necesito|necesitamos|pongan|agreguen|arreglen|solucionen|mejoren|habiliten|quiten|permitan|should|would be nice|espero que"
