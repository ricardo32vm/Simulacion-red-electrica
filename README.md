# ⚡ Simulación de Red Eléctrica — Script QGIS

> Script para QGIS que simula la propagación de fallas en redes eléctricas de distribución, con motor híbrido árbol/malla y selección interactiva de dispositivos por clic en el mapa.  
> Desarrollado para la cooperativa eléctrica de la zona Colonia Caroya / Jesús María, Córdoba, Argentina.

---

## 📋 Descripción

`simulacion_red_electrica_v3.py` recorre la jerarquía completa de una red de distribución y determina qué elementos quedan sin servicio al abrir un seccionador MT o un APR (seccionador BT). Calcula la propagación tanto en redes radiales (árbol) como malladas (BFS) y resalta en el mapa los elementos afectados.

**Características principales:**
- Motor de propagación híbrido: árbol clásico O(N) + BFS para redes malladas
- Nivel APR (seccionadores BT) entre subestaciones y líneas BT
- Grafo de conectividad BT híbrido: lee `nodo_inicio` / `nodo_fin` si existen, o infiere topología por proximidad geométrica
- Campo `tipo_red` configurable por tramo (`arbol` / `malla`), con fallback global seleccionable en la UI
- Selección interactiva de APR y seccionadores MT por clic en el mapa
- Interfaz gráfica integrada (diálogo Qt con tema oscuro) con tabla de resultados y barra de progreso
- Renderizado por reglas que resalta elementos afectados (rojo para cortes MT, naranja para cortes de APR)

---

## 🌳 Jerarquía de la red

```
seccionadores MT  [estado, start_line]
    └── línea_mt  [id]
            └── subestaciones  [linea_mt → línea_mt.id]
                    └── APR  [num_set → sub.id, línea_bt → bt.id]
                            ├── [árbol]  líneas_bt → acometidas_bt → medidores
                            └── [malla]  BFS(grafo_bt) → acometidas_bt → medidores
```

---

## 🛠️ Requisitos

| Requisito | Versión mínima |
|---|---|
| QGIS | 3.40 |
| Python | 3.9+ |

> No requiere dependencias externas — usa únicamente las APIs de QGIS (`qgis.core`, `qgis.gui`, `qgis.PyQt`).

---

## 📥 Capas requeridas en el proyecto QGIS

| Capa | Campos clave |
|---|---|
| `seccionadores` | `estado`, `start_line`, `end_line` |
| `apr` | `estado` (1=cerrado, 2=abierto), `num_set`, `línea_bt` |
| `línea_mt` | `id` |
| `subestaciones` | `id`, `linea_mt` |
| `líneas_bt` | `id`, `tipo_red`, `nodo_inicio` *(opcional)*, `nodo_fin` *(opcional)* |
| `acometidas_bt` | `id`, `línea_bt` |
| `medidores` | `id_acomet` |

> El CRS de trabajo asumido es POSGAR98 (la tolerancia geométrica de nodos está en metros).

---

## 🚀 Uso

1. Cargar en QGIS el proyecto con todas las capas de la red listadas arriba
2. Abrir la **Consola de Python** de QGIS (`Complementos → Consola de Python`)
3. Abrir el editor de scripts y cargar `simulacion_red_electrica_v3.py`
4. Ejecutar el script → se abre el diálogo del simulador
5. Seleccionar un seccionador MT o un APR por clic en el mapa
6. Ejecutar la simulación → se resaltan los elementos afectados y se listan en la tabla de resultados

### Modos de propagación BT

| Modo | Descripción |
|---|---|
| `arbol` | Propagación radial clásica O(N) |
| `malla` | Recorrido BFS sobre el grafo de conectividad |
| `auto` | Lee el campo `tipo_red` de cada tramo BT |

---

## 🔗 Herramientas relacionadas

| Repo | Descripción |
|---|---|
| [`crear_red_electrica`](https://github.com/ricardo32vm/crear-red-electrica) | Trazado de red MT |
| [`red_bt`](https://github.com/ricardo32vm/crear-red-bt) | Trazado de red BT con snapping |
| [`electric_network_tools`](https://github.com/ricardo32vm/electric-network-tools) | Topología y acometidas |

---

## 🗺️ Contexto de aplicación

Herramienta desarrollada para el análisis de continuidad de servicio en el área de concesión de la cooperativa eléctrica de **Colonia Caroya / Jesús María**, Provincia de Córdoba, Argentina.

---

## 🔭 Próximos pasos

Esta es la versión como script. Una futura iteración puede empaquetarlo como plugin QGIS (con `__init__.py`, `metadata.txt` y un wrapper que invoque el diálogo) para tener un botón en la barra de herramientas sin necesidad de ejecutar el script manualmente.

---

## 👨‍💻 Autor

**Ing. Ricardo Luis Castro**  
Docente-investigador — UTN Facultad Regional Villa María  
📍 Villa María, Córdoba, Argentina

[![YouTube](https://img.shields.io/badge/YouTube-Canal_GIS-red?logo=youtube)](https://youtube.com/@tucanal)
[![GitHub](https://img.shields.io/badge/GitHub-ricardo32vm-black?logo=github)](https://github.com/ricardo32vm)

---

## 📄 Licencia

[GPL v2](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html)
