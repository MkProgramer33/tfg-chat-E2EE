# Levantar la red de la cadena (validadores y clientes)

Esta guía explica cómo levantar la blockchain que actúa como **bulletin board**
del chat E2EE: nodos que minan bloques (**validadores**) y procesos que solo
publican o leen mensajes a través de la API HTTP (**clientes**).

La API del nodo es HTTP. Las lecturas (`/getblockchain`, `/getmempool`, …)
son GET y se pueden hacer desde el navegador o `curl`. Las publicaciones
con payload (`/addtx`, `/addblock`) son POST con cuerpo JSON, para que el
ciphertext y los bloques no acaben en la URL ni en los logs de acceso.

---

## 0. Requisitos previos

Desde la raíz del repo, sincroniza dependencias con `uv`:

```bash
uv sync
```

Todos los comandos `python` de esta guía asumen que estás **dentro de
`chain/`** (los módulos importan en plano: `from blockchain import ...`).

```bash
cd chain
```

Para correrlos con el entorno de `uv`, antepón `uv run`:

```bash
uv run python main.py -p 8000 --mine
```

---

## 1. Flags de `main.py`

| Flag | Significado | Por defecto    |
|---|---|----------------|
| `-p`, `--port` | Puerto donde escucha el nodo (obligatorio) | `8000`         |
| `-m`, `--mine` | Lanza minado, gossip y resolución de splits en background. Sin este flag el nodo es pasivo (solo expone API). | desactivado    |
| `-b`, `--boot-node` | `host:port` de un nodo conocido para entrar en la red. | ninguno        |
| `-i`, `--node-id` | Identificador del nodo (aparece en bloques minados). | UUID aleatorio |
| `-n`, `--node-ip` | IP pública que otros peers usarán para alcanzarte. | `localhost`    |

---

## 2. Validador (nodo que mina)

Un validador es un nodo arrancado con `--mine`. En background corre tres
bucles: minado PoW, `resolve_split` (adopta la cadena más larga vista en la
red) y `gossip_peerstore` (propaga peers conocidos).

> El bucle de minado **solo produce un bloque cuando el mempool tiene
> transacciones pendientes**. Mientras no haya mensajes publicados por
> clientes, el validador no inventa bloques vacíos.

### 2.1 Validador único (red de un solo nodo, útil para pruebas locales)

```bash
uv run python main.py -p 8000 --mine -i validator-0
```

### 2.2 Red multi-validador en la misma máquina

Levanta primero el bootnode y luego validadores adicionales que apunten a él.
Cada uno en su propia terminal:

```bash
# Terminal 1 — bootnode
uv run python main.py -p 8000 --mine -i validator-0

# Terminal 2 — segundo validador
uv run python main.py -p 8001 --mine -i validator-1 --boot-node=localhost:8000

# Terminal 3 — tercer validador
uv run python main.py -p 8002 --mine -i validator-2 --boot-node=localhost:8000
```

Tras unos segundos, comprueba que se han descubierto entre sí:

```bash
curl localhost:8000/getpeerstore
curl localhost:8001/getpeerstore
```

### 2.3 Validador en red P2P real (varias máquinas)

- Abre el puerto en tu router y NAT. Puedes verificarlo con
  <https://www.yougetsignal.com/tools/open-ports/>.
- Pasa tu IP pública en `--node-ip` para que otros peers puedan alcanzarte.
- Es aceptable que no todos los peers tengan puertos abiertos, pero **el
  bootnode sí debe tenerlos**.

```bash
uv run python main.py -p 8000 --mine \
    --node-ip=<tu-ip-publica> \
    --boot-node=<ip-bootnode>:8000 \
    -i validator-remote
```

---

## 3. Cliente (publicar y leer mensajes)

En este Proof of Concept un "cliente" del chat no necesita correr un nodo
propio: basta con que hable HTTP contra **cualquier validador**. Cuando el
binario de `client/` esté listo, hará exactamente eso por debajo.

Para experimentar a mano:

### 3.1 Publicar un mensaje (ciphertext) en el mempool

`/addtx` es POST con cuerpo JSON:

```bash
curl -X POST http://localhost:8000/addtx \
     -H 'Content-Type: application/json' \
     -d '{"sender": "<pubkeyA>", "to": "<pubkeyB>", "msg": "<ciphertext>"}'
```

El mensaje queda **pendiente** en el mempool hasta que un validador lo
incluya en un bloque.

### 3.2 Inspeccionar mempool y cadena

```bash
curl localhost:8000/getmempool        # mensajes pendientes
curl localhost:8000/getlastblock      # último bloque
curl localhost:8000/getblockchain     # cadena completa (JSON)
```

### 3.3 Cliente como nodo pasivo (opcional)

Si quieres que un cliente mantenga una copia local de la cadena sin minar,
lánzalo **sin** `--mine` y con un bootnode:

```bash
uv run python main.py -p 8100 -i client-0 --boot-node=localhost:8000
```

Este nodo no mina, pero recibe bloques broadcast por `/addblock` y puede
servir a la TUI desde `localhost:8100`. Útil cuando no quieres confiar en un
único validador para leer.

> Nota: en modo pasivo no corre `resolve_split` en background, así que si
> sospechas que estás en un fork llama manualmente:
> `curl localhost:8100/resolvesplit`.

---

## 4. Flujo de extremo a extremo (sanity check)

Con un validador en `:8000`:

```bash
# 1. Publica un mensaje
curl -X POST http://localhost:8000/addtx \
     -H 'Content-Type: application/json' \
     -d '{"sender": "alice", "to": "bob", "msg": "hola-cifrado"}'

# 2. Comprueba que está pendiente
curl localhost:8000/getmempool

# 3. (Si NO usas --mine) mina manualmente
curl localhost:8000/mine

# 4. Verifica que el mensaje quedó en la cadena
curl localhost:8000/getlastblock
```

En modo `--mine` el paso 3 sobra: el bucle de minado detecta el mempool
no vacío y produce el bloque en ≤ 1 s. Si el mempool está vacío,
`/mine` responde `Nothing to mine: mempool is empty` y el validador
no genera bloques.

---

## 5. Endpoints disponibles (resumen)

| Endpoint | Método | Body / params | Uso |
|---|---|---|---|
| `/` | GET | — | Estado del nodo (id, mempool, peers, bloques) |
| `/addtx` | POST | `{"sender","to","msg"}` | Publicar ciphertext en el mempool |
| `/addblock` | POST | `{"block": "<jsonpickle>"}` | Recibir un bloque (uso interno del broadcast) |
| `/addpeer?peer=host:port` | GET | query `peer` | Añadir un peer manualmente |
| `/getlastblock` | GET | — | Último bloque |
| `/getblockchain` | GET | — | Cadena completa en JSON |
| `/getpeerstore` | GET | — | Lista de peers conocidos |
| `/getmempool` | GET | — | Mensajes pendientes |
| `/mine` | GET | — | Minar un bloque manualmente (no-op si mempool vacío) |
| `/resolvesplit` | GET | — | Forzar adopción de la cadena más larga vista |

---

## 6. Tests

```bash
cd chain
uv run python -m unittest test
```
