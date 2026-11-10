"""Sistema de turnos para consulta medica (web.py + SQLite).
Uso:  python app.py      -> abre http://localhost:8080
Partes (una por integrante): 1 Config y BD | 2 Pacientes | 3 Filas y medicos | 4 Rutas
Las vistas (HTML) estan en la carpeta views/
"""
import os
import sqlite3
from datetime import datetime

import web

# ===== PARTE 1: CONFIGURACION Y BASE DE DATOS =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "hospital.db")

# nivel: (nombre, fila a la que va, minutos estimados por defecto)
URGENCIAS = {1: ("Nivel 1 - Critica", "prioritaria", 30), 2: ("Nivel 2 - Urgente", "prioritaria", 25),
             3: ("Nivel 3 - Semiurgente", "prioritaria", 20), 4: ("Nivel 4 - No urgente", "general", 15)}
MEDICOS = [("Dra. Ana Torres", "Medicina General"), ("Dr. Luis Ramirez", "Medicina General"),
           ("Dra. Marta Vega", "Urgencias")]
ESTADOS = {"espera": "En espera", "en_consulta": "En consulta", "atendido": "Atendido", "cancelado": "Cancelado"}

# Carga las plantillas HTML de views/ (layout.html es la base de todas)
render = web.template.render(os.path.join(BASE_DIR, "views"), base="layout",
                             globals={"URGENCIAS": URGENCIAS, "ESTADOS": ESTADOS, "sorted": sorted, "str": str})


def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # permite usar fila["nombre"]
    return conn


def consultar(sql, datos=()):  # SELECT: devuelve una lista de objetos (en el HTML se usa p.name)
    conn = conectar()
    filas = [web.storage(dict(f)) for f in conn.execute(sql, datos)]
    conn.close()
    return filas


def ejecutar(sql, datos=()):  # INSERT / UPDATE: devuelve el cursor (cur.rowcount, cur.lastrowid)
    conn = conectar()
    cur = conn.execute(sql, datos)
    conn.commit()
    conn.close()
    return cur


def crear_tablas():
    conn = conectar()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS doctors (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, specialty TEXT);
        CREATE TABLE IF NOT EXISTS patients (id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn TEXT UNIQUE, name TEXT, age INTEGER, reason TEXT, attention_type TEXT, urgency INTEGER,
            estimated_minutes INTEGER, status TEXT DEFAULT 'espera', doctor_id INTEGER,
            created_at TEXT, called_at TEXT, finished_at TEXT);""")
    if conn.execute("SELECT COUNT(*) FROM doctors").fetchone()[0] == 0:  # medicos de ejemplo
        conn.executemany("INSERT INTO doctors (name, specialty) VALUES (?, ?)", MEDICOS)
    conn.commit()
    conn.close()


def ahora():
    return datetime.now().isoformat(timespec="seconds")


# ===== PARTE 2: PACIENTES =====
def registrar_paciente(nombre, edad, motivo, urgencia, estimado):
    """Valida y guarda. Devuelve (id, None) o (None, mensaje_de_error)."""
    nombre, motivo = nombre.strip(), motivo.strip()
    if nombre == "" or motivo == "":
        return None, "El nombre y el motivo de consulta son obligatorios."
    if not edad.isdigit() or int(edad) > 120:
        return None, "La edad debe ser un numero entre 0 y 120."
    if not urgencia.isdigit() or int(urgencia) not in URGENCIAS:
        return None, "Nivel de urgencia invalido."
    _, fila, minutos = URGENCIAS[int(urgencia)]
    if estimado.strip() != "":  # si escribieron un tiempo, se usa en vez del default
        if not estimado.isdigit() or not 1 <= int(estimado) <= 240:
            return None, "El tiempo estimado debe ser entre 1 y 240 minutos."
        minutos = int(estimado)

    # el turno es P-001, P-002... (fila prioritaria) o G-001, G-002... (fila general)
    cantidad = consultar("SELECT COUNT(*) AS n FROM patients WHERE attention_type=?", (fila,))[0].n
    turno = "%s-%03d" % (fila[0].upper(), cantidad + 1)
    cur = ejecutar("INSERT INTO patients (turn, name, age, reason, attention_type, urgency, "
                   "estimated_minutes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (turno, nombre, int(edad), motivo, fila, int(urgencia), minutos, ahora()))
    return cur.lastrowid, None


def obtener_paciente(patient_id):
    filas = consultar("SELECT p.*, d.name AS doctor_name FROM patients p "
                      "LEFT JOIN doctors d ON d.id = p.doctor_id WHERE p.id=?", (patient_id,))
    return filas[0] if filas else None


def obtener_historial():
    return consultar("SELECT p.*, d.name AS doctor_name FROM patients p "
                     "LEFT JOIN doctors d ON d.id = p.doctor_id ORDER BY p.id DESC LIMIT 100")


def cancelar_turno(patient_id):  # devuelve un mensaje de error, o None si salio bien
    cur = ejecutar("UPDATE patients SET status='cancelado', finished_at=? WHERE id=? AND status='espera'",
                   (ahora(), patient_id))
    return None if cur.rowcount else "No se pudo cancelar el turno."


# ===== PARTE 3: FILAS, MEDICOS Y ESTADISTICAS =====
def obtener_filas():
    """Devuelve (fila_prioritaria, fila_general, medicos). Cada paciente trae 'posicion' y 'espera'."""
    filas = [consultar("SELECT * FROM patients WHERE status='espera' AND attention_type=? ORDER BY id", (tipo,))
             for tipo in ("prioritaria", "general")]  # FIFO: el que llego primero va primero
    medicos = consultar("SELECT * FROM doctors ORDER BY id")
    for m in medicos:  # a cada medico le agregamos el paciente que atiende ahorita y cuantos lleva
        actual = consultar("SELECT * FROM patients WHERE doctor_id=? AND status='en_consulta'", (m.id,))
        m.actual = actual[0] if actual else None
        m.atendidos = consultar("SELECT COUNT(*) AS n FROM patients WHERE doctor_id=? AND status='atendido'",
                                (m.id,))[0].n

    acumulado = 0  # espera = minutos de los que van antes / medicos (la fila general va despues)
    for fila in filas:
        for i, p in enumerate(fila):
            p.posicion = i + 1
            p.espera = round(acumulado / max(1, len(medicos)))
            acumulado += p.estimated_minutes
    return filas[0], filas[1], medicos


def llamar_siguiente(doctor_id):
    """Primero la fila prioritaria; si esta vacia, la general. Devuelve error o None."""
    ocupado = consultar("SELECT id FROM patients WHERE doctor_id=? AND status='en_consulta'", (doctor_id,))
    # ordenando de Z a A, 'prioritaria' sale antes que 'general'; en cada fila, el primero que llego
    siguiente = consultar("SELECT id FROM patients WHERE status='espera' ORDER BY attention_type DESC, id LIMIT 1")
    if ocupado:
        return "El medico ya esta atendiendo a un paciente."
    if not siguiente:
        return "No hay pacientes en espera."
    ejecutar("UPDATE patients SET status='en_consulta', doctor_id=?, called_at=? WHERE id=?",
             (doctor_id, ahora(), siguiente[0].id))


def finalizar_consulta(doctor_id):
    cur = ejecutar("UPDATE patients SET status='atendido', finished_at=? "
                   "WHERE doctor_id=? AND status='en_consulta'", (ahora(), doctor_id))
    return None if cur.rowcount else "El medico no tiene una consulta en curso."


def estadisticas():
    s = web.storage()
    s.por_estado = consultar("SELECT status, COUNT(*) AS n FROM patients GROUP BY status")
    s.por_nivel = consultar("SELECT urgency, COUNT(*) AS n FROM patients GROUP BY urgency")
    # promedios en minutos (julianday da dias, por eso x1440)
    t = consultar("SELECT AVG((julianday(called_at) - julianday(created_at)) * 1440) AS espera, "
                  "AVG((julianday(finished_at) - julianday(called_at)) * 1440) AS consulta "
                  "FROM patients WHERE status='atendido'")[0]
    s.espera_prom, s.consulta_prom = round(t.espera or 0, 1), round(t.consulta or 0, 1)
    return s


# ===== PARTE 4: RUTAS (CONTROLADORES) Y ARRANQUE =====
urls = ("/", "Panel", "/register", "Registro", "/ticket/(\\d+)", "Ticket", "/history", "Historial",
        "/stats", "Estadisticas", "/(llamar|finalizar|cancelar)/(\\d+)", "Accion")


class Panel:
    def GET(self):
        prioritaria, general, medicos = obtener_filas()
        return render.index(web.input(msg="").msg, prioritaria, general, medicos)  # msg = error opcional


class Registro:
    def GET(self):
        return render.register(None, web.storage(name="", age="", reason="", urgency="4", estimated=""))

    def POST(self):
        d = web.input(name="", age="", reason="", urgency="4", estimated="")
        nuevo_id, error = registrar_paciente(d.name, d.age, d.reason, d.urgency, d.estimated)
        if error:
            return render.register(error, d)
        raise web.seeother("/ticket/%d" % nuevo_id)


class Ticket:
    def GET(self, patient_id):
        paciente = obtener_paciente(int(patient_id))
        if paciente is None:
            raise web.notfound("Turno no encontrado")
        prioritaria, general, _ = obtener_filas()  # si sigue esperando, buscamos su posicion
        posicion = ([p for p in prioritaria + general if p.id == paciente.id] or [None])[0]
        return render.ticket(paciente, posicion)


class Historial:
    def GET(self):
        return render.history(obtener_historial())


class Estadisticas:
    def GET(self):
        return render.stats(estadisticas())


class Accion:  # los botones mandan POST a /llamar/1, /finalizar/1 o /cancelar/5
    def POST(self, accion, id):
        acciones = {"llamar": llamar_siguiente, "finalizar": finalizar_consulta, "cancelar": cancelar_turno}
        error = acciones[accion](int(id))
        raise web.seeother("/?msg=" + web.urlquote(error) if error else "/")


crear_tablas()
app = web.application(urls, globals())
app.add_processor(web.loadhook(lambda: web.header("Content-Type", "text/html; charset=utf-8")))

if __name__ == "__main__":
    app.run()
