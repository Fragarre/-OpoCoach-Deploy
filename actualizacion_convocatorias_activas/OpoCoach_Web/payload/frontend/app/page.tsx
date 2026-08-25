"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import type { Session } from "@supabase/supabase-js";

import { apiFetch } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";

type EstadoSuscripcion = {
  suscrito: boolean;
  status: string;
  customer_id: string | null;
  subscription_id: string | null;
  plan: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  cancel_at: string | null;
  cancelacion_programada: boolean;
  ended_at: string | null;
  prueba_gratuita_disponible: boolean;
  prueba_gratuita_consumida_at: string | null;
  historico_post_baja_dias: number;
  acceso_historico_hasta: string | null;
  acceso_historico_activo: boolean;
  pago_pendiente: boolean;
};

type Me = {
  id: string;
  email: string;
};

type Convocatoria = {
  id: number;
  puesto: string;
  numero: string;
  anio: number;
  codigo: string;
};

type Pregunta = {
  simulacro_pregunta_id: number;
  orden: number;
  parte_nombre: string | null;
  respuesta_usuario: string | null;
  seguridad_usuario: string | null;
  enunciado: string;
  opcion_a: string;
  opcion_b: string;
  opcion_c: string;
  opcion_d: string;
};

type PreguntaCorregida = Pregunta & {
  respuesta_correcta: string;
  resultado: "ACIERTO" | "FALLO" | "NO_CONTESTADA";
};

type Resultado = {
  simulacro_id: number;
  total: number;
  contestadas: number;
  aciertos: number;
  fallos: number;
  no_contestadas: number;
  puntos: number;
  nota: number;
  tiempo_correccion_segundos: number;
};

type AcumuladoTema = {
  tema_id: number | null;
  parte: string;
  numero_tema: number;
  titulo: string;
  preguntas: number;
  contestadas: number;
  no_contestadas: number;
  aciertos: number;
  fallos: number;
  fallos_seguro: number;
  porcentaje_convocatoria: number;
  porcentaje_aciertos: number;
  porcentaje_fallos: number;
  porcentaje_no_contestadas: number;
  porcentaje_aciertos_contestadas: number;
};

type AcumuladoNorma = {
  norma: string;
  preguntas: number;
  contestadas: number;
  no_contestadas: number;
  aciertos: number;
  fallos: number;
  fallos_seguro: number;
  porcentaje_convocatoria: number;
  porcentaje_aciertos: number;
  porcentaje_fallos: number;
  porcentaje_no_contestadas: number;
  porcentaje_aciertos_contestadas: number;
};

type AcumuladoSeguridad = {
  codigo: "SEGURO" | "MENOS_SEGURO";
  seguridad: string;
  contestadas: number;
  aciertos: number;
  fallos: number;
  porcentaje_aciertos: number;
  porcentaje_fallos: number;
};

type ResultadoAcumulado = {
  convocatoria_id: number;
  tipo_prueba: "SIMULACRO" | "TEST";
  simulacros: number;
  simulacros_ids: number[];
  preguntas: number;
  contestadas: number;
  no_contestadas: number;
  aciertos: number;
  fallos: number;
  temas: AcumuladoTema[];
  normas: AcumuladoNorma[];
  seguridad: AcumuladoSeguridad[];
  firma_datos: string;
};

type PdfGenerado = {
  filename: string;
  content_base64: string;
};

type AnalisisRendimiento = {
  firma_datos: string;
  texto: string;
};

type SimulacroListado = {
  id: number;
  convocatoria_id: number;
  numero: number;
  fecha_generacion: string;
  total_preguntas: number;
  estado: "GENERADO" | "FINALIZADO";
  tipo_prueba: "SIMULACRO" | "TEST";
  es_prueba_gratuita: boolean;
  convocatoria_codigo: string | null;
  contestadas: number;
};

type TemaTest = {
  id: number;
  parte: string;
  numero_tema: number;
  titulo: string;
  tipo_contenido: string | null;
  disponibles: number;
};

type NormaTest = {
  norma_clave: string;
  norma_nombre: string;
  disponibles: number;
};

type TestCreado = {
  id: number;
  numero: number;
  total_solicitado: number;
  total_generado: number;
  avisos: string[];
};

type RespuestaLocal = {
  respuesta: string | null;
  seguridad: string | null;
};

type ChatModo = "CONVOCATORIA" | "GENERAL";

type ChatMensaje = {
  role: "user" | "assistant";
  content: string;
};

type ChatFuente = {
  tipo: string;
  tema?: string;
  titulo_tema?: string;
  norma?: string;
  articulo?: string;
  articulo_boe?: string;
  clave?: string;
  titulo?: string;
};

type ChatRespuesta = {
  respuesta: string;
  fuentes: ChatFuente[];
  modelo: string | null;
  modo: ChatModo;
};

const ORIGENES = ["A1", "A2", "C1", "C2"] as const;
const FUENTES = ["REAL", "IA"] as const;

const SEGURIDADES = [
  ["SEGURO", "Seguro"],
  ["MENOS_SEGURO", "Menos seguro"],
] as const;

function formatearFechaSuscripcion(valor: string | null): string | null {
  if (!valor) return null;

  const fecha = new Date(valor);
  if (Number.isNaN(fecha.getTime())) return null;

  return new Intl.DateTimeFormat("es-ES", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(fecha);
}


function formatearTiempo(segundos: number): string {
  const total = Math.max(0, Math.floor(segundos));
  const horas = Math.floor(total / 3600);
  const minutos = Math.floor((total % 3600) / 60);
  const segundosRestantes = total % 60;

  if (horas > 0) {
    return `${horas} h ${String(minutos).padStart(2, "0")} min ${String(
      segundosRestantes
    ).padStart(2, "0")} s`;
  }

  return `${minutos} min ${String(segundosRestantes).padStart(2, "0")} s`;
}

function CronometroCorreccion({
  inicioMs,
  tiempoPrevio,
}: {
  inicioMs: number;
  tiempoPrevio: number;
}) {
  const [ahora, setAhora] = useState(Date.now());

  useEffect(() => {
    const intervalo = window.setInterval(() => setAhora(Date.now()), 1000);
    return () => window.clearInterval(intervalo);
  }, []);

  const sesion = Math.max(0, Math.floor((ahora - inicioMs) / 1000));
  return (
    <div style={{ fontWeight: 600, marginBottom: 14 }}>
      Tiempo transcurrido: {formatearTiempo(tiempoPrevio + sesion)}
    </div>
  );
}

export default function Home() {
  const supabase = useMemo(() => createClient(), []);
  const [session, setSession] = useState<Session | null>(null);
  const [cargandoSesion, setCargandoSesion] = useState(true);
  const [pantallaPublica, setPantallaPublica] = useState<"LANDING" | "LOGIN" | "REGISTRO">("LANDING");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [me, setMe] = useState<Me | null>(null);
  const [convocatorias, setConvocatorias] = useState<Convocatoria[]>([]);
  const [misSimulacros, setMisSimulacros] = useState<SimulacroListado[]>([]);
  const [misTests, setMisTests] = useState<SimulacroListado[]>([]);
  const [seccion, setSeccion] = useState<"INICIO" | "SIMULACROS" | "TESTS" | "CHAT">("INICIO");
  const [tipoActivo, setTipoActivo] = useState<"SIMULACRO" | "TEST" | null>(null);
  const [convocatoriaSimulacroId, setConvocatoriaSimulacroId] = useState<number | null>(null);
  const [convocatoriaTestId, setConvocatoriaTestId] = useState<number | null>(null);
  const [modoTest, setModoTest] = useState<"TEMA" | "NORMA">("TEMA");
  const [numeroPreguntasTest, setNumeroPreguntasTest] = useState(20);
  const [temasTest, setTemasTest] = useState<TemaTest[]>([]);
  const [normasTest, setNormasTest] = useState<NormaTest[]>([]);
  const [temasSeleccionados, setTemasSeleccionados] = useState<number[]>([]);
  const [normasSeleccionadas, setNormasSeleccionadas] = useState<string[]>([]);
  const [simulacroId, setSimulacroId] = useState<number | null>(null);
  const [pruebaActivaEsGratuita, setPruebaActivaEsGratuita] = useState(false);
  const [preguntas, setPreguntas] = useState<Pregunta[]>([]);
  const [respuestas, setRespuestas] = useState<Record<number, RespuestaLocal>>({});
  const [evaluarSeguridad, setEvaluarSeguridad] = useState(false);
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const [mostrarCronometro, setMostrarCronometro] = useState(false);
  const [tiempoPrevioCorreccion, setTiempoPrevioCorreccion] = useState(0);
  const [inicioCorreccionMs, setInicioCorreccionMs] = useState<number | null>(null);
  const [correccion, setCorreccion] = useState<PreguntaCorregida[]>([]);
  const [vistaPrueba, setVistaPrueba] = useState<"RESUMEN" | "PREGUNTAS">("RESUMEN");
  const [mostrarCorreccionPantalla, setMostrarCorreccionPantalla] = useState(false);
  const [resultadoAcumulado, setResultadoAcumulado] = useState<ResultadoAcumulado | null>(null);
  const [analisisRendimiento, setAnalisisRendimiento] = useState<
    Record<string, AnalisisRendimiento>
  >({});
  const [mensaje, setMensaje] = useState("");

  useEffect(() => {
    if (!mensaje) return;

    const temporizador = window.setTimeout(() => {
      setMensaje("");
    }, 3000);

    return () => window.clearTimeout(temporizador);
  }, [mensaje]);
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [accionEnCurso, setAccionEnCurso] = useState<string | null>(null);
  const [checkoutRetorno, setCheckoutRetorno] = useState<"success" | "cancel" | null>(null);
  const [estadoSuscripcion, setEstadoSuscripcion] = useState<EstadoSuscripcion | null>(null);
  const [chatConvocatoriaId, setChatConvocatoriaId] = useState<number | null>(null);
  const [chatModo, setChatModo] = useState<ChatModo>("CONVOCATORIA");
  const [chatEntrada, setChatEntrada] = useState("");
  const [chatHistoriales, setChatHistoriales] = useState<
    Record<string, ChatMensaje[]>
  >({});

  const modoHistoricoPostBaja = Boolean(
    estadoSuscripcion &&
      !estadoSuscripcion.suscrito &&
      estadoSuscripcion.acceso_historico_activo
  );

  const modoSoloLecturaActivo = Boolean(
    modoHistoricoPostBaja && !pruebaActivaEsGratuita
  );

  function itemSoloLectura(item: SimulacroListado): boolean {
    return Boolean(modoHistoricoPostBaja && !item.es_prueba_gratuita);
  }

  const actividadReciente = useMemo(
    () =>
      [...misSimulacros, ...misTests]
        .sort(
          (a, b) =>
            new Date(b.fecha_generacion).getTime() -
            new Date(a.fecha_generacion).getTime()
        )
        .slice(0, 4),
    [misSimulacros, misTests]
  );

  const totalPruebas = misSimulacros.length + misTests.length;
  const totalPendientes = [...misSimulacros, ...misTests].filter(
    (item) => item.estado !== "FINALIZADO"
  ).length;
  const totalCorregidas = totalPruebas - totalPendientes;

  const inicialUsuario = (me?.email?.trim()?.[0] ?? "O").toUpperCase();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const estado = params.get("checkout");

    if (estado === "success" || estado === "cancel") {
      setCheckoutRetorno(estado);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setCargandoSesion(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      if (!nextSession) {
        setMe(null);
        setConvocatorias([]);
        setMisSimulacros([]);
        setMisTests([]);
        setAnalisisRendimiento({});
        setChatHistoriales({});
        setChatEntrada("");
        limpiarSimulacro();
      }
    });

    return () => subscription.unsubscribe();
  }, [supabase]);

  useEffect(() => {
    if (!session) return;

    Promise.all([
      apiFetch<Me>("api/v1/me"),
      apiFetch<Convocatoria[]>("api/v1/convocatorias"),
      apiFetch<SimulacroListado[]>("api/v1/simulacros"),
      apiFetch<SimulacroListado[]>("api/v1/tests"),
      apiFetch<EstadoSuscripcion>("api/v1/billing/subscription"),
    ])
      .then(([usuario, lista, guardados, tests, suscripcion]) => {
        setMe(usuario);
        setConvocatorias(lista);
        setMisSimulacros(guardados);
        setMisTests(tests);
        setEstadoSuscripcion(suscripcion);

        // El backend entrega únicamente convocatorias activas. Si una
        // convocatoria fue dada de baja mientras estaba seleccionada en esta
        // sesión, sustituimos ese ID por una opción activa sin afectar a los
        // históricos ya guardados.
        const idsActivos = new Set(lista.map((item) => item.id));
        const convocatoriaPorDefecto = lista.length > 0 ? lista[0].id : null;
        setConvocatoriaSimulacroId((actual) =>
          actual !== null && idsActivos.has(actual) ? actual : convocatoriaPorDefecto
        );
        setConvocatoriaTestId((actual) =>
          actual !== null && idsActivos.has(actual) ? actual : convocatoriaPorDefecto
        );
        setChatConvocatoriaId((actual) =>
          actual !== null && idsActivos.has(actual) ? actual : convocatoriaPorDefecto
        );
        setError("");
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
      });
  }, [session]);

  useEffect(() => {
    if (!session || convocatoriaTestId === null) return;

    const query = FUENTES
      .map((f) => `fuente=${encodeURIComponent(f)}`)
      .join("&");

    if (!query) {
      setTemasTest([]);
      setNormasTest([]);
      return;
    }

    Promise.all([
      apiFetch<TemaTest[]>(
        `api/v1/convocatorias/${convocatoriaTestId}/tests/temas?${query}`
      ),
      apiFetch<NormaTest[]>(
        `api/v1/convocatorias/${convocatoriaTestId}/tests/normas?${query}`
      ),
    ])
      .then(([temas, normas]) => {
        setTemasTest(temas);
        setNormasTest(normas);
        setTemasSeleccionados((actual) =>
          actual.filter((id) => temas.some((t) => t.id === id))
        );
        setNormasSeleccionadas((actual) =>
          actual.filter((clave) =>
            normas.some((n) => n.norma_clave === clave)
          )
        );
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
      });
  }, [session, convocatoriaTestId]);

  function limpiarSimulacro() {
    setPreguntas([]);
    setRespuestas({});
    setEvaluarSeguridad(false);
    setResultado(null);
    setCorreccion([]);
    setResultadoAcumulado(null);
    setSimulacroId(null);
    setTipoActivo(null);
    setPruebaActivaEsGratuita(false);
    setMostrarCronometro(false);
    setTiempoPrevioCorreccion(0);
    setInicioCorreccionMs(null);
    setVistaPrueba("RESUMEN");
    setMostrarCorreccionPantalla(false);
  }


  function iniciarTiempoCorreccion(tiempoPrevio = 0) {
    setTiempoPrevioCorreccion(Math.max(0, Math.floor(tiempoPrevio)));
    setInicioCorreccionMs(Date.now());
    setMostrarCronometro(false);
  }


  async function recargarSimulacros() {
    const guardados = await apiFetch<SimulacroListado[]>("api/v1/simulacros");
    setMisSimulacros(guardados);
  }

  async function recargarTests() {
    const guardados = await apiFetch<SimulacroListado[]>("api/v1/tests");
    setMisTests(guardados);
  }

  async function recargarListaActiva() {
    if (tipoActivo === "TEST") {
      await recargarTests();
    } else {
      await recargarSimulacros();
    }
  }

  function inicializarRespuestas(lista: Pregunta[]) {
    const iniciales: Record<number, RespuestaLocal> = {};
    lista.forEach((p) => {
      iniciales[p.simulacro_pregunta_id] = {
        respuesta: p.respuesta_usuario,
        seguridad: p.seguridad_usuario,
      };
    });
    setRespuestas(iniciales);
    setEvaluarSeguridad(
      lista.some((p) => p.seguridad_usuario !== null)
    );
  }

  async function abrirSimulacro(simulacro: SimulacroListado) {
    setOcupado(true);
    setAccionEnCurso(
      simulacro.estado === "FINALIZADO"
        ? "Abriendo corrección..."
        : "Recuperando simulacro..."
    );
    setError("");
    setMensaje("");
    limpiarSimulacro();
    setTipoActivo(simulacro.tipo_prueba);
    setPruebaActivaEsGratuita(Boolean(simulacro.es_prueba_gratuita));

    try {
      if (simulacro.estado === "FINALIZADO") {
        const [res, corr, acumulado] = await Promise.all([
          apiFetch<Resultado>(
            `api/v1/simulacros/${simulacro.id}/resultado`
          ),
          apiFetch<PreguntaCorregida[]>(
            `api/v1/simulacros/${simulacro.id}/correccion`
          ),
          apiFetch<ResultadoAcumulado>(
            `api/v1/simulacros/${simulacro.id}/acumulado`
          ),
        ]);
        setSimulacroId(simulacro.id);
        setResultado(res);
        setTiempoPrevioCorreccion(res.tiempo_correccion_segundos);
        setInicioCorreccionMs(null);
        setMostrarCronometro(false);
        setCorreccion(corr);
        setResultadoAcumulado(acumulado);
        setMostrarCorreccionPantalla(false);
      } else {
        const [lista, tiempo] = await Promise.all([
          apiFetch<Pregunta[]>(
            `api/v1/simulacros/${simulacro.id}/preguntas`
          ),
          apiFetch<{ tiempo_correccion_segundos: number }>(
            `api/v1/simulacros/${simulacro.id}/tiempo-correccion`
          ),
        ]);
        setSimulacroId(simulacro.id);
        setPreguntas(lista);
        inicializarRespuestas(lista);
        if (itemSoloLectura(simulacro)) {
          setTiempoPrevioCorreccion(tiempo.tiempo_correccion_segundos);
          setInicioCorreccionMs(null);
          setMostrarCronometro(false);
        } else {
          iniciarTiempoCorreccion(tiempo.tiempo_correccion_segundos);
        }
        setVistaPrueba("RESUMEN");
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOcupado(false);
      setAccionEnCurso(null);
    }
  }

  function salirDePrueba(destino: "INICIO" | "LISTA") {
    const tipo = tipoActivo;
    limpiarSimulacro();
    setMensaje("");
    setError("");

    if (destino === "INICIO") {
      setSeccion("INICIO");
    } else {
      setSeccion(tipo === "TEST" ? "TESTS" : "SIMULACROS");
    }

    window.scrollTo({ top: 0, behavior: "smooth" });
  }


  async function modificarRespuestas() {
    if (simulacroId === null) return;
    if (modoSoloLecturaActivo) {
      setError(
        "Tras la baja, el histórico está disponible únicamente en modo lectura y para descarga de PDFs."
      );
      return;
    }

    setOcupado(true);
    setAccionEnCurso("Preparando modificación de respuestas...");
    setError("");
    setMensaje("");

    try {
      const [lista, tiempo] = await Promise.all([
        apiFetch<Pregunta[]>(
          `api/v1/simulacros/${simulacroId}/preguntas`
        ),
        apiFetch<{ tiempo_correccion_segundos: number }>(
          `api/v1/simulacros/${simulacroId}/tiempo-correccion`
        ),
      ]);

      setPreguntas(lista);
      inicializarRespuestas(lista);
      setResultado(null);
      setCorreccion([]);
      setResultadoAcumulado(null);
      iniciarTiempoCorreccion(tiempo.tiempo_correccion_segundos);
      setVistaPrueba("PREGUNTAS");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOcupado(false);
      setAccionEnCurso(null);
    }
  }

  async function eliminarGuardado(simulacro: SimulacroListado) {
    const nombre = simulacro.tipo_prueba === "TEST" ? "test" : "simulacro";
    const confirmar = window.confirm(
      `¿Eliminar definitivamente el ${nombre} nº ${simulacro.numero}?`
    );
    if (!confirmar) return;

    setOcupado(true);
    setAccionEnCurso(`Eliminando simulacro ${simulacro.numero}...`);
    setError("");
    setMensaje("");

    try {
      await apiFetch<void>(`api/v1/simulacros/${simulacro.id}`, {
        method: "DELETE",
      });
      if (simulacro.tipo_prueba === "TEST") {
        await recargarTests();
      } else {
        await recargarSimulacros();
      }
      setMensaje(
        `${simulacro.tipo_prueba === "TEST" ? "Test" : "Simulacro"} nº ${simulacro.numero} eliminado.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOcupado(false);
      setAccionEnCurso(null);
    }
  }

  function claveAnalisisActual(): string | null {
    if (!resultadoAcumulado) return null;
    return `${resultadoAcumulado.tipo_prueba}:${resultadoAcumulado.convocatoria_id}`;
  }

  function analisisActual(): AnalisisRendimiento | null {
    const clave = claveAnalisisActual();
    if (!clave || !resultadoAcumulado) return null;

    const cache = analisisRendimiento[clave];
    if (!cache) return null;

    return cache.firma_datos === resultadoAcumulado.firma_datos
      ? cache
      : null;
  }

  async function descargarPdfSoluciones() {
    if (simulacroId === null) return;

    setOcupado(true);
    setAccionEnCurso("Generando PDF de soluciones...");
    setError("");
    setMensaje("");

    try {
      const pdf = await apiFetch<PdfGenerado>(
        `api/v1/simulacros/${simulacroId}/pdf-soluciones`
      );

      const binario = atob(pdf.content_base64);
      const bytes = new Uint8Array(binario.length);

      for (let i = 0; i < binario.length; i += 1) {
        bytes[i] = binario.charCodeAt(i);
      }

      const blob = new Blob([bytes], { type: "application/pdf" });
      const url = URL.createObjectURL(blob);
      const enlace = document.createElement("a");

      enlace.href = url;
      enlace.download = pdf.filename;
      document.body.appendChild(enlace);
      enlace.click();
      enlace.remove();

      URL.revokeObjectURL(url);
      setMensaje("PDF de soluciones generado.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOcupado(false);
      setAccionEnCurso(null);
    }
  }


  async function descargarPdfPreguntas() {
    if (simulacroId === null) return;

    setOcupado(true);
    setAccionEnCurso("Generando PDF de preguntas...");
    setError("");
    setMensaje("");

    try {
      const pdf = await apiFetch<PdfGenerado>(
        `api/v1/simulacros/${simulacroId}/pdf-preguntas?incluir_seguridad=true`
      );

      const binario = atob(pdf.content_base64);
      const bytes = new Uint8Array(binario.length);

      for (let i = 0; i < binario.length; i += 1) {
        bytes[i] = binario.charCodeAt(i);
      }

      const blob = new Blob([bytes], { type: "application/pdf" });
      const url = URL.createObjectURL(blob);
      const enlace = document.createElement("a");

      enlace.href = url;
      enlace.download = pdf.filename;
      document.body.appendChild(enlace);
      enlace.click();
      enlace.remove();

      URL.revokeObjectURL(url);
      setMensaje("PDF de preguntas generado.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOcupado(false);
      setAccionEnCurso(null);
    }
  }


  async function generarAnalisisRendimiento() {
    if (simulacroId === null || !resultadoAcumulado) return;

    setOcupado(true);
    setAccionEnCurso("Analizando los resultados acumulados...");
    setError("");
    setMensaje("");

    try {
      const analisis = await apiFetch<AnalisisRendimiento>(
        `api/v1/simulacros/${simulacroId}/analisis-rendimiento`,
        { method: "POST" }
      );

      const clave = `${resultadoAcumulado.tipo_prueba}:${resultadoAcumulado.convocatoria_id}`;
      setAnalisisRendimiento((actual) => ({
        ...actual,
        [clave]: analisis,
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOcupado(false);
      setAccionEnCurso(null);
    }
  }

  function renderInlineMarkdown(texto: string) {
    const partes = texto.split(/(\*\*[^*]+\*\*)/g);

    return partes.map((parte, indice) => {
      if (parte.startsWith("**") && parte.endsWith("**")) {
        return <strong key={indice}>{parte.slice(2, -2)}</strong>;
      }

      return <span key={indice}>{parte}</span>;
    });
  }

  function renderAnalisisRendimiento(texto: string) {
    return texto.split("\n").map((linea, indice) => {
      const textoLinea = linea.trim();

      if (!textoLinea) {
        return <div key={indice} style={{ height: 8 }} />;
      }

      if (textoLinea.startsWith("### ")) {
        return (
          <h3 key={indice} style={{ marginTop: 22, marginBottom: 10 }}>
            {renderInlineMarkdown(textoLinea.slice(4))}
          </h3>
        );
      }

      const numero = textoLinea.match(/^(\d+)\.\s+(.*)$/);
      if (numero) {
        return (
          <p key={indice} style={{ margin: "8px 0 8px 18px" }}>
            <strong>{numero[1]}.</strong>{" "}
            {renderInlineMarkdown(numero[2])}
          </p>
        );
      }

      if (textoLinea.startsWith("- ")) {
        return (
          <p key={indice} style={{ margin: "6px 0 6px 22px" }}>
            • {renderInlineMarkdown(textoLinea.slice(2))}
          </p>
        );
      }

      return (
        <p key={indice} style={{ margin: "8px 0", lineHeight: 1.55 }}>
          {renderInlineMarkdown(textoLinea)}
        </p>
      );
    });
  }


  function claveChat(
    convocatoriaId: number | null = chatConvocatoriaId,
    modo: ChatModo = chatModo
  ): string | null {
    if (convocatoriaId === null) return null;
    return `${convocatoriaId}:${modo}`;
  }

  function mensajesChatActuales(): ChatMensaje[] {
    const clave = claveChat();
    return clave ? chatHistoriales[clave] ?? [] : [];
  }

  function limpiarChatActual() {
    const clave = claveChat();
    if (!clave) return;

    setChatHistoriales((actual) => ({
      ...actual,
      [clave]: [],
    }));
    setChatEntrada("");
    setError("");
    setMensaje("");
    setOcupado(false);
    setAccionEnCurso(null);
  }

  async function enviarChat(event: FormEvent) {
    event.preventDefault();

    if (chatConvocatoriaId === null) {
      setError("Selecciona una convocatoria para el chat.");
      return;
    }

    const pregunta = chatEntrada.trim().replace(/\s+/g, " ");
    if (!pregunta) return;

    const clave = claveChat();
    if (!clave) return;

    const previos = chatHistoriales[clave] ?? [];
    const mensajeUsuario: ChatMensaje = {
      role: "user",
      content: pregunta,
    };

    setChatHistoriales((actual) => ({
      ...actual,
      [clave]: [...(actual[clave] ?? []), mensajeUsuario],
    }));
    setChatEntrada("");
    setOcupado(true);
    setAccionEnCurso(
      chatModo === "CONVOCATORIA"
        ? "Consultando las fuentes disponibles..."
        : "Generando una respuesta de conocimiento general..."
    );
    setError("");
    setMensaje("");

    try {
      const resultadoChat = await apiFetch<ChatRespuesta>("api/v1/chat", {
        method: "POST",
        body: JSON.stringify({
          convocatoria_id: chatConvocatoriaId,
          pregunta,
          mensajes_previos: previos,
          modo: chatModo,
        }),
      });

      const mensajeAsistente: ChatMensaje = {
        role: "assistant",
        content: resultadoChat.respuesta,
      };

      setChatHistoriales((actual) => ({
        ...actual,
        [clave]: [...(actual[clave] ?? []), mensajeAsistente],
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOcupado(false);
      setAccionEnCurso(null);
    }
  }

  async function actualizarSuscripcion() {
    try {
      const estado = await apiFetch<EstadoSuscripcion>(
        "api/v1/billing/subscription"
      );
      setEstadoSuscripcion(estado);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function abrirCheckout() {
    setError("");
    setMensaje("");
    setOcupado(true);
    setAccionEnCurso("Abriendo pago seguro de Stripe...");

    try {
      const checkout = await apiFetch<{ id: string; url: string }>(
        "api/v1/billing/checkout",
        { method: "POST" }
      );
      window.location.assign(checkout.url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setOcupado(false);
      setAccionEnCurso(null);
    }
  }

  async function abrirPortalSuscripcion() {
    setError("");
    setMensaje("");
    setOcupado(true);
    setAccionEnCurso("Abriendo gestión de suscripción...");

    try {
      const portal = await apiFetch<{ url: string }>(
        "api/v1/billing/portal",
        { method: "POST" }
      );
      window.location.assign(portal.url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setOcupado(false);
      setAccionEnCurso(null);
    }
  }

  async function iniciarSesion(event: FormEvent) {
    event.preventDefault();
    setError("");
    setMensaje("");
    setOcupado(true);
    setAccionEnCurso("Iniciando sesión...");

    const { error: authError } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });

    setOcupado(false);
    setAccionEnCurso(null);

    if (authError) {
      setError(authError.message);
      return;
    }

    setPassword("");
  }

  async function crearCuenta(event: FormEvent) {
    event.preventDefault();
    setError("");
    setMensaje("");
    setOcupado(true);
    setAccionEnCurso("Creando cuenta...");

    const { data, error: authError } = await supabase.auth.signUp({
      email: email.trim(),
      password,
    });

    setOcupado(false);
    setAccionEnCurso(null);

    if (authError) {
      setError(authError.message);
      return;
    }

    setPassword("");

    if (!data.session) {
      setMensaje(
        "Cuenta creada. Revisa tu correo electrónico si Supabase requiere confirmar la dirección antes de entrar."
      );
      setPantallaPublica("LOGIN");
    }
  }

  async function cerrarSesion() {
    await supabase.auth.signOut();
  }

  function toggle(
    valor: string,
    seleccion: string[],
    setter: (x: string[]) => void
  ) {
    setter(
      seleccion.includes(valor)
        ? seleccion.filter((x) => x !== valor)
        : [...seleccion, valor]
    );
  }

  function establecerRespuesta(id: number, respuesta: string | null) {
    setRespuestas((actual) => {
      const previo = actual[id] ?? { respuesta: null, seguridad: null };
      return {
        ...actual,
        [id]: {
          respuesta,
          seguridad: respuesta === null ? null : previo.seguridad,
        },
      };
    });
  }

  function establecerSeguridad(id: number, seguridad: string | null) {
    setRespuestas((actual) => {
      const previo = actual[id] ?? { respuesta: null, seguridad: null };
      return {
        ...actual,
        [id]: {
          ...previo,
          seguridad,
        },
      };
    });
  }

  function cambiarEvaluacionSeguridad(activada: boolean) {
    setEvaluarSeguridad(activada);
    if (!activada) {
      setRespuestas((actual) => {
        const siguientes: Record<number, RespuestaLocal> = {};
        for (const [id, respuesta] of Object.entries(actual)) {
          siguientes[Number(id)] = { ...respuesta, seguridad: null };
        }
        return siguientes;
      });
    }
  }

  async function crear(convocatoriaId: number) {
    setError("");
    setMensaje("");
    limpiarSimulacro();
    setOcupado(true);
    setAccionEnCurso("Creando simulacro...");

    try {
      const creado = await apiFetch<{ id: number }>("api/v1/simulacros", {
        method: "POST",
        body: JSON.stringify({
          convocatoria_id: convocatoriaId,
          origenes: [...ORIGENES],
          fuentes: [...FUENTES],
        }),
      });

      const lista = await apiFetch<Pregunta[]>(
        `api/v1/simulacros/${creado.id}/preguntas`
      );

      setTipoActivo("SIMULACRO");
      setPruebaActivaEsGratuita(false);
      setSimulacroId(creado.id);
      setPreguntas(lista);
      inicializarRespuestas(lista);
      iniciarTiempoCorreccion(0);
      setVistaPrueba("RESUMEN");
      await recargarSimulacros();
      setMensaje(
        `Simulacro ${creado.id} creado correctamente: ${lista.length} preguntas.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOcupado(false);
      setAccionEnCurso(null);
    }
  }

  async function crearTest() {
    if (convocatoriaTestId === null) {
      setError("Selecciona una convocatoria.");
      return;
    }
    if (numeroPreguntasTest <= 0) {
      setError("El número de preguntas debe ser mayor que cero.");
      return;
    }
    if (modoTest === "TEMA" && temasSeleccionados.length === 0) {
      setError("Selecciona al menos un punto del temario.");
      return;
    }
    if (modoTest === "NORMA" && normasSeleccionadas.length === 0) {
      setError("Selecciona al menos una ley o norma.");
      return;
    }

    setOcupado(true);
    setAccionEnCurso("Creando test...");
    setError("");
    setMensaje("");
    limpiarSimulacro();
    setTipoActivo("TEST");

    try {
      const creado = await apiFetch<TestCreado>("api/v1/tests", {
        method: "POST",
        body: JSON.stringify({
          convocatoria_id: convocatoriaTestId,
          numero_preguntas: numeroPreguntasTest,
          modo_seleccion: modoTest,
          temas_seleccionados: temasSeleccionados,
          normas_seleccionadas: normasSeleccionadas,
          fuentes: [...FUENTES],
        }),
      });

      const lista = await apiFetch<Pregunta[]>(
        `api/v1/simulacros/${creado.id}/preguntas`
      );

      setPruebaActivaEsGratuita(!estadoSuscripcion?.suscrito);
      setSimulacroId(creado.id);
      setPreguntas(lista);
      inicializarRespuestas(lista);
      iniciarTiempoCorreccion(0);
      setVistaPrueba("RESUMEN");
      await recargarTests();
      await actualizarSuscripcion();

      const aviso =
        creado.avisos.length > 0 ? ` ${creado.avisos.join(" ")}` : "";
      setMensaje(
        `Test nº ${creado.numero} creado con ${creado.total_generado} preguntas.${aviso}`
      );
    } catch (err) {
      limpiarSimulacro();
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOcupado(false);
      setAccionEnCurso(null);
    }
  }

  function payloadRespuestas() {
    return preguntas.map((p) => {
      const local = respuestas[p.simulacro_pregunta_id] ?? {
        respuesta: null,
        seguridad: null,
      };
      return {
        simulacro_pregunta_id: p.simulacro_pregunta_id,
        respuesta: local.respuesta,
        seguridad:
          evaluarSeguridad && local.respuesta ? local.seguridad : null,
      };
    });
  }

  function validarSeguridad(): string | null {
    if (!evaluarSeguridad) return null;

    const pendientes = preguntas
      .filter((p) => {
        const local = respuestas[p.simulacro_pregunta_id];
        return Boolean(local?.respuesta && !local.seguridad);
      })
      .map((p) => p.orden);

    if (pendientes.length === 0) return null;

    return `Falta indicar el nivel de seguridad en ${pendientes.length === 1 ? "la pregunta" : "las preguntas"}: ${pendientes.join(", ")}.`;
  }

  async function guardar() {
    if (simulacroId === null) return;

    const validacion = validarSeguridad();
    if (validacion) {
      setError(validacion);
      return;
    }

    setOcupado(true);
    setAccionEnCurso("Guardando respuestas...");
    setError("");
    setMensaje("");

    try {
      await apiFetch<void>(
        `api/v1/simulacros/${simulacroId}/respuestas`,
        {
          method: "PUT",
          body: JSON.stringify({ respuestas: payloadRespuestas() }),
        }
      );
      await recargarListaActiva();
      setMensaje("Respuestas guardadas correctamente.");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOcupado(false);
      setAccionEnCurso(null);
    }
  }

  async function calificar() {
    if (simulacroId === null) return;

    const validacion = validarSeguridad();
    if (validacion) {
      setError(validacion);
      return;
    }

    setOcupado(true);
    setAccionEnCurso("Guardando y calificando simulacro...");
    setError("");
    setMensaje("");

    try {
      await apiFetch<void>(
        `api/v1/simulacros/${simulacroId}/respuestas`,
        {
          method: "PUT",
          body: JSON.stringify({ respuestas: payloadRespuestas() }),
        }
      );

      const segundosSesion =
        inicioCorreccionMs === null
          ? 0
          : Math.max(0, Math.floor((Date.now() - inicioCorreccionMs) / 1000));

      const res = await apiFetch<Resultado>(
        `api/v1/simulacros/${simulacroId}/finalizar?segundos_adicionales=${segundosSesion}`,
        { method: "POST" }
      );

      const [corr, acumulado] = await Promise.all([
        apiFetch<PreguntaCorregida[]>(
          `api/v1/simulacros/${simulacroId}/correccion`
        ),
        apiFetch<ResultadoAcumulado>(
          `api/v1/simulacros/${simulacroId}/acumulado`
        ),
      ]);

      setResultado(res);
      setTiempoPrevioCorreccion(res.tiempo_correccion_segundos);
      setInicioCorreccionMs(null);
      setMostrarCronometro(false);
      setCorreccion(corr);
      setResultadoAcumulado(acumulado);
      await recargarListaActiva();
      setMensaje(`${tipoActivo === "TEST" ? "Test" : "Simulacro"} calificado correctamente.`);
      window.scrollTo({ top: 0, behavior: "smooth" });
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOcupado(false);
      setAccionEnCurso(null);
    }
  }

  if (cargandoSesion) {
    return <main className="page">Comprobando sesión...</main>;
  }

  if (!session) {
    if (pantallaPublica === "LANDING") {
      return (
        <main className="public-site">
          <header className="public-header">
            <button
              type="button"
              className="brand public-brand"
              onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
              aria-label="OpoCoach"
            >
              <span className="brand-mark">O</span>
              <span>OpoCoach</span>
            </button>

            <nav className="public-nav" aria-label="Navegación pública">
              <a href="#como-funciona">Cómo funciona</a>
              <a href="#simulacros">Simulacros</a>
              <a href="#tests">Tests</a>
              <a href="#precio">Precio</a>
            </nav>

            <div className="public-header-actions">
              <button
                type="button"
                className="secondary compact-button"
                onClick={() => {
                  setError("");
                  setMensaje("");
                  setPantallaPublica("LOGIN");
                }}
              >
                Iniciar sesión
              </button>
              <button
                type="button"
                className="primary compact-button"
                onClick={() => {
                  setError("");
                  setMensaje("");
                  setPantallaPublica("REGISTRO");
                }}
              >
                Probar gratis
              </button>
            </div>
          </header>

          <section className="public-hero">
            <div className="public-hero-copy">
              <span className="public-kicker">Preparación inteligente de oposiciones</span>
              <h1>Entrena como te examinan. Corrige como necesitas aprender.</h1>
              <p>
                OpoCoach combina simulacros, tests dirigidos y análisis de tus
                respuestas para que practiques con criterio y detectes dónde
                necesitas reforzar.
              </p>

              <div className="public-hero-actions">
                <button
                  type="button"
                  className="primary public-cta"
                  onClick={() => {
                    setError("");
                    setMensaje("");
                    setPantallaPublica("REGISTRO");
                  }}
                >
                  Hacer un test gratis
                </button>
                <button
                  type="button"
                  className="secondary public-cta"
                  onClick={() =>
                    document
                      .getElementById("como-funciona")
                      ?.scrollIntoView({ behavior: "smooth" })
                  }
                >
                  Ver cómo funciona
                </button>
              </div>

              <div className="public-trust-line">
                <span>1 test gratuito</span>
                <span>Hasta 10 preguntas</span>
                <span>Corrección y PDFs incluidos</span>
              </div>
            </div>

            <div className="public-value-panel" aria-label="Qué ofrece OpoCoach">
              <span className="eyebrow">Todo tu entrenamiento en un solo lugar</span>
              <div className="value-step">
                <span className="value-step-number">01</span>
                <div>
                  <strong>Simula el examen</strong>
                  <p>
                    Practica con pruebas completas construidas para tu convocatoria.
                  </p>
                </div>
              </div>
              <div className="value-step">
                <span className="value-step-number">02</span>
                <div>
                  <strong>Refuerza lo que necesitas</strong>
                  <p>
                    Crea tests por temas o por leyes y normas concretas.
                  </p>
                </div>
              </div>
              <div className="value-step">
                <span className="value-step-number">03</span>
                <div>
                  <strong>Corrige con más información</strong>
                  <p>
                    Revisa resultados y compáralos con la seguridad con la que respondes.
                  </p>
                </div>
              </div>
              <div className="value-step">
                <span className="value-step-number">04</span>
                <div>
                  <strong>Resuelve dudas y profundiza</strong>
                  <p>
                    Consulta tus dudas con el apoyo del contenido de tu temario o explora conocimiento general para comprender mejor cada materia.
                  </p>
                </div>
              </div>
              <div className="value-trial">
                <strong>Empieza sin pagar</strong>
                <span>1 test gratuito · hasta 10 preguntas · corrección y PDFs incluidos</span>
              </div>
            </div>
          </section>

          <section className="public-proof" id="como-funciona">
            <div className="public-proof-heading">
              <div>
                <span className="eyebrow">Cómo funciona</span>
                <h2>De practicar preguntas a entender cómo estás preparando el examen</h2>
              </div>
              <p>
                OpoCoach acompaña todo el ciclo de entrenamiento: eliges qué
                practicar, respondes, corriges y utilizas lo aprendido para decidir
                dónde concentrar el siguiente esfuerzo.
              </p>
            </div>

            <div className="public-process">
              <article id="simulacros">
                <span className="process-number">01</span>
                <div className="process-content">
                  <span className="process-kicker">Entrena</span>
                  <h3>Elige cómo quieres practicar</h3>
                  <p>
                    Haz un simulacro completo o construye un test específico por
                    temas, leyes o normas de tu convocatoria.
                  </p>
                </div>
              </article>

              <article id="tests">
                <span className="process-number">02</span>
                <div className="process-content">
                  <span className="process-kicker">Responde</span>
                  <h3>Contesta y registra tu seguridad</h3>
                  <p>
                    Resuelve las preguntas como en una prueba real y, si lo deseas,
                    indica con qué seguridad has elegido cada respuesta.
                  </p>
                </div>
              </article>

              <article>
                <span className="process-number">03</span>
                <div className="process-content">
                  <span className="process-kicker">Analiza</span>
                  <h3>Corrige y detecta dónde está el riesgo</h3>
                  <p>
                    Revisa aciertos, fallos y preguntas no contestadas, y compara
                    el resultado con tu nivel de confianza para localizar errores
                    que merecen más atención.
                  </p>
                </div>
              </article>

              <article>
                <span className="process-number">04</span>
                <div className="process-content">
                  <span className="process-kicker">Profundiza</span>
                  <h3>Resuelve dudas con el Chat</h3>
                  <p>
                    Consulta el contenido de tu convocatoria o amplía la explicación
                    con conocimiento general para comprender mejor la materia antes
                    de volver a practicar.
                  </p>
                </div>
              </article>
            </div>
          </section>

          <section className="public-highlight">
            <div>
              <span className="eyebrow">No sólo una nota</span>
              <h2>Entiende también cómo estás respondiendo</h2>
              <p>
                OpoCoach conserva tus resultados y te permite revisar el
                rendimiento acumulado por temas, normas y nivel de seguridad.
              </p>
            </div>
            <div className="highlight-stats">
              <div>
                <span>Por tema</span>
                <strong>Detecta tus puntos débiles</strong>
              </div>
              <div>
                <span>Por norma</span>
                <strong>Localiza dónde reforzar</strong>
              </div>
              <div>
                <span>Por seguridad</span>
                <strong>Identifica errores de exceso de confianza</strong>
              </div>
            </div>
          </section>

          <section className="public-pricing" id="precio">
            <div>
              <span className="eyebrow">Precio sencillo</span>
              <h2>Prueba OpoCoach antes de suscribirte</h2>
              <p>
                Empieza con un test gratuito de hasta 10 preguntas. Si te resulta
                útil, activa el acceso completo.
              </p>
            </div>

            <div className="pricing-card">
              <span className="pricing-name">OpoCoach</span>
              <div className="pricing-price">
                <strong>10 €</strong>
                <span>/ mes</span>
              </div>
              <ul>
                <li>Simulacros completos</li>
                <li>Tests por temas y normas</li>
                <li>Corrección y análisis acumulado</li>
                <li>PDFs de preguntas y soluciones</li>
                <li>Chat de apoyo de la convocatoria</li>
              </ul>
              <button
                type="button"
                className="primary public-cta"
                onClick={() => {
                  setError("");
                  setMensaje("");
                  setPantallaPublica("REGISTRO");
                }}
              >
                Probar gratis
              </button>
              <span className="pricing-note">
                La prueba gratuita incluye un test de hasta 10 preguntas.
              </span>
            </div>
          </section>

          <section className="public-final-cta">
            <div>
              <span className="eyebrow">Empieza ahora</span>
              <h2>Haz tu primer test y comprueba cómo trabaja OpoCoach.</h2>
            </div>
            <button
              type="button"
              className="primary public-cta"
              onClick={() => {
                setError("");
                setMensaje("");
                setPantallaPublica("REGISTRO");
              }}
            >
              Crear cuenta y probar
            </button>
          </section>

          <footer className="public-footer">
            <strong>OpoCoach</strong>
            <span>Preparación de oposiciones</span>
          </footer>
        </main>
      );
    }

    const esRegistro = pantallaPublica === "REGISTRO";

    return (
      <main className="auth-shell">
        <button
          type="button"
          className="auth-back"
          onClick={() => {
            setError("");
            setMensaje("");
            setPantallaPublica("LANDING");
          }}
        >
          ← Volver a OpoCoach
        </button>

        <section className="auth-layout">
          <div className="auth-intro">
            <button
              type="button"
              className="brand auth-brand"
              onClick={() => setPantallaPublica("LANDING")}
            >
              <span className="brand-mark">O</span>
              <span>OpoCoach</span>
            </button>

            <span className="public-kicker">
              {esRegistro ? "Empieza con una prueba gratuita" : "Bienvenido de nuevo"}
            </span>
            <h1>
              {esRegistro
                ? "Crea tu cuenta y haz tu primer test."
                : "Continúa con tu preparación."}
            </h1>
            <p>
              {esRegistro
                ? "La cuenta gratuita te permite realizar un test de hasta 10 preguntas con corrección y PDFs."
                : "Accede a tus simulacros, tests, resultados y herramientas de preparación."}
            </p>

            <div className="auth-points">
              <span>Simulacros y tests</span>
              <span>Corrección por seguridad</span>
              <span>Histórico y PDFs</span>
            </div>
          </div>

          <div className="auth-card">
            <span className="eyebrow">
              {esRegistro ? "Crear cuenta" : "Acceso"}
            </span>
            <h2>{esRegistro ? "Prueba OpoCoach gratis" : "Iniciar sesión"}</h2>

            {error && <div className="error">{error}</div>}
            {mensaje && <div className="success">{mensaje}</div>}

            <form onSubmit={esRegistro ? crearCuenta : iniciarSesion}>
              <label htmlFor="email">Correo electrónico</label>
              <input
                id="email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />

              <label htmlFor="password">Contraseña</label>
              <input
                id="password"
                type="password"
                autoComplete={esRegistro ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={6}
                required
              />

              <button
                className="primary auth-submit"
                disabled={ocupado}
                type="submit"
              >
                {ocupado
                  ? esRegistro
                    ? "Creando cuenta..."
                    : "Entrando..."
                  : esRegistro
                    ? "Crear cuenta"
                    : "Entrar"}
              </button>
            </form>

            <div className="auth-switch">
              <span>
                {esRegistro ? "¿Ya tienes cuenta?" : "¿Todavía no tienes cuenta?"}
              </span>
              <button
                type="button"
                className="text-action"
                onClick={() => {
                  setError("");
                  setMensaje("");
                  setPantallaPublica(esRegistro ? "LOGIN" : "REGISTRO");
                }}
              >
                {esRegistro ? "Iniciar sesión" : "Probar gratis"}
              </button>
            </div>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="page app-page">
      {simulacroId === null && (
        <>
          <header className="app-header">
            <button
              type="button"
              className="brand"
              onClick={() => setSeccion("INICIO")}
              aria-label="Ir al inicio"
            >
              <span className="brand-mark">O</span>
              <span>OpoCoach</span>
            </button>

            <nav className="app-nav" aria-label="Navegación principal">
              <button
                type="button"
                className={seccion === "INICIO" ? "nav-link active" : "nav-link"}
                onClick={() => setSeccion("INICIO")}
              >
                Inicio
              </button>
              <button
                type="button"
                className={seccion === "SIMULACROS" ? "nav-link active" : "nav-link"}
                onClick={() => setSeccion("SIMULACROS")}
              >
                Simulacros
              </button>
              <button
                type="button"
                className={seccion === "TESTS" ? "nav-link active" : "nav-link"}
                onClick={() => setSeccion("TESTS")}
              >
                Tests
              </button>
              <button
                type="button"
                className={seccion === "CHAT" ? "nav-link active" : "nav-link"}
                onClick={() => setSeccion("CHAT")}
              >
                Chat
              </button>
            </nav>

            <div className="account-area">
              {estadoSuscripcion?.suscrito && (
                <button
                  type="button"
                  className="plan-chip"
                  disabled={ocupado}
                  onClick={abrirPortalSuscripcion}
                  title="Gestionar suscripción"
                >
                  {estadoSuscripcion.pago_pendiente
                    ? "Pago pendiente"
                    : estadoSuscripcion.cancelacion_programada
                      ? "Plan activo · baja programada"
                      : "Plan activo"}
                </button>
              )}
              <div className="account-identity">
                <span className="account-avatar">{inicialUsuario}</span>
                <span className="account-email">
                  {me?.email ?? "Usuario"}
                </span>
              </div>
              <button
                type="button"
                className="logout-button"
                onClick={cerrarSesion}
                title="Cerrar sesión"
              >
                Salir
              </button>
            </div>
          </header>

          {estadoSuscripcion &&
            (
              !estadoSuscripcion.suscrito ||
              estadoSuscripcion.pago_pendiente ||
              estadoSuscripcion.cancelacion_programada ||
              checkoutRetorno === "success" ||
              checkoutRetorno === "cancel"
            ) && (
            <section
              className={
                estadoSuscripcion.pago_pendiente
                  ? "subscription-banner subscription-warning"
                  : estadoSuscripcion.cancelacion_programada
                    ? "subscription-banner subscription-info"
                    : "subscription-banner"
              }
            >
              <div>
                <strong>
                  {estadoSuscripcion.pago_pendiente
                    ? "Hay un problema con el pago"
                    : estadoSuscripcion.cancelacion_programada
                      ? `Suscripción activa hasta ${
                          formatearFechaSuscripcion(
                            estadoSuscripcion.cancel_at ??
                              estadoSuscripcion.current_period_end
                          ) ?? "la fecha de baja"
                        }`
                      : estadoSuscripcion.suscrito
                        ? "Suscripción activa"
                        : estadoSuscripcion.prueba_gratuita_disponible
                          ? "Prueba gratuita disponible"
                          : "Suscripción no activa"}
                </strong>
                <span>
                  {estadoSuscripcion.pago_pendiente
                    ? "Tu acceso continúa temporalmente. Revisa tu método de pago."
                    : estadoSuscripcion.cancelacion_programada
                      ? "Conservas el acceso completo hasta la fecha indicada."
                      : estadoSuscripcion.prueba_gratuita_disponible
                        ? "Puedes realizar un test gratuito de hasta 10 preguntas con todas sus funciones."
                        : "Activa una suscripción para crear nuevas pruebas y utilizar todas las funciones."}
                </span>

                {checkoutRetorno === "success" && (
                  <span>
                    Stripe ha completado el pago. Puedes comprobar de nuevo el estado si el webhook todavía está procesándose.
                  </span>
                )}
                {checkoutRetorno === "cancel" && (
                  <span>El proceso de pago se ha cancelado.</span>
                )}
              </div>

              <div className="subscription-actions">
                {estadoSuscripcion.suscrito ? (
                  <button
                    type="button"
                    className="secondary compact-button"
                    disabled={ocupado}
                    onClick={abrirPortalSuscripcion}
                  >
                    Gestionar suscripción
                  </button>
                ) : (
                  <button
                    type="button"
                    className="primary compact-button"
                    disabled={ocupado}
                    onClick={abrirCheckout}
                  >
                    Activar suscripción
                  </button>
                )}

                {checkoutRetorno === "success" && (
                  <button
                    type="button"
                    className="secondary compact-button"
                    onClick={actualizarSuscripcion}
                  >
                    Comprobar estado
                  </button>
                )}
              </div>
            </section>
          )}
        </>
      )}

      {(error || mensaje || accionEnCurso) && (
        <div className="feedback-stack" role="status" aria-live="polite">
          {error && (
            <div className="error feedback-message">
              <div className="feedback-text">{error}</div>
              <button
                type="button"
                className="feedback-close"
                aria-label="Cerrar mensaje"
                onClick={() => setError("")}
              >
                ×
              </button>
            </div>
          )}
          {mensaje && (
            <div className="success feedback-message">
              <div className="feedback-text">{mensaje}</div>
              <button
                type="button"
                className="feedback-close"
                aria-label="Cerrar mensaje"
                onClick={() => setMensaje("")}
              >
                ×
              </button>
            </div>
          )}
          {accionEnCurso && (
            accionEnCurso === "Creando simulacro..." ? (
              <div className="working feedback-message long-operation-message">
                <span className="loading-spinner loading-spinner-large" aria-hidden="true" />
                <div className="feedback-text">
                  <strong>Preparando el simulacro</strong>
                  <span>
                    Estamos seleccionando y organizando las preguntas de tu convocatoria.
                    Esta operación puede tardar unos segundos.
                  </span>
                  <small>
                    No cierres esta página; el simulacro aparecerá automáticamente cuando
                    esté listo.
                  </small>
                </div>
              </div>
            ) : accionEnCurso === "Creando test..." ? (
              <div className="working feedback-message long-operation-message">
                <span className="loading-spinner loading-spinner-large" aria-hidden="true" />
                <div className="feedback-text">
                  <strong>Preparando el test</strong>
                  <span>
                    Estamos seleccionando y organizando las preguntas según los criterios
                    elegidos. Esta operación puede tardar unos segundos.
                  </span>
                  <small>
                    No cierres esta página; el test aparecerá automáticamente cuando esté
                    listo.
                  </small>
                </div>
              </div>
            ) : accionEnCurso === "Generando PDF de soluciones..." ? (
              <div className="working feedback-message long-operation-message">
                <span className="loading-spinner loading-spinner-large" aria-hidden="true" />
                <div className="feedback-text">
                  <strong>Preparando el PDF de soluciones</strong>
                  <span>
                    Estamos generando las explicaciones de las respuestas. En una prueba
                    completa puede tardar alrededor de un minuto.
                  </span>
                  <small>
                    No cierres esta página; la descarga comenzará automáticamente cuando
                    termine.
                  </small>
                </div>
              </div>
            ) : accionEnCurso === "Analizando los resultados acumulados..." ? (
              <div className="working feedback-message long-operation-message">
                <span className="loading-spinner loading-spinner-large" aria-hidden="true" />
                <div className="feedback-text">
                  <strong>Analizando tu rendimiento</strong>
                  <span>
                    Estamos procesando tus resultados y preparando el análisis
                    personalizado. Esta operación puede tardar unos segundos.
                  </span>
                  <small>
                    Mantén esta página abierta; el análisis aparecerá automáticamente.
                  </small>
                </div>
              </div>
            ) : (
              <div className="working feedback-message">
                <span className="loading-spinner" aria-hidden="true" />
                <div className="feedback-text">{accionEnCurso}</div>
              </div>
            )
          )}
        </div>
      )}

      {simulacroId === null && seccion === "INICIO" && (
        <div className="home-dashboard">
          <section className="home-hero">
            <div>
              <span className="eyebrow">Tu preparación</span>
              <h1>Prepárate con criterio, no sólo con más preguntas.</h1>
              <p>
                Simulacros completos, tests dirigidos y correcciones que te ayudan
                a detectar dónde fallas y con qué nivel de seguridad respondes.
              </p>
              <div className="hero-actions">
                <button
                  type="button"
                  className="primary primary-large"
                  onClick={() => setSeccion("SIMULACROS")}
                >
                  Crear simulacro
                </button>
                <button
                  type="button"
                  className="secondary primary-large"
                  onClick={() => setSeccion("TESTS")}
                >
                  Crear test
                </button>
              </div>
            </div>

            <div className="hero-summary">
              <span className="summary-label">Tu actividad</span>
              <strong>{totalPruebas}</strong>
              <span>pruebas guardadas</span>
              <div className="summary-divider" />
              <div className="summary-mini-grid">
                <div>
                  <strong>{totalPendientes}</strong>
                  <span>Pendientes</span>
                </div>
                <div>
                  <strong>{totalCorregidas}</strong>
                  <span>Corregidas</span>
                </div>
              </div>
            </div>
          </section>

          <section className="home-grid">
            <div className="home-panel home-panel-wide">
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">Actividad reciente</span>
                  <h2>Continúa donde lo dejaste</h2>
                </div>
                {actividadReciente.length > 0 && (
                  <span className="muted">{actividadReciente.length} recientes</span>
                )}
              </div>

              {actividadReciente.length === 0 ? (
                <div className="empty-state">
                  <strong>Aún no tienes pruebas guardadas</strong>
                  <span>
                    Crea tu primer simulacro o construye un test por temas o normas.
                  </span>
                </div>
              ) : (
                <div className="recent-list">
                  {actividadReciente.map((item) => (
                    <button
                      type="button"
                      className="recent-item"
                      key={`${item.tipo_prueba}-${item.id}`}
                      onClick={() => abrirSimulacro(item)}
                    >
                      <span
                        className={
                          item.tipo_prueba === "SIMULACRO"
                            ? "recent-icon recent-icon-blue"
                            : "recent-icon recent-icon-green"
                        }
                      >
                        {item.tipo_prueba === "SIMULACRO" ? "S" : "T"}
                      </span>
                      <span className="recent-main">
                        <strong>
                          {item.tipo_prueba === "SIMULACRO" ? "Simulacro" : "Test"} Nº {item.numero}
                        </strong>
                        <span>
                          {item.convocatoria_codigo ?? `Convocatoria ${item.convocatoria_id}`} ·{" "}
                          {item.total_preguntas} preguntas · {item.contestadas} contestadas
                        </span>
                      </span>
                      <span
                        className={
                          item.estado === "FINALIZADO"
                            ? "status status-finished"
                            : "status status-pending"
                        }
                      >
                        {item.estado === "FINALIZADO" ? "Corregido" : "Pendiente"}
                      </span>
                      <span className="recent-action">
                        {item.estado === "FINALIZADO"
                          ? "Ver corrección"
                          : itemSoloLectura(item)
                            ? "Ver"
                            : "Continuar"}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <aside className="home-panel">
              <span className="eyebrow">Convocatorias</span>
              <h2>Tu espacio de preparación</h2>
              <p className="muted">
                {convocatorias.length === 1
                  ? "Tienes 1 convocatoria disponible."
                  : `Tienes ${convocatorias.length} convocatorias disponibles.`}
              </p>

              <div className="convocatoria-summary-list">
                {convocatorias.map((convocatoria) => (
                  <div className="convocatoria-summary" key={convocatoria.id}>
                    <span className="convocatoria-code">{convocatoria.codigo}</span>
                    <strong>{convocatoria.puesto}</strong>
                  </div>
                ))}
              </div>

              <button
                type="button"
                className="text-action"
                onClick={() => setSeccion("CHAT")}
              >
                Consultar OpoCoach →
              </button>
            </aside>
          </section>

          <section className="feature-strip">
            <div>
              <span className="feature-number">01</span>
              <strong>Simula el examen</strong>
              <span>Practica con la estructura de tu convocatoria.</span>
            </div>
            <div>
              <span className="feature-number">02</span>
              <strong>Refuerza puntos concretos</strong>
              <span>Construye tests por temas o por leyes y normas.</span>
            </div>
            <div>
              <span className="feature-number">03</span>
              <strong>Revisa cómo respondes</strong>
              <span>Compara aciertos, errores y seguridad declarada.</span>
            </div>
          </section>
        </div>
      )}

      {simulacroId !== null && preguntas.length > 0 && (
        <section className="card">
          <h2>Documentos de la prueba</h2>
          <p className="muted">
            Los dos documentos se generan a partir de la copia congelada de esta
            prueba. Puedes descargarlos aunque no hayas corregido la prueba en la
            aplicación, por ejemplo para realizarla y corregirla en papel.
          </p>
          <div className="actions">
            <button
              className="secondary"
              disabled={ocupado}
              onClick={descargarPdfPreguntas}
            >
              {ocupado && accionEnCurso === "Generando PDF de preguntas..."
                ? "Generando PDF..."
                : "Descargar PDF de preguntas"}
            </button>

            <button
              className="secondary"
              disabled={ocupado}
              onClick={descargarPdfSoluciones}
            >
              {ocupado && accionEnCurso === "Generando PDF de soluciones..."
                ? "Generando PDF..."
                : "Descargar PDF de soluciones"}
            </button>
          </div>
        </section>
      )}

      {resultado && (
        <section className="card">
          <div className="row space-between">
            <h2>Resultado</h2>
            <button
              className="secondary"
              type="button"
              onClick={() => setMostrarCorreccionPantalla((actual) => !actual)}
            >
              {mostrarCorreccionPantalla ? "Ocultar corrección en pantalla" : "Ver corrección en pantalla"}
            </button>
          </div>
          {!modoSoloLecturaActivo && (
            <button
              className="secondary"
              disabled={ocupado}
              onClick={modificarRespuestas}
              style={{ marginBottom: 16 }}
            >
              {ocupado && accionEnCurso === "Preparando modificación de respuestas..."
                ? "Preparando..."
                : "Modificar respuestas"}
            </button>
          )}
          {modoSoloLecturaActivo && (
            <p className="muted">
              Histórico en modo solo lectura. Puedes consultar la prueba y descargar sus PDFs.
            </p>
          )}
          <div className="result-grid">
            <div><strong>{resultado.nota.toFixed(2)}</strong><span>Nota</span></div>
            <div><strong>{resultado.aciertos}</strong><span>Aciertos</span></div>
            <div><strong>{resultado.fallos}</strong><span>Fallos</span></div>
            <div><strong>{resultado.no_contestadas}</strong><span>No contestadas</span></div>
            <div><strong>{resultado.puntos.toFixed(3)}</strong><span>Puntos</span></div>
            <div><strong>{formatearTiempo(resultado.tiempo_correccion_segundos)}</strong><span>Tiempo empleado</span></div>
          </div>
        </section>
      )}

      {resultado && resultadoAcumulado && (
        <section className="card">
          <h2>Rendimiento acumulado de la convocatoria</h2>
          {resultadoAcumulado.simulacros <= 0 ? (
            <p className="muted">
              Todavía no existen pruebas corregidas para mostrar estadísticas acumuladas.
            </p>
          ) : (
            <>
              <p className="muted">
                Las tablas siguientes corresponden a todos los{" "}
                {resultadoAcumulado.tipo_prueba === "TEST" ? "tests" : "simulacros"}{" "}
                corregidos que se conservan actualmente en esta convocatoria, no
                únicamente a la prueba abierta. Si se modifica o elimina una prueba,
                los resultados se recalculan automáticamente.
              </p>

              <p>
                <strong>Datos acumulados:</strong>{" "}
                {resultadoAcumulado.simulacros}{" "}
                {resultadoAcumulado.tipo_prueba === "TEST" ? "tests" : "simulacros"} ·{" "}
                {resultadoAcumulado.preguntas} preguntas ·{" "}
                {resultadoAcumulado.contestadas} contestadas ·{" "}
                {resultadoAcumulado.no_contestadas} no contestadas.
              </p>

              <h3>Resultados acumulados por tema</h3>
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Tema</th>
                      <th>Preguntas</th>
                      <th>% acumulado</th>
                      <th>Aciertos</th>
                      <th>% aciertos</th>
                      <th>Fallos</th>
                      <th>% fallos</th>
                      <th>No contestadas</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resultadoAcumulado.temas.map((tema) => (
                      <tr key={`${tema.parte}-${tema.numero_tema}-${tema.titulo}`}>
                        <td>{tema.parte} {tema.numero_tema}. {tema.titulo}</td>
                        <td>{tema.preguntas}</td>
                        <td>{tema.porcentaje_convocatoria.toFixed(1)} %</td>
                        <td>{tema.aciertos}</td>
                        <td>{tema.porcentaje_aciertos.toFixed(1)} %</td>
                        <td>{tema.fallos}</td>
                        <td>{tema.porcentaje_fallos.toFixed(1)} %</td>
                        <td>{tema.no_contestadas}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted">
                El porcentaje acumulado indica el peso de cada tema sobre todas las
                preguntas analizadas. Los porcentajes de aciertos y fallos se calculan
                sobre el total de preguntas de ese tema.
              </p>

              <h3>Resultados acumulados por ley o norma</h3>
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Ley o norma</th>
                      <th>Preguntas</th>
                      <th>% acumulado</th>
                      <th>Aciertos</th>
                      <th>% aciertos</th>
                      <th>Fallos</th>
                      <th>% fallos</th>
                      <th>No contestadas</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resultadoAcumulado.normas.map((norma) => (
                      <tr key={norma.norma}>
                        <td>{norma.norma}</td>
                        <td>{norma.preguntas}</td>
                        <td>{norma.porcentaje_convocatoria.toFixed(1)} %</td>
                        <td>{norma.aciertos}</td>
                        <td>{norma.porcentaje_aciertos.toFixed(1)} %</td>
                        <td>{norma.fallos}</td>
                        <td>{norma.porcentaje_fallos.toFixed(1)} %</td>
                        <td>{norma.no_contestadas}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted">
                Las preguntas jurídicas se agrupan por la ley o norma congelada en
                cada prueba. Las preguntas de informática aparecen agrupadas como
                «Informática».
              </p>

              {resultadoAcumulado.seguridad.length > 0 && (
                <>
                  <h3>Resultados acumulados por nivel de seguridad</h3>
                  <div style={{ overflowX: "auto" }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Seguridad</th>
                          <th>Contestadas</th>
                          <th>Aciertos</th>
                          <th>% aciertos</th>
                          <th>Fallos</th>
                          <th>% fallos</th>
                        </tr>
                      </thead>
                      <tbody>
                        {resultadoAcumulado.seguridad.map((seguridad) => (
                          <tr key={seguridad.codigo}>
                            <td>{seguridad.seguridad}</td>
                            <td>{seguridad.contestadas}</td>
                            <td>{seguridad.aciertos}</td>
                            <td>{seguridad.porcentaje_aciertos.toFixed(1)} %</td>
                            <td>{seguridad.fallos}</td>
                            <td>{seguridad.porcentaje_fallos.toFixed(1)} %</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="muted">
                    Los porcentajes se calculan únicamente sobre las preguntas
                    contestadas en pruebas en las que se valoró la seguridad.
                  </p>
                </>
              )}
            </>
          )}
        </section>
      )}

      {resultado &&
        resultadoAcumulado &&
        resultadoAcumulado.simulacros > 0 &&
        !modoSoloLecturaActivo && (
        <section className="card">
          <h2>Análisis acumulado de la convocatoria</h2>
          <p className="muted">
            El análisis utiliza todas las pruebas corregidas del mismo tipo que
            la prueba abierta y que se conservan actualmente en esta convocatoria,
            no únicamente esta corrección. Si se elimina o modifica una prueba,
            los datos se recalculan.
          </p>
          <p>
            <strong>Datos considerados:</strong>{" "}
            {resultadoAcumulado.simulacros}{" "}
            {resultadoAcumulado.tipo_prueba === "TEST" ? "tests" : "simulacros"} ·{" "}
            {resultadoAcumulado.preguntas} preguntas.
          </p>

          {analisisActual() && (
            <div style={{ marginTop: 18 }}>
              {renderAnalisisRendimiento(analisisActual()!.texto)}
            </div>
          )}

          <button
            className="secondary"
            disabled={ocupado}
            onClick={generarAnalisisRendimiento}
          >
            {ocupado && accionEnCurso === "Analizando los resultados acumulados..."
              ? "Analizando..."
              : analisisActual()
                ? "Regenerar análisis de rendimiento"
                : "Generar análisis de rendimiento"}
          </button>
        </section>
      )}

      {simulacroId === null && seccion === "CHAT" && (
        <section className="card">
          <h2>Chat</h2>

          {modoHistoricoPostBaja && (
            <div className="working" style={{ marginBottom: 18 }}>
              El Chat no está disponible durante el acceso histórico posterior a la baja.
            </div>
          )}

          {!modoHistoricoPostBaja && (
            <>
          <label htmlFor="chat-convocatoria">Convocatoria</label>
          <select
            id="chat-convocatoria"
            value={chatConvocatoriaId ?? ""}
            onChange={(event) => {
              const valor = Number(event.target.value);
              setChatConvocatoriaId(Number.isFinite(valor) ? valor : null);
              setChatEntrada("");
              setError("");
              setMensaje("");
            }}
          >
            {convocatorias.map((convocatoria) => (
              <option key={convocatoria.id} value={convocatoria.id}>
                {convocatoria.codigo} — {convocatoria.puesto}
              </option>
            ))}
          </select>

          <h3>Modo de consulta</h3>
          <div className="options">
            <label>
              <input
                type="radio"
                name="chat-modo"
                checked={chatModo === "CONVOCATORIA"}
                onChange={() => {
                  setChatModo("CONVOCATORIA");
                  setChatEntrada("");
                  setError("");
                  setMensaje("");
                }}
              />{" "}
              Convocatoria y OpoCoach
            </label>
            <label>
              <input
                type="radio"
                name="chat-modo"
                checked={chatModo === "GENERAL"}
                onChange={() => {
                  setChatModo("GENERAL");
                  setChatEntrada("");
                  setError("");
                  setMensaje("");
                }}
              />{" "}
              Conocimiento general de GPT
            </label>
          </div>

          {chatModo === "CONVOCATORIA" ? (
            <div className="working" style={{ marginTop: 14 }}>
              Las respuestas se limitan al corpus de la convocatoria activa y
              a la base de conocimiento de OpoCoach.
            </div>
          ) : (
            <div className="working" style={{ marginTop: 14 }}>
              Este modo utiliza conocimiento general de GPT. Sus respuestas
              pueden incluir información ajena al temario y no están respaldadas
              por el corpus de la convocatoria.
            </div>
          )}

          <div style={{ marginTop: 18, marginBottom: 18 }}>
            <button
              type="button"
              className="secondary"
              disabled={ocupado || mensajesChatActuales().length === 0}
              onClick={limpiarChatActual}
            >
              Limpiar conversación
            </button>
          </div>

          <div style={{ display: "grid", gap: 12, marginBottom: 18 }}>
            {mensajesChatActuales().length === 0 ? (
              <p className="muted">La conversación está vacía.</p>
            ) : (
              mensajesChatActuales().map((mensajeChat, indice) => (
                <div
                  key={`${mensajeChat.role}-${indice}`}
                  style={{
                    padding: 14,
                    border: "1px solid #d9d9d9",
                    borderRadius: 8,
                    background:
                      mensajeChat.role === "user" ? "#f7f7f7" : "white",
                  }}
                >
                  <strong>
                    {mensajeChat.role === "user" ? "Tú" : "OpoCoach"}
                  </strong>
                  <div
                    style={{
                      marginTop: 8,
                      whiteSpace: "pre-wrap",
                      lineHeight: 1.55,
                    }}
                  >
                    {mensajeChat.content}
                  </div>
                </div>
              ))
            )}
          </div>

          <form onSubmit={enviarChat}>
            <label htmlFor="chat-pregunta">
              {chatModo === "CONVOCATORIA"
                ? "Escriba una duda sobre la convocatoria o sobre OpoCoach"
                : "Escriba una pregunta de conocimiento general"}
            </label>
            <textarea
              id="chat-pregunta"
              rows={4}
              value={chatEntrada}
              disabled={ocupado || chatConvocatoriaId === null}
              onChange={(event) => setChatEntrada(event.target.value)}
            />
            <div style={{ marginTop: 12 }}>
              <button
                type="submit"
                className="primary"
                disabled={
                  ocupado ||
                  chatConvocatoriaId === null ||
                  chatEntrada.trim().length === 0
                }
              >
                {ocupado && accionEnCurso?.includes("fuentes")
                  ? "Consultando..."
                  : ocupado && accionEnCurso?.includes("conocimiento general")
                    ? "Generando..."
                    : "Enviar"}
              </button>
            </div>
          </form>
            </>
          )}
        </section>
      )}

      {simulacroId === null &&
        seccion === "SIMULACROS" &&
        !modoHistoricoPostBaja && (
        <section className="card">
          <h2>Crear simulacro</h2>
          <p className="muted">Selecciona la convocatoria y crea una prueba completa.</p>

          <label htmlFor="convocatoria-simulacro">Convocatoria</label>
          <select
            id="convocatoria-simulacro"
            className="select"
            value={convocatoriaSimulacroId ?? ""}
            onChange={(e) => setConvocatoriaSimulacroId(Number(e.target.value))}
          >
            {convocatorias.map((convocatoria) => (
              <option key={convocatoria.id} value={convocatoria.id}>
                {convocatoria.codigo} — {convocatoria.puesto}
              </option>
            ))}
          </select>

          <div style={{ marginTop: 18 }}>
            <button
              className="primary"
              disabled={ocupado || convocatoriaSimulacroId === null}
              onClick={() => convocatoriaSimulacroId !== null && crear(convocatoriaSimulacroId)}
            >
              {ocupado && accionEnCurso === "Creando simulacro..."
                ? "Creando simulacro..."
                : "Crear simulacro"}
            </button>
          </div>
        </section>
      )}

      {simulacroId === null && seccion === "SIMULACROS" && (
        <section className="card">
          <h2>Mis simulacros</h2>
          {misSimulacros.length === 0 ? (
            <p className="muted">Todavía no hay simulacros guardados.</p>
          ) : (
            <div className="saved-list">
              {misSimulacros.map((simulacro) => (
                <div className="saved-row" key={simulacro.id}>
                  <div className="saved-main">
                    <strong>
                      Nº {simulacro.numero} ·{" "}
                      {simulacro.convocatoria_codigo ?? `Convocatoria ${simulacro.convocatoria_id}`}
                    </strong>
                    <div className="muted">
                      {new Date(simulacro.fecha_generacion).toLocaleString("es-ES")} ·{" "}
                      {simulacro.total_preguntas} preguntas ·{" "}
                      {simulacro.contestadas} contestadas
                    </div>
                  </div>

                  <span
                    className={
                      simulacro.estado === "FINALIZADO"
                        ? "status status-finished"
                        : "status status-pending"
                    }
                  >
                    {simulacro.estado === "FINALIZADO"
                      ? "Corregido"
                      : "Pendiente"}
                  </span>

                  <div className="saved-actions">
                    <button
                      className="secondary"
                      disabled={ocupado}
                      onClick={() => abrirSimulacro(simulacro)}
                    >
                      {simulacro.estado === "FINALIZADO"
                        ? "Ver corrección"
                        : itemSoloLectura(simulacro)
                          ? "Ver preguntas"
                          : "Continuar"}
                    </button>
                    {!itemSoloLectura(simulacro) && (
                      <button
                        className="danger"
                        disabled={ocupado}
                        onClick={() => eliminarGuardado(simulacro)}
                      >
                        Eliminar
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {simulacroId === null && seccion === "TESTS" && !modoHistoricoPostBaja && (
        <>
          <section className="card">
            <h2>Construir test</h2>

            <label>Convocatoria</label>
            <select
              className="select"
              value={convocatoriaTestId ?? ""}
              onChange={(e) => {
                setConvocatoriaTestId(Number(e.target.value));
                setTemasSeleccionados([]);
                setNormasSeleccionadas([]);
              }}
            >
              {convocatorias.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.codigo} — {c.puesto}
                </option>
              ))}
            </select>

            <label>Número de preguntas</label>
            <input
              className="number-input"
              type="number"
              min={1}
              value={numeroPreguntasTest}
              onChange={(e) =>
                setNumeroPreguntasTest(Math.max(1, Number(e.target.value)))
              }
            />

            <h3>Generar preguntas por</h3>
            <div className="options">
              <label>
                <input
                  type="radio"
                  checked={modoTest === "TEMA"}
                  onChange={() => setModoTest("TEMA")}
                />{" "}
                Puntos del temario
              </label>
              <label>
                <input
                  type="radio"
                  checked={modoTest === "NORMA"}
                  onChange={() => setModoTest("NORMA")}
                />{" "}
                Ley o norma
              </label>
            </div>

            {modoTest === "TEMA" ? (
              <div className="selection-list">
                {temasTest.map((tema) => (
                  <label key={tema.id} className="selection-item">
                    <input
                      type="checkbox"
                      checked={temasSeleccionados.includes(tema.id)}
                      onChange={() =>
                        toggle(
                          String(tema.id),
                          temasSeleccionados.map(String),
                          (valores) =>
                            setTemasSeleccionados(valores.map(Number))
                        )
                      }
                    />
                    <span>
                      {tema.numero_tema}. {tema.parte} — {tema.titulo}
                    </span>
                  </label>
                ))}
              </div>
            ) : (
              <div className="selection-list">
                {normasTest.map((norma) => (
                  <label key={norma.norma_clave} className="selection-item">
                    <input
                      type="checkbox"
                      checked={normasSeleccionadas.includes(norma.norma_clave)}
                      onChange={() =>
                        toggle(
                          norma.norma_clave,
                          normasSeleccionadas,
                          setNormasSeleccionadas
                        )
                      }
                    />
                    <span>
                      {norma.norma_nombre}
                    </span>
                  </label>
                ))}
              </div>
            )}

            <div style={{ marginTop: 18 }}>
              <button
                className="primary"
                disabled={ocupado}
                onClick={crearTest}
              >
                {ocupado ? "Creando..." : "Crear test"}
              </button>
            </div>
          </section>

          <section className="card">
            <h2>Mis tests</h2>
            {misTests.length === 0 ? (
              <p className="muted">Todavía no hay tests guardados.</p>
            ) : (
              <div className="saved-list">
                {misTests.map((test) => (
                  <div className="saved-row" key={test.id}>
                    <div className="saved-main">
                      <strong>
                        Nº {test.numero} ·{" "}
                        {test.convocatoria_codigo ??
                          `Convocatoria ${test.convocatoria_id}`}
                      </strong>
                      <div className="muted">
                        {new Date(test.fecha_generacion).toLocaleString("es-ES")} ·{" "}
                        {test.total_preguntas} preguntas · {test.contestadas} contestadas
                      </div>
                    </div>
                    <span
                      className={
                        test.estado === "FINALIZADO"
                          ? "status status-finished"
                          : "status status-pending"
                      }
                    >
                      {test.estado === "FINALIZADO" ? "Corregido" : "Pendiente"}
                    </span>
                    <div className="saved-actions">
                      <button
                        className="secondary"
                        disabled={ocupado}
                        onClick={() => abrirSimulacro(test)}
                      >
                        {test.estado === "FINALIZADO"
                          ? "Ver corrección"
                          : itemSoloLectura(test)
                            ? "Ver preguntas"
                            : "Continuar"}
                      </button>
                      {!itemSoloLectura(test) && (
                        <button
                          className="danger"
                          disabled={ocupado}
                          onClick={() => eliminarGuardado(test)}
                        >
                          Eliminar
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

        </>
      )}

      {simulacroId !== null && (
        <section className="card sticky-actions">
          <div className="simulacro-toolbar">
            <div>
              <strong>{tipoActivo === "TEST" ? "Test" : "Simulacro"} {simulacroId}</strong>
              <div className="muted">
                {resultado
                  ? "Prueba corregida. Puedes revisar el resultado, descargar los PDFs o volver a tu espacio de trabajo."
                  : vistaPrueba === "RESUMEN"
                    ? "Elige si quieres realizar la prueba en pantalla o trabajar con los documentos PDF."
                    : evaluarSeguridad
                      ? "Marca respuesta y seguridad en cada pregunta contestada."
                      : "Marca la respuesta de cada pregunta."}
              </div>
            </div>
            <div className="toolbar-actions">
              <button
                className="secondary"
                disabled={ocupado}
                onClick={() => salirDePrueba("INICIO")}
              >
                Inicio
              </button>
              <button
                className="secondary"
                disabled={ocupado}
                onClick={() => salirDePrueba("LISTA")}
              >
                {tipoActivo === "TEST" ? "Volver a mis tests" : "Volver a mis simulacros"}
              </button>
              {!resultado && vistaPrueba === "RESUMEN" && !modoSoloLecturaActivo && (
                <button
                  className="primary"
                  disabled={ocupado}
                  onClick={() => {
                    setVistaPrueba("PREGUNTAS");
                    window.scrollTo({ top: 0, behavior: "smooth" });
                  }}
                >
                  Realizar en pantalla
                </button>
              )}
              {!resultado && !modoSoloLecturaActivo && vistaPrueba === "PREGUNTAS" && (
                <>
                  <button className="secondary" disabled={ocupado} onClick={guardar}>
                    {ocupado && accionEnCurso?.startsWith("Guardando respuestas")
                      ? "Guardando..."
                      : "Guardar respuestas"}
                  </button>
                  <button className="primary calificar-button" disabled={ocupado} onClick={calificar}>
                    {ocupado && accionEnCurso?.includes("calificando")
                      ? "Calificando..."
                      : `Calificar ${tipoActivo === "TEST" ? "test" : "simulacro"}`}
                  </button>
                </>
              )}
            </div>
          </div>
        </section>
      )}

      {simulacroId !== null && !resultado && vistaPrueba === "PREGUNTAS" && (
        <section className="card">
          {modoSoloLecturaActivo ? (
            <div className="working" style={{ marginBottom: 18 }}>
              Histórico en modo solo lectura. Las respuestas no pueden modificarse.
            </div>
          ) : (
            <>
              <label style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
                <input
                  type="checkbox"
                  checked={mostrarCronometro}
                  onChange={(event) => setMostrarCronometro(event.target.checked)}
                />
                <span>Mostrar cronómetro</span>
              </label>
              <p className="muted" style={{ marginTop: 0 }}>
                El tiempo se registra igualmente aunque el cronómetro permanezca oculto.
              </p>

              {mostrarCronometro && inicioCorreccionMs !== null && (
                <div className="floating-timer" role="status" aria-live="polite">
                  <CronometroCorreccion
                    inicioMs={inicioCorreccionMs}
                    tiempoPrevio={tiempoPrevioCorreccion}
                  />
                </div>
              )}

              <label style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 18 }}>
                <input
                  type="checkbox"
                  checked={evaluarSeguridad}
                  onChange={(event) =>
                    cambiarEvaluacionSeguridad(event.target.checked)
                  }
                />
                <span>Evaluar seguridad en las respuestas</span>
              </label>
            </>
          )}

          {preguntas.map((pregunta) => {
            const local = respuestas[pregunta.simulacro_pregunta_id] ?? {
              respuesta: null,
              seguridad: null,
            };

            const opciones = [
              ["A", pregunta.opcion_a],
              ["B", pregunta.opcion_b],
              ["C", pregunta.opcion_c],
              ["D", pregunta.opcion_d],
            ];

            return (
              <article
                className="question"
                key={pregunta.simulacro_pregunta_id}
              >
                <strong>
                  {pregunta.orden}. {pregunta.parte_nombre ?? ""}
                </strong>
                <p>{pregunta.enunciado}</p>

                <div className="answer-options">
                  {opciones.map(([letra, texto]) => (
                    <label className="answer-line" key={letra}>
                      <input
                        type="radio"
                        name={`respuesta-${pregunta.simulacro_pregunta_id}`}
                        checked={local.respuesta === letra}
                        disabled={modoSoloLecturaActivo}
                        onChange={() =>
                          establecerRespuesta(
                            pregunta.simulacro_pregunta_id,
                            letra
                          )
                        }
                      />
                      <span>
                        <strong>{letra}.</strong> {texto}
                      </span>
                    </label>
                  ))}
                  <button
                    type="button"
                    className="link-button"
                    disabled={modoSoloLecturaActivo}
                    onClick={() =>
                      establecerRespuesta(
                        pregunta.simulacro_pregunta_id,
                        null
                      )
                    }
                  >
                    Dejar en blanco
                  </button>
                </div>

                {evaluarSeguridad && local.respuesta && (
                  <div className="security-box">
                    <span>Seguridad:</span>
                    {SEGURIDADES.map(([valor, etiqueta]) => (
                      <label key={valor}>
                        <input
                          type="radio"
                          name={`seguridad-${pregunta.simulacro_pregunta_id}`}
                          checked={local.seguridad === valor}
                          disabled={modoSoloLecturaActivo}
                          onChange={() =>
                            establecerSeguridad(
                              pregunta.simulacro_pregunta_id,
                              valor
                            )
                          }
                        />{" "}
                        {etiqueta}
                      </label>
                    ))}
                  </div>
                )}
              </article>
            );
          })}

          {!modoSoloLecturaActivo && (
            <div className="row final-actions">
              <button className="secondary" disabled={ocupado} onClick={guardar}>
                {ocupado && accionEnCurso?.startsWith("Guardando respuestas")
                  ? "Guardando..."
                  : "Guardar respuestas"}
              </button>
              <button className="primary calificar-button" disabled={ocupado} onClick={calificar}>
                {ocupado && accionEnCurso?.includes("calificando")
                  ? "Calificando..."
                  : `Calificar ${tipoActivo === "TEST" ? "test" : "simulacro"}`}
              </button>
            </div>
          )}
        </section>
      )}

      {resultado && mostrarCorreccionPantalla && (
        <section className="card">
          <div className="row space-between">
            <h2>Corrección en pantalla</h2>
            <button
              className="secondary"
              onClick={() => salirDePrueba("LISTA")}
            >
              {tipoActivo === "TEST" ? "Volver a mis tests" : "Volver a mis simulacros"}
            </button>
          </div>

          {correccion.map((pregunta) => (
            <article
              className={`question correction ${pregunta.resultado.toLowerCase()}`}
              key={pregunta.simulacro_pregunta_id}
            >
              <div className="row space-between">
                <strong>
                  {pregunta.orden}. {pregunta.parte_nombre ?? ""}
                </strong>
                <span className="result-label">
                  {pregunta.resultado === "ACIERTO"
                    ? "Acierto"
                    : pregunta.resultado === "FALLO"
                    ? "Fallo"
                    : "No contestada"}
                </span>
              </div>

              <p>{pregunta.enunciado}</p>
              <p className="option">A. {pregunta.opcion_a}</p>
              <p className="option">B. {pregunta.opcion_b}</p>
              <p className="option">C. {pregunta.opcion_c}</p>
              <p className="option">D. {pregunta.opcion_d}</p>

              <div className="correction-detail">
                <span>
                  Tu respuesta: <strong>{pregunta.respuesta_usuario ?? "—"}</strong>
                </span>
                <span>
                  Correcta: <strong>{pregunta.respuesta_correcta}</strong>
                </span>
                {pregunta.seguridad_usuario && (
                  <span>
                    Seguridad:{" "}
                    <strong>
                      {pregunta.seguridad_usuario.replaceAll("_", " ")}
                    </strong>
                  </span>
                )}
              </div>
            </article>
          ))}
        </section>
      )}
    </main>
  );
}
