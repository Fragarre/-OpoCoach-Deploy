import base64
import stripe
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel

from app.analisis_rendimiento import generar_analisis_rendimiento
from app.chat_convocatoria import responder_chat
from app.pdf_examen import generar_pdf_preguntas
from app.pdf_soluciones import generar_pdf_soluciones
from app.auth import UsuarioAutenticado, usuario_actual
from app.billing import crear_checkout_suscripcion, crear_portal_cliente
from app.subscriptions import (
    procesar_webhook,
    obtener_estado_suscripcion,
    obtener_customer_id_stripe,
)
from app.postgres import comprobar_postgres
from app.repositorio_contenidos import (
    comprobar_base,
    convocatoria_esta_activa,
    obtener_convocatorias,
    obtener_resumen_convocatoria,
)
from app.schemas import (
    Convocatoria,
    CrearSimulacroRequest,
    DisponibilidadParte,
    EstadoBase,
    GuardarRespuestasRequest,
    PreguntaCorregida,
    PreguntaSimulacro,
    ResultadoSimulacro,
    ResumenConvocatoria,
    Simulacro,
    SimulacroCreado,
    SimulacroListado,
    UsuarioActual,
    TemaTest,
    NormaTest,
    CrearTestRequest,
    TestCreado,
    CheckoutSessionResponse,
    PortalSessionResponse,
    EstadoSuscripcion,
)
from app.tests_opocoach import (
    obtener_puntos_temario_test,
    obtener_normas_test,
    crear_test,
)
from app.simulacros import (
    crear_simulacro,
    finalizar_simulacro,
    guardar_respuestas,
    obtener_correccion,
    obtener_disponibilidad,
    obtener_preguntas_para_realizar,
    obtener_simulacro,
    listar_simulacros,
    eliminar_simulacro,
    obtener_resultado_guardado,
    obtener_tiempo_correccion,
    obtener_resultado_para_analisis,
    obtener_resultado_acumulado,
)

class ChatMensajeRequest(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    convocatoria_id: int
    pregunta: str
    mensajes_previos: list[ChatMensajeRequest] = []
    modo: str = "CONVOCATORIA"



def _estado_acceso(user_id):
    return obtener_estado_suscripcion(user_id)


def _exigir_suscripcion_activa(user_id) -> dict:
    estado = _estado_acceso(user_id)
    if not estado["suscrito"]:
        raise HTTPException(
            status_code=403,
            detail=(
                "Esta función requiere una suscripción activa a OpoCoach."
            ),
        )
    return estado


def _obtener_prueba_accesible(simulacro_id: int, user_id):
    prueba = obtener_simulacro(simulacro_id, user_id)
    if prueba is None:
        raise HTTPException(status_code=404, detail="Simulacro no encontrado")
    return prueba


def _exigir_lectura_prueba(simulacro_id: int, user_id) -> tuple[dict, dict]:
    prueba = _obtener_prueba_accesible(simulacro_id, user_id)
    estado = _estado_acceso(user_id)

    if (
        bool(prueba.get("es_prueba_gratuita"))
        or estado["suscrito"]
        or estado.get("acceso_historico_activo", False)
    ):
        return prueba, estado

    raise HTTPException(
        status_code=403,
        detail=(
            "El plazo de acceso al histórico de esta suscripción ha finalizado."
        ),
    )


def _exigir_escritura_prueba(simulacro_id: int, user_id) -> tuple[dict, dict]:
    prueba = _obtener_prueba_accesible(simulacro_id, user_id)
    estado = _estado_acceso(user_id)

    if bool(prueba.get("es_prueba_gratuita")) or estado["suscrito"]:
        return prueba, estado

    if estado.get("acceso_historico_activo", False):
        raise HTTPException(
            status_code=403,
            detail=(
                "Tras la baja, el histórico está disponible únicamente en modo "
                "lectura y para descarga de PDFs."
            ),
        )

    raise HTTPException(
        status_code=403,
        detail=(
            "El plazo de acceso al histórico de esta suscripción ha finalizado."
        ),
    )


app = FastAPI(
    title="OpoCoach API",
    version="0.9.0",
    description=(
        "Backend paralelo de migración: contenidos SQLite, persistencia "
        "PostgreSQL y autenticación Supabase."
    ),
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/postgres/estado")
def estado_postgres() -> dict[str, str]:
    try:
        return comprobar_postgres()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"PostgreSQL no disponible: {exc}",
        ) from exc


@app.get("/api/v1/base/estado", response_model=EstadoBase)
def estado_base() -> EstadoBase:
    return EstadoBase(**comprobar_base())


@app.get("/api/v1/convocatorias", response_model=list[Convocatoria])
def listar_convocatorias() -> list[Convocatoria]:
    return [Convocatoria(**fila) for fila in obtener_convocatorias()]


@app.get(
    "/api/v1/convocatorias/{convocatoria_id}/resumen",
    response_model=ResumenConvocatoria,
)
def resumen_convocatoria(convocatoria_id: int) -> ResumenConvocatoria:
    fila = obtener_resumen_convocatoria(convocatoria_id)
    if fila is None:
        raise HTTPException(status_code=404, detail="Convocatoria no encontrada")
    return ResumenConvocatoria(**fila)


@app.get("/api/v1/me", response_model=UsuarioActual)
def me(usuario: UsuarioAutenticado = Depends(usuario_actual)) -> UsuarioActual:
    return UsuarioActual(id=str(usuario.id), email=usuario.email)




@app.post("/api/v1/billing/webhook")
async def stripe_webhook_api(request: Request) -> dict[str, str]:
    payload = await request.body()
    signature = request.headers.get("stripe-signature")

    if not signature:
        raise HTTPException(
            status_code=400,
            detail="Falta la cabecera Stripe-Signature.",
        )

    try:
        tipo = procesar_webhook(payload, signature)
        return {"received": "true", "type": tipo}
    except stripe.SignatureVerificationError as exc:
        raise HTTPException(
            status_code=400,
            detail="Firma Stripe no válida.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Payload Stripe no válido.",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.get(
    "/api/v1/billing/subscription",
    response_model=EstadoSuscripcion,
)
def estado_suscripcion_api(
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> EstadoSuscripcion:
    return EstadoSuscripcion(
        **obtener_estado_suscripcion(usuario.id)
    )


@app.post(
    "/api/v1/billing/checkout",
    response_model=CheckoutSessionResponse,
    status_code=201,
)
def crear_checkout_api(
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> CheckoutSessionResponse:
    try:
        estado = obtener_estado_suscripcion(usuario.id)
        if estado["suscrito"]:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Ya existe una suscripción activa para esta cuenta. "
                    "Utiliza Gestionar suscripción."
                ),
            )

        checkout = crear_checkout_suscripcion(
            user_id=usuario.id,
            email=usuario.email,
            customer_id=obtener_customer_id_stripe(usuario.id),
        )
        return CheckoutSessionResponse(
            id=checkout.id,
            url=checkout.url,
        )
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except stripe.StripeError as exc:
        mensaje = getattr(exc, "user_message", None) or str(exc)
        raise HTTPException(
            status_code=502,
            detail=f"Stripe no ha podido crear el Checkout: {mensaje}",
        ) from exc


@app.post(
    "/api/v1/billing/portal",
    response_model=PortalSessionResponse,
    status_code=201,
)
def crear_portal_api(
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> PortalSessionResponse:
    try:
        customer_id = obtener_customer_id_stripe(usuario.id)
        if not customer_id:
            raise HTTPException(
                status_code=404,
                detail="Esta cuenta todavía no tiene un cliente Stripe asociado.",
            )

        portal = crear_portal_cliente(customer_id)
        return PortalSessionResponse(url=portal.url)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except stripe.StripeError as exc:
        mensaje = getattr(exc, "user_message", None) or str(exc)
        raise HTTPException(
            status_code=502,
            detail=f"Stripe no ha podido abrir el portal: {mensaje}",
        ) from exc


@app.post("/api/v1/chat")
def chat_api(
    datos: ChatRequest,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> dict:
    """
    Chat autenticado de OpoCoach.

    CONVOCATORIA:
        Restringe la respuesta al corpus de la convocatoria indicada y a la
        base de conocimiento funcional de OpoCoach.
    GENERAL:
        Usa conocimiento general del modelo y no recupera el corpus.
    """
    try:
        _exigir_suscripcion_activa(usuario.id)

        if datos.convocatoria_id <= 0:
            raise ValueError("La convocatoria no es válida.")

        # Verifica que la convocatoria exista también en modo GENERAL, porque
        # el frontend mantendrá siempre una convocatoria activa.
        if obtener_resumen_convocatoria(datos.convocatoria_id) is None:
            raise ValueError("La convocatoria no existe.")
        if not convocatoria_esta_activa(datos.convocatoria_id):
            raise ValueError("La convocatoria no está activa.")

        mensajes = [
            {
                "role": mensaje.role,
                "content": mensaje.content,
            }
            for mensaje in datos.mensajes_previos[-8:]
            if mensaje.role in {"user", "assistant"}
            and mensaje.content.strip()
        ]

        return responder_chat(
            convocatoria_id=datos.convocatoria_id,
            pregunta=datos.pregunta,
            mensajes_previos=mensajes,
            modo=datos.modo,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc



@app.get(
    "/api/v1/convocatorias/{convocatoria_id}/simulacro/disponibilidad",
    response_model=list[DisponibilidadParte],
)
def disponibilidad_simulacro(
    convocatoria_id: int,
    origen: list[str] = Query(...),
    fuente: list[str] = Query(default=["REAL", "IA"]),
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> list[DisponibilidadParte]:
    try:
        _exigir_suscripcion_activa(usuario.id)
        return [
            DisponibilidadParte(**x)
            for x in obtener_disponibilidad(convocatoria_id, origen, fuente)
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc



@app.get("/api/v1/simulacros", response_model=list[SimulacroListado])
def mis_simulacros_api(
    convocatoria_id: int | None = None,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> list[SimulacroListado]:
    try:
        estado = _estado_acceso(usuario.id)
        filas = listar_simulacros(
            usuario.id,
            convocatoria_id=convocatoria_id,
            tipo_prueba="SIMULACRO",
        )
        if not (
            estado["suscrito"]
            or estado.get("acceso_historico_activo", False)
        ):
            filas = [
                fila for fila in filas
                if bool(fila.get("es_prueba_gratuita"))
            ]
        return [SimulacroListado(**fila) for fila in filas]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc



@app.get(
    "/api/v1/convocatorias/{convocatoria_id}/tests/temas",
    response_model=list[TemaTest],
)
def temas_disponibles_test_api(
    convocatoria_id: int,
    fuente: list[str] = Query(default=["REAL", "IA"]),
    _usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> list[TemaTest]:
    try:
        return [
            TemaTest(**fila)
            for fila in obtener_puntos_temario_test(convocatoria_id, fuente)
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(
    "/api/v1/convocatorias/{convocatoria_id}/tests/normas",
    response_model=list[NormaTest],
)
def normas_disponibles_test_api(
    convocatoria_id: int,
    fuente: list[str] = Query(default=["REAL", "IA"]),
    _usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> list[NormaTest]:
    try:
        return [
            NormaTest(**fila)
            for fila in obtener_normas_test(convocatoria_id, fuente)
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/tests", response_model=list[SimulacroListado])
def mis_tests_api(
    convocatoria_id: int | None = None,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> list[SimulacroListado]:
    estado = _estado_acceso(usuario.id)
    filas = listar_simulacros(
        usuario.id,
        convocatoria_id=convocatoria_id,
        tipo_prueba="TEST",
    )
    if not (
        estado["suscrito"]
        or estado.get("acceso_historico_activo", False)
    ):
        filas = [
            fila for fila in filas
            if bool(fila.get("es_prueba_gratuita"))
        ]
    return [SimulacroListado(**fila) for fila in filas]


@app.post("/api/v1/tests", response_model=TestCreado, status_code=201)
def nuevo_test_api(
    datos: CrearTestRequest,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> TestCreado:
    try:
        estado = _estado_acceso(usuario.id)
        es_prueba_gratuita = not estado["suscrito"]

        if es_prueba_gratuita:
            if not estado["prueba_gratuita_disponible"]:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "La prueba gratuita de esta cuenta ya ha sido utilizada. "
                        "Activa una suscripción para crear nuevos tests."
                    ),
                )
            if datos.numero_preguntas > 10:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "La prueba gratuita permite un máximo de 10 preguntas. "
                        "Activa una suscripción para crear tests más largos."
                    ),
                )

        return TestCreado(
            **crear_test(
                convocatoria_id=datos.convocatoria_id,
                numero_preguntas=datos.numero_preguntas,
                temas_seleccionados=datos.temas_seleccionados,
                normas_seleccionadas=datos.normas_seleccionadas,
                modo_seleccion=datos.modo_seleccion,
                fuentes=datos.fuentes,
                user_id=usuario.id,
                es_prueba_gratuita=es_prueba_gratuita,
            )
        )
    except HTTPException:
        raise
    except ValueError as exc:
        mensaje = str(exc)
        if "prueba gratuita" in mensaje.lower():
            raise HTTPException(status_code=403, detail=mensaje) from exc
        raise HTTPException(status_code=400, detail=mensaje) from exc


@app.post(
    "/api/v1/simulacros",
    response_model=SimulacroCreado,
    status_code=201,
)
def nuevo_simulacro(
    datos: CrearSimulacroRequest,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> SimulacroCreado:
    try:
        _exigir_suscripcion_activa(usuario.id)
        sid = crear_simulacro(
            datos.convocatoria_id,
            datos.origenes,
            datos.fuentes,
            usuario.id,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SimulacroCreado(id=sid)


@app.get("/api/v1/simulacros/{simulacro_id}", response_model=Simulacro)
def ver_simulacro(
    simulacro_id: int,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> Simulacro:
    fila, _estado = _exigir_lectura_prueba(simulacro_id, usuario.id)
    return Simulacro(**fila)


@app.get(
    "/api/v1/simulacros/{simulacro_id}/preguntas",
    response_model=list[PreguntaSimulacro],
)
def preguntas_simulacro(
    simulacro_id: int,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> list[PreguntaSimulacro]:
    _exigir_lectura_prueba(simulacro_id, usuario.id)
    return [
        PreguntaSimulacro(**x)
        for x in obtener_preguntas_para_realizar(simulacro_id, usuario.id)
    ]


@app.put(
    "/api/v1/simulacros/{simulacro_id}/respuestas",
    status_code=204,
)
def guardar_respuestas_simulacro(
    simulacro_id: int,
    datos: GuardarRespuestasRequest,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> None:
    try:
        _exigir_escritura_prueba(simulacro_id, usuario.id)
        guardar_respuestas(
            simulacro_id,
            [x.model_dump() for x in datos.respuestas],
            usuario.id,
        )
    except ValueError as exc:
        mensaje = str(exc)
        codigo = 404 if "no existe" in mensaje.lower() else 400
        raise HTTPException(status_code=codigo, detail=mensaje) from exc


@app.get("/api/v1/simulacros/{simulacro_id}/tiempo-correccion")
def tiempo_correccion_api(
    simulacro_id: int,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> dict[str, int]:
    try:
        _exigir_lectura_prueba(simulacro_id, usuario.id)
        return {
            "tiempo_correccion_segundos": obtener_tiempo_correccion(
                simulacro_id,
                usuario.id,
            )
        }
    except ValueError as exc:
        mensaje = str(exc)
        codigo = 404 if "no existe" in mensaje.lower() else 400
        raise HTTPException(status_code=codigo, detail=mensaje) from exc


@app.post(
    "/api/v1/simulacros/{simulacro_id}/finalizar",
    response_model=ResultadoSimulacro,
)
def finalizar_simulacro_api(
    simulacro_id: int,
    segundos_adicionales: int = Query(default=0, ge=0),
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> ResultadoSimulacro:
    try:
        _exigir_escritura_prueba(simulacro_id, usuario.id)
        return ResultadoSimulacro(
            **finalizar_simulacro(
                simulacro_id,
                usuario.id,
                segundos_adicionales=segundos_adicionales,
            )
        )
    except ValueError as exc:
        mensaje = str(exc)
        codigo = 404 if "no existe" in mensaje.lower() else 400
        raise HTTPException(status_code=codigo, detail=mensaje) from exc



@app.get(
    "/api/v1/simulacros/{simulacro_id}/resultado",
    response_model=ResultadoSimulacro,
)
def resultado_simulacro_guardado_api(
    simulacro_id: int,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> ResultadoSimulacro:
    try:
        _exigir_lectura_prueba(simulacro_id, usuario.id)
        return ResultadoSimulacro(
            **obtener_resultado_guardado(simulacro_id, usuario.id)
        )
    except ValueError as exc:
        mensaje = str(exc)
        codigo = 404 if "no existe" in mensaje.lower() else 400
        raise HTTPException(status_code=codigo, detail=mensaje) from exc




@app.get("/api/v1/simulacros/{simulacro_id}/acumulado")
def resultado_acumulado_api(
    simulacro_id: int,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> dict:
    try:
        prueba, estado = _exigir_lectura_prueba(simulacro_id, usuario.id)
        solo_gratuita = bool(
            prueba.get("es_prueba_gratuita")
            and not estado["suscrito"]
            and not estado.get("acceso_historico_activo", False)
        )
        return obtener_resultado_acumulado(
            simulacro_id,
            usuario.id,
            solo_prueba_gratuita=solo_gratuita,
        )
    except ValueError as exc:
        mensaje = str(exc)
        codigo = 404 if "no existe" in mensaje.lower() else 400
        raise HTTPException(status_code=codigo, detail=mensaje) from exc






@app.get("/api/v1/simulacros/{simulacro_id}/pdf-soluciones")
def pdf_soluciones_api(
    simulacro_id: int,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> dict:
    """
    Genera el PDF de soluciones desde el snapshot guardado.
    Está disponible tanto para pruebas abiertas como finalizadas.
    """
    try:
        _exigir_lectura_prueba(simulacro_id, usuario.id)
        nombre, contenido = generar_pdf_soluciones(
            simulacro_id=simulacro_id,
            user_id=usuario.id,
        )
        return {
            "filename": nombre,
            "content_base64": base64.b64encode(contenido).decode("ascii"),
        }
    except ValueError as exc:
        mensaje = str(exc)
        codigo = 404 if "no existe" in mensaje.lower() else 400
        raise HTTPException(status_code=codigo, detail=mensaje) from exc


@app.get("/api/v1/simulacros/{simulacro_id}/pdf-preguntas")
def pdf_preguntas_api(
    simulacro_id: int,
    incluir_seguridad: bool = True,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> dict:
    """
    Genera bajo petición el PDF de preguntas a partir del snapshot guardado.
    El PDF no se persiste en el servidor.
    """
    try:
        _exigir_lectura_prueba(simulacro_id, usuario.id)
        nombre, contenido = generar_pdf_preguntas(
            simulacro_id=simulacro_id,
            user_id=usuario.id,
            incluir_seguridad=incluir_seguridad,
        )
        return {
            "filename": nombre,
            "content_base64": base64.b64encode(contenido).decode("ascii"),
        }
    except ValueError as exc:
        mensaje = str(exc)
        codigo = 404 if "no existe" in mensaje.lower() else 400
        raise HTTPException(status_code=codigo, detail=mensaje) from exc


@app.post("/api/v1/simulacros/{simulacro_id}/analisis-rendimiento")
def analisis_rendimiento_api(
    simulacro_id: int,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> dict:
    """
    Genera bajo petición un análisis IA del rendimiento de la prueba abierta
    y del acumulado del mismo tipo en su convocatoria.
    """
    try:
        prueba, estado = _exigir_escritura_prueba(simulacro_id, usuario.id)
        resultado_actual = obtener_resultado_para_analisis(
            simulacro_id,
            usuario.id,
        )
        resultado_acumulado = obtener_resultado_acumulado(
            simulacro_id,
            usuario.id,
            solo_prueba_gratuita=bool(
                prueba.get("es_prueba_gratuita")
                and not estado["suscrito"]
            ),
        )
        texto = generar_analisis_rendimiento(
            resultado_actual=resultado_actual,
            resultado_acumulado=resultado_acumulado,
        )
        return {
            "firma_datos": resultado_acumulado["firma_datos"],
            "texto": texto,
        }
    except ValueError as exc:
        mensaje = str(exc)
        codigo = 404 if "no existe" in mensaje.lower() else 400
        raise HTTPException(status_code=codigo, detail=mensaje) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.delete("/api/v1/simulacros/{simulacro_id}", status_code=204)
def eliminar_simulacro_api(
    simulacro_id: int,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> None:
    _exigir_escritura_prueba(simulacro_id, usuario.id)
    if not eliminar_simulacro(simulacro_id, usuario.id):
        raise HTTPException(status_code=404, detail="Simulacro no encontrado")


@app.get(
    "/api/v1/simulacros/{simulacro_id}/correccion",
    response_model=list[PreguntaCorregida],
)
def correccion_simulacro(
    simulacro_id: int,
    usuario: UsuarioAutenticado = Depends(usuario_actual),
) -> list[PreguntaCorregida]:
    try:
        _exigir_lectura_prueba(simulacro_id, usuario.id)
        return [
            PreguntaCorregida(**x)
            for x in obtener_correccion(simulacro_id, usuario.id)
        ]
    except ValueError as exc:
        mensaje = str(exc)
        codigo = 404 if "no existe" in mensaje.lower() else 400
        raise HTTPException(status_code=codigo, detail=mensaje) from exc
