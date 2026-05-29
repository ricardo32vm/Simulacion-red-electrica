"""
simulacion_red_electrica_v3.py
════════════════════════════════════════════════════════════════════════════════
Script para QGIS 3.40 — Simulador de red eléctrica con APR y motor híbrido
árbol / malla (BFS)
════════════════════════════════════════════════════════════════════════════════

NOVEDADES v3 respecto a v2:
  • Nuevo nivel APR (seccionadores BT) entre subestaciones y líneas_bt
  • Motor de propagación híbrido: árbol clásico O(N) + BFS para redes malladas
  • Grafo de conectividad BT híbrido: lee nodo_inicio/nodo_fin si existen,
    infiere topología por proximidad geométrica donde no hay atributos
  • Campo tipo_red en líneas_bt: 'arbol' / 'malla' (se crea automáticamente
    si no existe; el usuario lo puebla con la calculadora de campos de QGIS)
  • Selector en la UI: modo global fallback cuando tipo_red no está definido
  • Selección interactiva de APR y seccionadores MT por clic en el mapa

JERARQUÍA COMPLETA:
  seccionadores MT  [estado=2, start_line]
      └── línea_mt         [id]
               └── subestaciones      [linea_mt → línea_mt.id]
                        └── APR            [num_set → sub.id, línea_bt → bt.id]
                                  ├── [árbol]  líneas_bt → acometidas_bt → medidores
                                  └── [malla]  BFS(grafo_bt) → acometidas_bt → medidores

════════════════════════════════════════════════════════════════════════════════
"""

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRuleBasedRenderer, QgsSymbol,
    QgsFeatureRequest, QgsGeometry, QgsPointXY, QgsField, QgsFeature,
)
from qgis.gui import QgsMapToolEmitPoint
from qgis.PyQt.QtGui import QColor, QCursor
from qgis.PyQt.QtCore import Qt, QDateTime, pyqtSignal, QVariant
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QFrame, QSizePolicy, QWidget, QProgressBar,
    QGroupBox, QGridLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QApplication, QComboBox,
    QCheckBox, QButtonGroup, QRadioButton,
)
import qgis.utils
from collections import deque

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════

CAPA_SECCIONADORES   = "seccionadores"
CAPA_APR             = "apr"               # ← capa nueva de seccionadores BT
CAPA_LINEA_MT        = "línea_mt"
CAPA_SUBESTACIONES   = "subestaciones"
CAPA_LINEAS_BT       = "líneas_bt"
CAPA_ACOMETIDAS_BT   = "acometidas_bt"
CAPA_MEDIDORES       = "medidores"

# Campos seccionadores MT
CAMPO_ESTADO_SEC     = "estado"
CAMPO_START_LINE     = "start_line"
CAMPO_END_LINE       = "end_line"

# Campos APR
CAMPO_APR_ESTADO     = "estado"       # 1=cerrado, 2=abierto
CAMPO_APR_NUMSET     = "num_set"      # FK → subestaciones.id
CAMPO_APR_LINEABT    = "línea_bt"     # FK → líneas_bt.id (start_line del APR)

# Campos generales
CAMPO_LMT_ID         = "id"
CAMPO_SUB_LINEAMT    = "linea_mt"
CAMPO_SUB_ID         = "id"
CAMPO_BT_ID          = "id"
CAMPO_BT_TIPO_RED    = "tipo_red"     # 'arbol' o 'malla' (se crea si no existe)
CAMPO_BT_NODO_INI    = "nodo_inicio"  # opcional: nodo topológico inicio
CAMPO_BT_NODO_FIN    = "nodo_fin"     # opcional: nodo topológico fin
CAMPO_ACOM_LINEABT   = "línea_bt"
CAMPO_ACOM_ID        = "id"
CAMPO_MED_IDACOMET   = "id_acomet"

# Estados
ESTADO_CONECTADO     = 1
ESTADO_ABIERTO       = 2

# Modos de propagación BT
MODO_ARBOL           = "arbol"
MODO_MALLA           = "malla"
MODO_AUTOMATICO      = "auto"   # lee campo tipo_red de cada tramo

# Tolerancia geométrica para inferir nodos por proximidad (metros en POSGAR98)
TOLERANCIA_NODO_M    = 0.5

# Búsqueda por clic en mapa
RADIO_BUSQUEDA_MM    = 5

# Colores
COLOR_AFECTADO        = QColor(220, 38, 38)
COLOR_AFECTADO_APR    = QColor(234, 88, 12)   # naranja para cortes de APR
COLOR_NORMAL          = QColor(30, 30, 30)
ANCHO_LINEA_AFECTADA  = 1.2
TAMANO_PUNTO_AFECTADO = 4.0

# ══════════════════════════════════════════════════════════════════════════════
# ESTILOS Qt
# ══════════════════════════════════════════════════════════════════════════════

ESTILO_BASE = """
QDialog, QWidget { background-color: #1a1d23; color: #e8eaed;
  font-family: 'Consolas', 'Courier New', monospace; }
QLabel { color: #e8eaed; }

QPushButton#btn_simular {
  background-color: #dc2626; color: #fff; border: none; border-radius: 6px;
  padding: 10px 24px; font-size: 13px; font-weight: bold;
  font-family: 'Segoe UI', sans-serif; }
QPushButton#btn_simular:hover  { background-color: #ef4444; }
QPushButton#btn_simular:pressed{ background-color: #b91c1c; }
QPushButton#btn_simular:disabled{ background-color: #4a2020; color: #7a4040; }

QPushButton#btn_restaurar {
  background-color: #1e3a5f; color: #60a5fa; border: 1px solid #2563eb;
  border-radius: 6px; padding: 10px 24px; font-size: 13px; font-weight: bold;
  font-family: 'Segoe UI', sans-serif; }
QPushButton#btn_restaurar:hover{ background-color: #1e40af; color: #fff; }

QPushButton#btn_sec, QPushButton#btn_apr {
  background-color: #1e2530; color: #6b7280; border: 1px solid #374151;
  border-radius: 6px; padding: 8px 14px; font-size: 11px;
  font-family: 'Segoe UI', sans-serif; }
QPushButton#btn_sec:checked, QPushButton#btn_apr:checked {
  background-color: #dc2626; color: #fff; border-color: #dc2626; }
QPushButton#btn_sec:hover, QPushButton#btn_apr:hover {
  background-color: #252d3a; color: #9ca3af; }

QPushButton#btn_secundario {
  background-color: #1e2530; color: #6b7280; border: 1px solid #374151;
  border-radius: 6px; padding: 8px 18px; font-size: 11px;
  font-family: 'Segoe UI', sans-serif; }
QPushButton#btn_secundario:hover { background-color: #252d3a; color: #9ca3af; }

QTextEdit#log_consola {
  background-color: #0d1117; color: #c9d1d9; border: 1px solid #2d3340;
  border-radius: 6px; font-family: 'Consolas', monospace; font-size: 12px;
  padding: 8px; }

QTableWidget {
  background-color: #0d1117; color: #c9d1d9; border: 1px solid #2d3340;
  border-radius: 6px; gridline-color: #21262d; font-size: 12px;
  font-family: 'Consolas', monospace; }
QTableWidget::item { padding: 4px 8px; }
QTableWidget::item:selected { background-color: #264f78; }
QHeaderView::section {
  background-color: #161b22; color: #8b949e; border: none;
  border-bottom: 1px solid #2d3340; padding: 6px 10px; font-size: 10px;
  font-family: 'Segoe UI', sans-serif; letter-spacing: 1px; }

QTabWidget::pane { background-color: #1a1d23; border: 1px solid #2d3340;
  border-radius: 6px; }
QTabBar::tab { background-color: #1a1d23; color: #6b7280; border: none;
  padding: 8px 20px; font-family: 'Segoe UI', sans-serif; font-size: 11px;
  letter-spacing: 1px; }
QTabBar::tab:selected { color: #f9fafb; border-bottom: 2px solid #dc2626; }
QTabBar::tab:hover { color: #d1d5db; }

QProgressBar { background-color: #1e2530; border: none; border-radius: 3px;
  height: 4px; color: transparent; }
QProgressBar::chunk { background-color: #dc2626; border-radius: 3px; }

QGroupBox { background-color: #1e2530; border: 1px solid #2d3340;
  border-radius: 8px; margin-top: 12px; padding-top: 8px;
  font-family: 'Segoe UI', sans-serif; font-size: 10px;
  color: #6b7280; letter-spacing: 1.5px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left;
  padding: 0 8px; color: #6b7280; }

QComboBox { background-color: #1e2530; color: #c9d1d9; border: 1px solid #374151;
  border-radius: 5px; padding: 5px 10px; font-size: 11px;
  font-family: 'Segoe UI', sans-serif; }
QComboBox:hover { border-color: #4b5563; }
QComboBox QAbstractItemView { background-color: #1e2530; color: #c9d1d9;
  border: 1px solid #374151; selection-background-color: #264f78; }
QComboBox::drop-down { border: none; }

QRadioButton { color: #9ca3af; font-size: 11px;
  font-family: 'Segoe UI', sans-serif; spacing: 6px; }
QRadioButton:checked { color: #f9fafb; }
QRadioButton::indicator { width: 14px; height: 14px; border-radius: 7px;
  border: 1px solid #4b5563; background: #1e2530; }
QRadioButton::indicator:checked { border: 1px solid #dc2626;
  background: #dc2626; }

QFrame#separador { background-color: #2d3340; max-height: 1px; }
QScrollBar:vertical { background: #1a1d23; width: 8px; }
QScrollBar::handle:vertical { background: #374151; border-radius: 4px;
  min-height: 20px; }
QScrollBar::handle:vertical:hover { background: #4b5563; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

ESTILO_CONFIRMACION = """
QDialog { background-color: #1a1d23; border: 1px solid #2d3340;
  border-radius: 10px; }
QLabel { color: #e8eaed; font-family: 'Segoe UI', sans-serif; }
QPushButton { border-radius: 6px; padding: 9px 22px; font-size: 12px;
  font-weight: bold; font-family: 'Segoe UI', sans-serif; }
QPushButton#btn_confirmar { background-color: #dc2626; color: #fff;
  border: none; }
QPushButton#btn_confirmar:hover { background-color: #ef4444; }
QPushButton#btn_cancelar { background-color: transparent; color: #6b7280;
  border: 1px solid #374151; }
QPushButton#btn_cancelar:hover { background-color: #1f2937; color: #d1d5db; }
"""

# ══════════════════════════════════════════════════════════════════════════════
# HERRAMIENTA DE SELECCIÓN POR MOUSE (genérica: sirve para MT y APR)
# ══════════════════════════════════════════════════════════════════════════════

class HerramientaSeleccion(QgsMapToolEmitPoint):
    seleccionado  = pyqtSignal(object)   # emite QgsFeature
    cancelado     = pyqtSignal()

    def __init__(self, canvas, nombre_capa):
        super().__init__(canvas)
        self.canvas      = canvas
        self.nombre_capa = nombre_capa
        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasPressEvent(self, event):
        if event.button() != Qt.LeftButton:
            self.cancelado.emit()
            return
        punto = self.toMapCoordinates(event.pos())
        try:
            capas = QgsProject.instance().mapLayersByName(self.nombre_capa)
            if not capas:
                raise ValueError(f"Capa '{self.nombre_capa}' no encontrada.")
            capa = capas[0]
            tol  = self._tolerancia(RADIO_BUSQUEDA_MM)
            rect = QgsGeometry.fromPointXY(punto).buffer(tol, 5).boundingBox()
            mejor, dist_min = None, float("inf")
            for f in capa.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
                d = f.geometry().distance(QgsGeometry.fromPointXY(punto))
                if d < dist_min:
                    dist_min, mejor = d, f
            if mejor:
                self.seleccionado.emit(mejor)
            else:
                iface.messageBar().pushMessage(
                    "Simulador",
                    f"No se encontró ningún elemento de '{self.nombre_capa}' en ese punto.",
                    level=1, duration=3)
        except Exception as e:
            iface.messageBar().pushMessage("Simulador", str(e), level=2, duration=4)

    def _tolerancia(self, mm):
        try:
            dpi    = self.canvas.mapSettings().outputDpi()
            escala = self.canvas.mapSettings().scale()
            return mm * escala / (dpi / 25.4)
        except Exception:
            return 50

# ══════════════════════════════════════════════════════════════════════════════
# DIÁLOGO DE CONFIRMACIÓN (MT y APR)
# ══════════════════════════════════════════════════════════════════════════════

class DialogoConfirmacion(QDialog):
    def __init__(self, feature, tipo="MT", parent=None):
        super().__init__(parent or iface.mainWindow())
        self.feature = feature
        self.tipo    = tipo
        self.setWindowTitle("Cambio de estado")
        self.setFixedSize(440, 295)
        self.setStyleSheet(ESTILO_CONFIRMACION)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self._ui()

    def _ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(0)

        # Cabecera
        fila = QHBoxLayout()
        ico  = QLabel("⚠")
        ico.setStyleSheet(
            "font-size: 22px; background: #2d1e00; border-radius: 8px;"
            " padding: 7px 10px; border: 1px solid #78350f;")
        ico.setFixedSize(46, 46)
        ico.setAlignment(Qt.AlignCenter)
        vb = QVBoxLayout()
        vb.setSpacing(2)
        etiq = "Apertura de seccionador MT" if self.tipo == "MT" else "Apertura de APR (BT)"
        lbl1 = QLabel(etiq)
        lbl1.setStyleSheet("font-size: 14px; font-weight: bold; color: #fff;")
        lbl2 = QLabel("Confirme el cambio de estado en la red")
        lbl2.setStyleSheet("font-size: 10px; color: #6b7280;")
        vb.addWidget(lbl1); vb.addWidget(lbl2)
        fila.addWidget(ico); fila.addSpacing(12); fila.addLayout(vb)
        lay.addLayout(fila)
        lay.addSpacing(16)

        # Datos
        frame = QFrame()
        frame.setStyleSheet(
            "background: #0d1117; border: 1px solid #2d3340; border-radius: 8px;")
        grid = QGridLayout(frame)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(7)

        def fila_dato(r, et, val, col="#c9d1d9"):
            le = QLabel(et)
            le.setStyleSheet("color: #4b5563; font-size: 11px; font-family: 'Segoe UI';")
            lv = QLabel(str(val))
            lv.setStyleSheet(
                f"color: {col}; font-size: 11px; font-family: 'Consolas'; font-weight: bold;")
            grid.addWidget(le, r, 0); grid.addWidget(lv, r, 1)

        fila_dato(0, "FID",           self.feature.id())
        fila_dato(1, "Estado actual", "1 — CONECTADO", "#4ade80")
        fila_dato(2, "Nuevo estado",  "2 — ABIERTO",   "#dc2626")
        if self.tipo == "MT":
            fila_dato(3, "Línea MT aguas abajo",
                      self.feature[CAMPO_START_LINE] or "—", "#a5f3fc")
        else:
            fila_dato(3, "Subestación (num_set)",
                      self.feature[CAMPO_APR_NUMSET]  or "—", "#a5f3fc")
            fila_dato(4, "Línea BT aguas abajo",
                      self.feature[CAMPO_APR_LINEABT]  or "—", "#fde68a")

        lay.addWidget(frame)
        lay.addSpacing(18)

        # Botones
        fb = QHBoxLayout(); fb.setSpacing(10)
        bc = QPushButton("Cancelar");          bc.setObjectName("btn_cancelar")
        bc.setFixedHeight(38);                 bc.clicked.connect(self.reject)
        etiq_conf = "⚡  Confirmar apertura MT" if self.tipo == "MT" \
                    else "⚡  Confirmar apertura APR"
        bk = QPushButton(etiq_conf);           bk.setObjectName("btn_confirmar")
        bk.setFixedHeight(38);                 bk.clicked.connect(self.accept)
        fb.addWidget(bc); fb.addWidget(bk, stretch=1)
        lay.addLayout(fb)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dp = e.globalPos() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.LeftButton and hasattr(self, "_dp"):
            self.move(e.globalPos() - self._dp)

# ══════════════════════════════════════════════════════════════════════════════
# WIDGETS DE SOPORTE
# ══════════════════════════════════════════════════════════════════════════════

class TarjetaStat(QFrame):
    def __init__(self, icono, etiqueta, valor="—", color="#dc2626", parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""QFrame {{
            background-color: #151920; border: 1px solid #2d3340;
            border-left: 3px solid {color}; border-radius: 8px; padding: 4px; }}""")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(72)
        lay = QVBoxLayout(self); lay.setContentsMargins(12,10,12,10); lay.setSpacing(2)
        fila = QHBoxLayout()
        li = QLabel(icono); li.setStyleSheet("font-size: 13px; color: #6b7280;")
        le = QLabel(etiqueta.upper())
        le.setStyleSheet(
            "color: #6b7280; font-size: 9px; font-family: 'Segoe UI'; letter-spacing: 1.5px;")
        fila.addWidget(li); fila.addWidget(le); fila.addStretch()
        lay.addLayout(fila)
        self.lbl = QLabel(str(valor))
        self.lbl.setStyleSheet(
            f"color: {color}; font-size: 22px; font-weight: bold;"
            " font-family: 'Consolas', monospace;")
        lay.addWidget(self.lbl)

    def actualizar(self, v): self.lbl.setText(str(v))


class PanelEstado(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setStyleSheet(
            "QFrame { background-color: #0d1117; border-radius: 18px;"
            " border: 1px solid #2d3340; }")
        lay = QHBoxLayout(self); lay.setContentsMargins(14,0,14,0)
        self.dot = QLabel("●"); self.dot.setStyleSheet("color: #4ade80; font-size: 10px;")
        self.lbl = QLabel("SISTEMA EN LÍNEA")
        self.lbl.setStyleSheet(
            "color: #4ade80; font-size: 10px; font-family: 'Segoe UI'; letter-spacing: 2px;")
        lay.addWidget(self.dot); lay.addSpacing(6)
        lay.addWidget(self.lbl); lay.addStretch()

    def set_estado(self, txt, color):
        for w in (self.dot, self.lbl):
            w.setStyleSheet(
                f"color: {color}; font-size: {'10px' if w is self.dot else '10px'};"
                + (" font-family: 'Segoe UI'; letter-spacing: 2px;" if w is self.lbl else ""))
        self.lbl.setText(txt.upper())

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR DE RED — GRAFO BT HÍBRIDO + BFS
# ══════════════════════════════════════════════════════════════════════════════

_renderers_originales      = {}
_seccionadores_modificados = []   # (fid, capa_nombre)


def _capa(nombre):
    cs = QgsProject.instance().mapLayersByName(nombre)
    if not cs:
        raise ValueError(f"Capa no encontrada: '{nombre}'")
    return cs[0]


def _round_coord(v, decimales=1):
    """Redondea coordenada para agrupar nodos por proximidad."""
    factor = 10 ** decimales
    return round(v * factor) / factor


def construir_grafo_bt(ids_bt_activas):
    """
    Construye el grafo de conectividad de la red BT para las líneas activas.

    Estrategia híbrida:
      1. Si la feature tiene campos nodo_inicio / nodo_fin → usa esos valores
         como identificadores de nodo (strings).
      2. Si no, infiere el nodo redondeando las coordenadas de los extremos
         del primer y último vértice de la geometría de la línea.

    Retorna:
      grafo      : dict { nodo: set(nodo_vecino, ...) }
      nodo_de_bt : dict { bt_id: (nodo_ini, nodo_fin) }
    """
    capa_bt   = _capa(CAPA_LINEAS_BT)
    campos    = [f.name() for f in capa_bt.fields()]
    tiene_nodos = (CAMPO_BT_NODO_INI in campos and CAMPO_BT_NODO_FIN in campos)

    grafo      = {}   # nodo → set de nodos vecinos
    nodo_de_bt = {}   # bt_id → (nodo_ini, nodo_fin)

    def agregar_arista(n1, n2):
        grafo.setdefault(n1, set()).add(n2)
        grafo.setdefault(n2, set()).add(n1)

    for f in capa_bt.getFeatures():
        bt_id = f[CAMPO_BT_ID]
        if bt_id not in ids_bt_activas:
            continue

        if tiene_nodos and f[CAMPO_BT_NODO_INI] and f[CAMPO_BT_NODO_FIN]:
            n_ini = str(f[CAMPO_BT_NODO_INI])
            n_fin = str(f[CAMPO_BT_NODO_FIN])
        else:
            # Inferir por geometría: redondear extremos
            geom = f.geometry()
            if geom is None or geom.isEmpty():
                continue
            pts = list(geom.vertices())
            if len(pts) < 2:
                continue
            p0, p1 = pts[0], pts[-1]
            n_ini = f"g_{_round_coord(p0.x())}_{_round_coord(p0.y())}"
            n_fin = f"g_{_round_coord(p1.x())}_{_round_coord(p1.y())}"

        agregar_arista(n_ini, n_fin)
        nodo_de_bt[bt_id] = (n_ini, n_fin)

    return grafo, nodo_de_bt


def bfs_bt(nodos_fuente, grafo):
    """
    BFS desde un conjunto de nodos fuente (subestaciones activas con APR cerrado).
    Retorna el conjunto de nodos alcanzables (energizados).
    """
    visitados = set(nodos_fuente)
    cola      = deque(nodos_fuente)
    while cola:
        nodo = cola.popleft()
        for vecino in grafo.get(nodo, set()):
            if vecino not in visitados:
                visitados.add(vecino)
                cola.append(vecino)
    return visitados


def calcular_afectados(modo_bt_global=MODO_AUTOMATICO):
    """
    Motor principal de propagación. Considera:
      - Seccionadores MT abiertos → corta líneas_mt → subestaciones sin MT
      - APR abiertos → corta líneas_bt directas
      - Topología árbol / malla según campo tipo_red o modo_bt_global

    Retorna:
      afectados  : dict { nombre_capa: set(fids) }
      detalles   : lista de dicts con info de cada apertura
      conteos    : dict { nombre_capa: int }
    """
    afectados = {
        CAPA_LINEA_MT: set(), CAPA_SUBESTACIONES: set(),
        CAPA_APR: set(),
        CAPA_LINEAS_BT: set(), CAPA_ACOMETIDAS_BT: set(), CAPA_MEDIDORES: set(),
    }
    detalles = []

    c_sec  = _capa(CAPA_SECCIONADORES)
    c_lmt  = _capa(CAPA_LINEA_MT)
    c_sub  = _capa(CAPA_SUBESTACIONES)
    c_apr  = _capa(CAPA_APR)
    c_bt   = _capa(CAPA_LINEAS_BT)
    c_acom = _capa(CAPA_ACOMETIDAS_BT)
    c_med  = _capa(CAPA_MEDIDORES)

    # ── 1. Seccionadores MT abiertos ──────────────────────────────────────────
    ids_lmt_afectadas = set()
    for f in c_sec.getFeatures():
        if f[CAMPO_ESTADO_SEC] == ESTADO_ABIERTO:
            sl = f[CAMPO_START_LINE]
            if sl is not None:
                ids_lmt_afectadas.add(sl)
                detalles.append({
                    "tipo": "MT", "sec_fid": f.id(),
                    "start_line": sl, "end_line": f[CAMPO_END_LINE],
                })

    # ── 2. líneas_mt afectadas ────────────────────────────────────────────────
    for f in c_lmt.getFeatures():
        if f[CAMPO_LMT_ID] in ids_lmt_afectadas:
            afectados[CAPA_LINEA_MT].add(f.id())

    # ── 3. Subestaciones: separar activas / inactivas ─────────────────────────
    ids_sub_activas   = set()   # sub.id
    ids_sub_inactivas = set()   # sub.id
    fids_sub_inact    = set()   # fid para resaltado

    for f in c_sub.getFeatures():
        sid = f[CAMPO_SUB_ID]
        if f[CAMPO_SUB_LINEAMT] in ids_lmt_afectadas:
            ids_sub_inactivas.add(sid)
            fids_sub_inact.add(f.id())
        else:
            ids_sub_activas.add(sid)
    afectados[CAPA_SUBESTACIONES] = fids_sub_inact

    # ── 4. APR abiertos ───────────────────────────────────────────────────────
    ids_bt_cortadas_apr = set()   # bt.id cortadas por APR abierto
    ids_bt_fuente_act   = set()   # bt.id con APR cerrado desde sub activa
    nodos_fuente_bfs    = set()   # nodos del grafo energizados por sub activa

    for f in c_apr.getFeatures():
        ns   = f[CAMPO_APR_NUMSET]
        lbt  = f[CAMPO_APR_LINEABT]
        est  = f[CAMPO_APR_ESTADO]

        if est == ESTADO_ABIERTO:
            # APR abierto → corta su línea BT aguas abajo
            if lbt is not None:
                ids_bt_cortadas_apr.add(lbt)
            afectados[CAPA_APR].add(f.id())
            detalles.append({
                "tipo": "APR", "sec_fid": f.id(),
                "num_set": ns, "linea_bt": lbt,
            })
        else:
            # APR cerrado desde sub activa → fuente BFS
            if ns in ids_sub_activas and lbt is not None:
                ids_bt_fuente_act.add(lbt)

    # ── 5. Clasificar líneas_bt y construir listas de trabajo ─────────────────
    campos_bt = [fld.name() for fld in c_bt.fields()]
    tiene_tipo_red = CAMPO_BT_TIPO_RED in campos_bt

    ids_bt_arbol        = set()   # bt.id a propagar en modo árbol
    ids_bt_malla_todas  = set()   # bt.id participantes del grafo mallado
    ids_bt_fuente_malla = set()   # bt.id que son nodos fuente en el grafo
    fid_de_bt           = {}      # bt.id → fid (para resaltado)

    for f in c_bt.getFeatures():
        bid = f[CAMPO_BT_ID]
        fid_de_bt[bid] = f.id()

        # Determinar modo efectivo de este tramo
        if tiene_tipo_red and f[CAMPO_BT_TIPO_RED] in (MODO_ARBOL, MODO_MALLA):
            modo_efectivo = f[CAMPO_BT_TIPO_RED]
        elif modo_bt_global in (MODO_ARBOL, MODO_MALLA):
            modo_efectivo = modo_bt_global
        else:
            # MODO_AUTOMATICO sin campo → asumir árbol por defecto
            modo_efectivo = MODO_ARBOL

        if modo_efectivo == MODO_MALLA:
            ids_bt_malla_todas.add(bid)
            if bid in ids_bt_fuente_act:
                ids_bt_fuente_malla.add(bid)
        else:
            ids_bt_arbol.add(bid)

    # ── 6a. Propagación ÁRBOL ─────────────────────────────────────────────────
    # Una línea árbol está afectada si:
    #   a) Su APR fue abierto directamente, O
    #   b) Pertenece a una subestación inactiva (sin MT)
    # Para árbol simple usamos la FK directa (num_set / APR)
    # Re-leemos APR para obtener la asociación bt→sub
    bt_a_sub = {}   # bt.id → sub.id
    for f in c_apr.getFeatures():
        lbt = f[CAMPO_APR_LINEABT]
        ns  = f[CAMPO_APR_NUMSET]
        if lbt is not None:
            bt_a_sub[lbt] = ns

    ids_bt_afectadas_arbol = set()
    for bid in ids_bt_arbol:
        sub_id = bt_a_sub.get(bid)
        if bid in ids_bt_cortadas_apr:
            ids_bt_afectadas_arbol.add(bid)
        elif sub_id in ids_sub_inactivas:
            ids_bt_afectadas_arbol.add(bid)

    # ── 6b. Propagación MALLA (BFS) ───────────────────────────────────────────
    ids_bt_afectadas_malla = set()
    if ids_bt_malla_todas:
        # Construir grafo solo con las líneas malla
        grafo, nodo_de_bt = construir_grafo_bt(ids_bt_malla_todas)

        # Nodos fuente = extremos de BT con APR cerrado desde sub activa,
        #                excluyendo las cortadas por APR abierto
        nodos_inicio = set()
        for bid in ids_bt_fuente_malla:
            if bid not in ids_bt_cortadas_apr and bid in nodo_de_bt:
                n_ini, n_fin = nodo_de_bt[bid]
                nodos_inicio.add(n_ini)
                nodos_inicio.add(n_fin)

        nodos_energizados = bfs_bt(nodos_inicio, grafo)

        # Una línea malla está afectada si NINGUNO de sus extremos es alcanzable
        for bid in ids_bt_malla_todas:
            if bid in nodo_de_bt:
                n_ini, n_fin = nodo_de_bt[bid]
                if n_ini not in nodos_energizados and n_fin not in nodos_energizados:
                    ids_bt_afectadas_malla.add(bid)
            else:
                # Sin geometría válida → tratar como afectada por precaución
                ids_bt_afectadas_malla.add(bid)

    # ── 7. Unir afectadas BT y marcar fids ────────────────────────────────────
    ids_bt_afectadas = ids_bt_afectadas_arbol | ids_bt_afectadas_malla
    for bid in ids_bt_afectadas:
        if bid in fid_de_bt:
            afectados[CAPA_LINEAS_BT].add(fid_de_bt[bid])

    # ── 8. Acometidas afectadas ───────────────────────────────────────────────
    ids_acom = set()
    fid_acom = {}
    for f in c_acom.getFeatures():
        aid = f[CAMPO_ACOM_ID]
        fid_acom[aid] = f.id()
        if f[CAMPO_ACOM_LINEABT] in ids_bt_afectadas:
            ids_acom.add(aid)
            afectados[CAPA_ACOMETIDAS_BT].add(f.id())

    # ── 9. Medidores afectados ────────────────────────────────────────────────
    for f in c_med.getFeatures():
        if f[CAMPO_MED_IDACOMET] in ids_acom:
            afectados[CAPA_MEDIDORES].add(f.id())

    conteos = {k: len(v) for k, v in afectados.items()}
    return afectados, detalles, conteos


def aplicar_resaltado(afectados):
    global _renderers_originales
    for nombre, fids in afectados.items():
        try:
            capa = _capa(nombre)
            if nombre not in _renderers_originales:
                _renderers_originales[nombre] = capa.renderer().clone()
            if not fids:
                continue

            # APR usa naranja, el resto rojo
            color = COLOR_AFECTADO_APR if nombre == CAPA_APR else COLOR_AFECTADO
            lista = ", ".join(str(f) for f in fids)
            expr  = f"$id IN ({lista})"

            sym_af = QgsSymbol.defaultSymbol(capa.geometryType())
            sym_af.setColor(color)
            if capa.geometryType() == 1:
                sym_af.setWidth(ANCHO_LINEA_AFECTADA)
            elif capa.geometryType() == 0:
                sym_af.setSize(TAMANO_PUNTO_AFECTADO)

            sym_ok = QgsSymbol.defaultSymbol(capa.geometryType())
            sym_ok.setColor(COLOR_NORMAL)

            r_af = QgsRuleBasedRenderer.Rule(sym_af)
            r_af.setFilterExpression(expr); r_af.setLabel("Fuera de servicio")
            r_ok = QgsRuleBasedRenderer.Rule(sym_ok)
            r_ok.setFilterExpression(f"NOT ({expr})"); r_ok.setLabel("En servicio")
            raiz = QgsRuleBasedRenderer.Rule(None)
            raiz.appendChild(r_af); raiz.appendChild(r_ok)
            capa.setRenderer(QgsRuleBasedRenderer(raiz))
            capa.triggerRepaint()
        except Exception:
            pass
    iface.mapCanvas().refresh()


def asegurar_campo_tipo_red():
    """Crea el campo tipo_red en líneas_bt si no existe."""
    try:
        capa   = _capa(CAPA_LINEAS_BT)
        campos = [f.name() for f in capa.fields()]
        if CAMPO_BT_TIPO_RED not in campos:
            capa.startEditing()
            capa.addAttribute(QgsField(CAMPO_BT_TIPO_RED, QVariant.String, len=10))
            capa.commitChanges()
            return True   # se creó ahora
        return False      # ya existía
    except Exception:
        return False


def cambiar_estado(nombre_capa, fid, campo_estado, nuevo_estado):
    global _seccionadores_modificados
    capa    = _capa(nombre_capa)
    idx     = capa.fields().indexFromName(campo_estado)
    if idx < 0:
        raise ValueError(f"Campo '{campo_estado}' no encontrado en '{nombre_capa}'.")
    capa.startEditing()
    capa.changeAttributeValue(fid, idx, nuevo_estado)
    capa.commitChanges()
    capa.triggerRepaint()
    if nuevo_estado == ESTADO_ABIERTO:
        _seccionadores_modificados.append((fid, nombre_capa, campo_estado))
    else:
        _seccionadores_modificados = [
            t for t in _seccionadores_modificados
            if not (t[0] == fid and t[1] == nombre_capa)
        ]


def restaurar_todo():
    global _renderers_originales, _seccionadores_modificados
    for fid, nom, campo in list(_seccionadores_modificados):
        try:
            cambiar_estado(nom, fid, campo, ESTADO_CONECTADO)
        except Exception:
            pass
    _seccionadores_modificados.clear()
    for nombre, renderer in _renderers_originales.items():
        cs = QgsProject.instance().mapLayersByName(nombre)
        if cs:
            cs[0].setRenderer(renderer.clone())
            cs[0].triggerRepaint()
    _renderers_originales.clear()
    iface.mapCanvas().refresh()

# ══════════════════════════════════════════════════════════════════════════════
# DIÁLOGO PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class DialogoSimulador(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.setWindowTitle("Simulador de Red Eléctrica v3")
        self.setMinimumSize(820, 720)
        self.resize(920, 780)
        self.setStyleSheet(ESTILO_BASE)
        self._herramienta      = None
        self._herramienta_ant  = None
        self._modo_seleccion   = None   # 'MT' o 'APR'
        self._construir_ui()
        self._verificar_campo_tipo_red()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _construir_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        root.addLayout(self._cabecera())
        root.addWidget(self._sep())
        root.addWidget(self._panel_seleccion())
        root.addWidget(self._panel_modo_bt())
        root.addWidget(self._sep())
        root.addLayout(self._fila_botones())

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(4)
        root.addWidget(self.progress)

        root.addWidget(self._grupo_stats())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_log(),   "  📋  LOG DE EVENTOS  ")
        self.tabs.addTab(self._tab_tabla(), "  📊  DETALLE POR CAPA  ")
        root.addWidget(self.tabs, stretch=1)
        root.addLayout(self._pie())

    def _sep(self):
        s = QFrame(); s.setObjectName("separador")
        s.setFrameShape(QFrame.HLine); return s

    def _cabecera(self):
        lay = QHBoxLayout()
        ico = QLabel("⚡")
        ico.setStyleSheet(
            "font-size: 26px; background-color: #1e2530; border-radius: 10px;"
            " padding: 6px 10px; border: 1px solid #2d3340;")
        ico.setFixedSize(50, 50); ico.setAlignment(Qt.AlignCenter)
        lay.addWidget(ico); lay.addSpacing(12)
        vb = QVBoxLayout(); vb.setSpacing(2)
        t = QLabel("SIMULADOR DE RED ELÉCTRICA v3")
        t.setStyleSheet(
            "color: #fff; font-size: 15px; font-weight: bold;"
            " font-family: 'Segoe UI'; letter-spacing: 1px;")
        s = QLabel("MT · APR · Árbol / Malla BFS · QGIS 3.40")
        s.setStyleSheet(
            "color: #8a9bb0; font-size: 10px; font-family: 'Segoe UI';"
            " letter-spacing: 1.5px;")
        vb.addWidget(t); vb.addWidget(s)
        lay.addLayout(vb); lay.addStretch()
        self.panel_estado = PanelEstado()
        lay.addWidget(self.panel_estado)
        return lay

    def _panel_seleccion(self):
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background-color: #1a2235; border: 1px solid #1e3a5f;"
            " border-radius: 8px; }")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(14, 10, 14, 10); lay.setSpacing(10)

        ico = QLabel("🖱"); ico.setStyleSheet("font-size: 18px;")
        lay.addWidget(ico)

        vb = QVBoxLayout(); vb.setSpacing(1)
        lb1 = QLabel("Seleccionar dispositivo en el mapa")
        lb1.setStyleSheet(
            "color: #93c5fd; font-size: 12px; font-weight: bold;"
            " font-family: 'Segoe UI';")
        lb2 = QLabel("Seleccione el tipo de dispositivo y haga clic sobre él en el mapa")
        lb2.setStyleSheet(
            "color: #4b6a8a; font-size: 10px; font-family: 'Segoe UI';")
        vb.addWidget(lb1); vb.addWidget(lb2)
        lay.addLayout(vb, stretch=1)

        self.btn_sec = QPushButton("⚡  Seccionador MT")
        self.btn_sec.setObjectName("btn_sec")
        self.btn_sec.setFixedHeight(36); self.btn_sec.setCheckable(True)
        self.btn_sec.clicked.connect(lambda: self._toggle_seleccion("MT"))

        self.btn_apr = QPushButton("🔌  APR (BT)")
        self.btn_apr.setObjectName("btn_apr")
        self.btn_apr.setFixedHeight(36); self.btn_apr.setCheckable(True)
        self.btn_apr.clicked.connect(lambda: self._toggle_seleccion("APR"))

        lay.addWidget(self.btn_sec)
        lay.addWidget(self.btn_apr)
        return frame

    def _panel_modo_bt(self):
        """Panel de configuración del modo de propagación BT."""
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background-color: #12151c; border: 1px solid #2d3340;"
            " border-radius: 8px; }")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(14, 10, 14, 10); lay.setSpacing(16)

        ico = QLabel("🕸"); ico.setStyleSheet("font-size: 16px;")
        lay.addWidget(ico)

        lbl = QLabel("Modo BT:")
        lbl.setStyleSheet(
            "color: #6b7280; font-size: 11px; font-family: 'Segoe UI';"
            " font-weight: bold;")
        lay.addWidget(lbl)

        self.bg_modo = QButtonGroup(self)
        opciones = [
            ("auto",  "Automático (usa campo tipo_red)"),
            ("arbol", "Todo árbol"),
            ("malla", "Todo malla (BFS)"),
        ]
        for val, texto in opciones:
            rb = QRadioButton(texto)
            if val == "auto":
                rb.setChecked(True)
            self.bg_modo.addButton(rb)
            rb.setProperty("modo", val)
            lay.addWidget(rb)

        lay.addStretch()

        # Indicador de campo tipo_red
        self.lbl_tipo_red = QLabel("▸ campo tipo_red: verificando…")
        self.lbl_tipo_red.setStyleSheet(
            "color: #6b7280; font-size: 10px; font-family: 'Consolas';")
        lay.addWidget(self.lbl_tipo_red)
        return frame

    def _fila_botones(self):
        lay = QHBoxLayout(); lay.setSpacing(10)
        self.btn_simular = QPushButton("▶  EJECUTAR SIMULACIÓN")
        self.btn_simular.setObjectName("btn_simular")
        self.btn_simular.setFixedHeight(42)
        self.btn_simular.clicked.connect(self._ejecutar)
        self.btn_restaurar = QPushButton("↺  RESTAURAR TODO")
        self.btn_restaurar.setObjectName("btn_restaurar")
        self.btn_restaurar.setFixedHeight(42)
        self.btn_restaurar.clicked.connect(self._restaurar)
        lay.addWidget(self.btn_simular, stretch=2)
        lay.addWidget(self.btn_restaurar, stretch=1)
        return lay

    def _grupo_stats(self):
        group = QGroupBox("RESUMEN DE ELEMENTOS AFECTADOS")
        grid  = QGridLayout(group)
        grid.setSpacing(8); grid.setContentsMargins(12, 18, 12, 12)

        self.stat_sec  = TarjetaStat("⚠",  "Secc. MT abiertos",    color="#f97316")
        self.stat_apr  = TarjetaStat("🔌", "APR abiertos",          color="#f59e0b")
        self.stat_lmt  = TarjetaStat("〰", "Líneas MT",             color="#dc2626")
        self.stat_sub  = TarjetaStat("🏠", "Subestaciones",         color="#dc2626")
        self.stat_bt   = TarjetaStat("〰", "Líneas BT",             color="#ef4444")
        self.stat_acom = TarjetaStat("〰", "Acometidas",            color="#f87171")
        self.stat_med  = TarjetaStat("🔌", "Medidores sin servicio",color="#fca5a5")

        grid.addWidget(self.stat_sec,  0, 0)
        grid.addWidget(self.stat_apr,  0, 1)
        grid.addWidget(self.stat_lmt,  0, 2)
        grid.addWidget(self.stat_sub,  1, 0)
        grid.addWidget(self.stat_bt,   1, 1)
        grid.addWidget(self.stat_acom, 1, 2)
        grid.addWidget(self.stat_med,  2, 0, 1, 3)   # ocupa toda la fila
        return group

    def _tab_log(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0); lay.setSpacing(6)
        self.log = QTextEdit()
        self.log.setObjectName("log_consola"); self.log.setReadOnly(True)
        lay.addWidget(self.log)
        fila = QHBoxLayout()
        bl = QPushButton("🗑  Limpiar log"); bl.setObjectName("btn_secundario")
        bl.setFixedHeight(30); bl.clicked.connect(self.log.clear)
        fila.addStretch(); fila.addWidget(bl); lay.addLayout(fila)
        return w

    def _tab_tabla(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(["CAPA", "AFECTADOS", "ESTADO"])
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setShowGrid(False)
        lay.addWidget(self.tabla)
        return w

    def _pie(self):
        lay = QHBoxLayout()
        self.lbl_ts = QLabel("—")
        self.lbl_ts.setStyleSheet(
            "color: #4b5563; font-size: 10px; font-family: 'Consolas', monospace;")
        lay.addWidget(self.lbl_ts); lay.addStretch()
        bc = QPushButton("Cerrar"); bc.setObjectName("btn_secundario")
        bc.setFixedHeight(32); bc.clicked.connect(self._al_cerrar)
        lay.addWidget(bc)
        return lay

    # ── Lógica ────────────────────────────────────────────────────────────────

    def _log(self, msg, tipo="info"):
        c = {"info":"#c9d1d9","ok":"#4ade80","warn":"#fb923c","error":"#f87171",
             "titulo":"#60a5fa","sep":"#2d3340","dato":"#a5f3fc","apr":"#fde68a"}
        color = c.get(tipo, "#c9d1d9")
        ts    = QDateTime.currentDateTime().toString("hh:mm:ss")
        ts_h  = f'<span style="color:#4b5563;">[{ts}]</span>'
        if tipo == "sep":
            self.log.append(f'<span style="color:{color};">{"─"*52}</span>')
        else:
            self.log.append(f'{ts_h} <span style="color:{color};">{msg}</span>')
        self.log.verticalScrollBar().setValue(
            self.log.verticalScrollBar().maximum())

    def _verificar_campo_tipo_red(self):
        try:
            capa   = _capa(CAPA_LINEAS_BT)
            campos = [f.name() for f in capa.fields()]
            if CAMPO_BT_TIPO_RED in campos:
                self.lbl_tipo_red.setText("▸ campo tipo_red: ✓ existe")
                self.lbl_tipo_red.setStyleSheet(
                    "color: #4ade80; font-size: 10px; font-family: 'Consolas';")
            else:
                self.lbl_tipo_red.setText("▸ campo tipo_red: no existe (se creará al simular)")
                self.lbl_tipo_red.setStyleSheet(
                    "color: #fb923c; font-size: 10px; font-family: 'Consolas';")
        except Exception:
            self.lbl_tipo_red.setText("▸ campo tipo_red: capa no cargada")
            self.lbl_tipo_red.setStyleSheet(
                "color: #f87171; font-size: 10px; font-family: 'Consolas';")

    def _modo_bt_seleccionado(self):
        for btn in self.bg_modo.buttons():
            if btn.isChecked():
                return btn.property("modo")
        return MODO_AUTOMATICO

    def _toggle_seleccion(self, tipo):
        """Activa / desactiva la herramienta de selección para MT o APR."""
        canvas = iface.mapCanvas()

        # Si se hace clic en el botón ya activo → cancelar
        if self._modo_seleccion == tipo:
            self._cancelar_seleccion()
            return

        # Cancelar cualquier selección activa antes de empezar la nueva
        self._cancelar_seleccion(silencioso=True)

        self._modo_seleccion = tipo
        nombre_capa = CAPA_SECCIONADORES if tipo == "MT" else CAPA_APR

        self.btn_sec.setChecked(tipo == "MT")
        self.btn_apr.setChecked(tipo == "APR")

        self._log("", "sep")
        self._log(
            f"🖱  Modo selección activo: {'Seccionador MT' if tipo=='MT' else 'APR (BT)'}."
            " Haga clic sobre el dispositivo en el mapa.", "titulo")

        self._herramienta_ant = canvas.mapTool()
        herr = HerramientaSeleccion(canvas, nombre_capa)
        herr.seleccionado.connect(self._al_seleccionar)
        herr.cancelado.connect(self._cancelar_seleccion)
        self._herramienta = herr
        canvas.setMapTool(herr)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.show()

    def _cancelar_seleccion(self, silencioso=False):
        canvas = iface.mapCanvas()
        if self._herramienta_ant:
            canvas.setMapTool(self._herramienta_ant)
        self._herramienta     = None
        self._herramienta_ant = None
        self._modo_seleccion  = None
        self.btn_sec.setChecked(False)
        self.btn_apr.setChecked(False)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()
        if not silencioso:
            self._log("⊘  Selección cancelada.", "info")

    def _al_seleccionar(self, feature):
        tipo = self._modo_seleccion or "MT"
        self._cancelar_seleccion(silencioso=True)

        campo_estado = CAMPO_ESTADO_SEC if tipo == "MT" else CAMPO_APR_ESTADO
        if feature[campo_estado] == ESTADO_ABIERTO:
            self._log(
                f"ℹ  El dispositivo FID={feature.id()} ya está ABIERTO (estado=2).",
                "warn")
            return

        dlg = DialogoConfirmacion(feature, tipo=tipo, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            nombre_capa = CAPA_SECCIONADORES if tipo == "MT" else CAPA_APR
            self._log("", "sep")
            self._log(
                f"{'⚡' if tipo=='MT' else '🔌'}  "
                f"{'Seccionador MT' if tipo=='MT' else 'APR'} "
                f"FID={feature.id()} — estado 1 → 2", "warn" if tipo=="MT" else "apr")
            try:
                cambiar_estado(nombre_capa, feature.id(), campo_estado, ESTADO_ABIERTO)
                self._log("✅  Campo 'estado' actualizado en la capa.", "ok")
            except Exception as e:
                self._log(f"❌  Error al editar: {e}", "error"); return
            self._log("", "sep")
            self._log("▶  Ejecutando simulación automática…", "titulo")
            self._ejecutar()
        else:
            self._log("⊘  Cambio de estado cancelado.", "info")

    def _ejecutar(self):
        self.btn_simular.setEnabled(False)
        self.progress.setVisible(True)
        self.panel_estado.set_estado("Procesando…", "#facc15")
        QApplication.processEvents()

        # Crear campo tipo_red si no existe
        creado = asegurar_campo_tipo_red()
        if creado:
            self._log(
                "ℹ  Se creó el campo 'tipo_red' en líneas_bt. "
                "Poblarlo con 'arbol' o 'malla' usando la calculadora de campos de QGIS.",
                "warn")
            self._verificar_campo_tipo_red()

        modo = self._modo_bt_seleccionado()
        self._log(
            f"ℹ  Modo BT: {'Automático (campo tipo_red)' if modo==MODO_AUTOMATICO else modo.upper()}",
            "info")

        try:
            afectados, detalles, conteos = calcular_afectados(modo_bt_global=modo)

            n_sec = sum(1 for d in detalles if d["tipo"] == "MT")
            n_apr = sum(1 for d in detalles if d["tipo"] == "APR")

            if n_sec == 0 and n_apr == 0:
                self._log("ℹ  Sin seccionadores ni APR abiertos. Red en servicio.", "warn")
                self.panel_estado.set_estado("Sin cortes activos", "#4ade80")
                self._actualizar_stats(0, 0, {k: 0 for k in conteos})
                self._actualizar_tabla({k: 0 for k in conteos})
            else:
                if n_sec:
                    self._log(f"⚠  Seccionadores MT abiertos: {n_sec}", "warn")
                    for d in detalles:
                        if d["tipo"] == "MT":
                            self._log(
                                f"   • Sec MT FID={d['sec_fid']} │ "
                                f"start_line={d['start_line']} │ end_line={d['end_line']}",
                                "dato")
                if n_apr:
                    self._log(f"🔌  APR abiertos: {n_apr}", "apr")
                    for d in detalles:
                        if d["tipo"] == "APR":
                            self._log(
                                f"   • APR FID={d['sec_fid']} │ "
                                f"num_set={d['num_set']} │ línea_bt={d['linea_bt']}",
                                "dato")

                self._log("", "sep")
                aplicar_resaltado(afectados)

                iconos = {
                    CAPA_LINEA_MT:      ("〰 ", "Líneas MT"),
                    CAPA_SUBESTACIONES: ("🏠 ", "Subestaciones"),
                    CAPA_APR:           ("🔌 ", "APR"),
                    CAPA_LINEAS_BT:     ("〰 ", "Líneas BT"),
                    CAPA_ACOMETIDAS_BT: ("〰 ", "Acometidas BT"),
                    CAPA_MEDIDORES:     ("⚡ ", "Medidores"),
                }
                self._log("📊  ELEMENTOS AFECTADOS:", "titulo")
                for capa, (ic, nom) in iconos.items():
                    n    = conteos.get(capa, 0)
                    tipo = "error" if n > 0 else "ok"
                    marca = "✗" if n > 0 else "✓"
                    self._log(f"   {marca}  {ic}{nom:<20}  {n:>4} elemento(s)", tipo)

                med = conteos.get(CAPA_MEDIDORES, 0)
                self._log("", "sep")
                if med > 0:
                    self._log(f"🔴  USUARIOS SIN SERVICIO: {med} medidores", "error")
                self._log("✅  Simulación completada. Mapa actualizado.", "ok")
                self.panel_estado.set_estado(
                    f"CORTE ACTIVO — {med} medidores", "#dc2626")
                self._actualizar_stats(n_sec, n_apr, conteos)
                self._actualizar_tabla(conteos)

        except ValueError as e:
            self._log(f"❌  {e}", "error")
            self.panel_estado.set_estado("Error — ver log", "#f87171")
        except Exception as e:
            self._log(f"❌  Error inesperado: {e}", "error")
            import traceback; self._log(traceback.format_exc(), "error")
        finally:
            self.progress.setVisible(False)
            self.btn_simular.setEnabled(True)
            ts = QDateTime.currentDateTime().toString("dd/MM/yyyy  hh:mm:ss")
            self.lbl_ts.setText(f"Última ejecución: {ts}")

    def _restaurar(self):
        self.progress.setVisible(True)
        QApplication.processEvents()
        try:
            restaurar_todo()
            self._log("", "sep")
            self._log("↺  Estados revertidos y colores restaurados.", "ok")
            self.panel_estado.set_estado("SISTEMA EN LÍNEA", "#4ade80")
            cero = {k: 0 for k in [
                CAPA_LINEA_MT, CAPA_SUBESTACIONES, CAPA_APR,
                CAPA_LINEAS_BT, CAPA_ACOMETIDAS_BT, CAPA_MEDIDORES]}
            self._actualizar_stats(0, 0, cero)
            self._actualizar_tabla(cero)
        except Exception as e:
            self._log(f"❌  {e}", "error")
        finally:
            self.progress.setVisible(False)

    def _actualizar_stats(self, n_sec, n_apr, conteos):
        self.stat_sec.actualizar(n_sec)
        self.stat_apr.actualizar(n_apr)
        self.stat_lmt.actualizar(conteos.get(CAPA_LINEA_MT,      "—"))
        self.stat_sub.actualizar(conteos.get(CAPA_SUBESTACIONES, "—"))
        self.stat_bt.actualizar( conteos.get(CAPA_LINEAS_BT,     "—"))
        self.stat_acom.actualizar(conteos.get(CAPA_ACOMETIDAS_BT,"—"))
        self.stat_med.actualizar( conteos.get(CAPA_MEDIDORES,     "—"))

    def _actualizar_tabla(self, conteos):
        capas_info = [
            ("Seccionadores MT (abiertos)", None),
            ("APR (abiertos)",              None),
            ("Líneas de Media Tensión",     CAPA_LINEA_MT),
            ("Subestaciones",               CAPA_SUBESTACIONES),
            ("APR afectados",               CAPA_APR),
            ("Líneas BT",                   CAPA_LINEAS_BT),
            ("Acometidas BT",               CAPA_ACOMETIDAS_BT),
            ("Medidores",                   CAPA_MEDIDORES),
        ]
        self.tabla.setRowCount(0)
        for nombre_vis, clave in capas_info:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            i_n = QTableWidgetItem(nombre_vis)
            i_n.setForeground(QColor("#c9d1d9"))
            i_n.setFlags(i_n.flags() & ~Qt.ItemIsEditable)

            n = conteos.get(clave, 0) if clave else "—"
            i_c = QTableWidgetItem(str(n))
            i_c.setTextAlignment(Qt.AlignCenter)
            i_c.setFlags(i_c.flags() & ~Qt.ItemIsEditable)

            if isinstance(n, int) and n > 0:
                i_c.setForeground(QColor("#f87171"))
                et, ec = "⛔ Afectado",  "#f87171"
            elif clave is None:
                et, ec = "—",            "#4b5563"
            else:
                i_c.setForeground(QColor("#4ade80"))
                et, ec = "✅ Operativo", "#4ade80"

            i_e = QTableWidgetItem(et)
            i_e.setForeground(QColor(ec))
            i_e.setTextAlignment(Qt.AlignCenter)
            i_e.setFlags(i_e.flags() & ~Qt.ItemIsEditable)

            self.tabla.setItem(fila, 0, i_n)
            self.tabla.setItem(fila, 1, i_c)
            self.tabla.setItem(fila, 2, i_e)
            self.tabla.setRowHeight(fila, 32)

    def _al_cerrar(self):
        self._cancelar_seleccion(silencioso=True); self.close()

    def closeEvent(self, e):
        self._cancelar_seleccion(silencioso=True); super().closeEvent(e)

# ══════════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
# ══════════════════════════════════════════════════════════════════════════════

if hasattr(qgis.utils, '_simulador_v3') and qgis.utils._simulador_v3 is not None:
    try:
        qgis.utils._simulador_v3.close()
    except Exception:
        pass

dialogo = DialogoSimulador()
qgis.utils._simulador_v3 = dialogo
dialogo.show()
