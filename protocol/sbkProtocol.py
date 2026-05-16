"""
SBK Protocol — Stealth Bulletin-board Keys.

Envuelve el Double Ratchet de `ratchet.py` y añade la capa de stealth
addresses sobre el bulletin board: cada ciphertext publicado lleva, *dentro
del payload cifrado*, la dirección donde el peer debe buscar nuestro
siguiente mensaje.

Invariante de seguridad (memory/feedback_stealth_address.md):
    `next_address` viaja DENTRO del ciphertext AEAD, nunca como campo
    plaintext de la Transaction.

Esquema de direcciones — con rotación diferida:
  - `tx.to = HMAC(mk_n, "sbk-address")` donde `mk_n` es la message key
    de este mensaje. Como mk avanza por mensaje, dos txs consecutivas en
    la cadena tienen `tx.to` distintos (unlinkable).
  - `bundle.next_address = HMAC(mk_{n+1}, "sbk-address")`. El receptor
    confía en este valor sin recomputarlo. Es lo que hace que el
    bootstrap problem (predecir la dirección de la primera tx de una
    cadena nueva tras una rotación DH) desaparezca: cuando una rotación
    está pendiente, `mk_{n+1}` ya sale de la cadena nueva, y el receptor
    se entera viendo el bundle del mensaje de transición que aún viaja
    en la cadena vieja.

Limitación conocida: la `header.dh` viaja en plaintext en `tx.msg` (ver
`ratchet.pack`). Un observador que escanee la cadena ve la pubkey actual
del emisor y puede agrupar txs por época DH. Las stealth addresses dan
unlinkability por mensaje pero no por época. Fix futuro: cifrar el
header con una subclave (extensión Header Encryption del spec Signal).
"""

from __future__ import annotations

import hashlib
import hmac
import sys
from dataclasses import dataclass
from pathlib import Path

# TODO(packaging): retirar este hack cuando montemos __init__.py y un
# entrypoint único en la raíz del repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from chain.transaction import Transaction  # noqa: E402

import jsonpickle

from ratchet import (
    State,
    decrypt,
    encrypt,
    pack,
    peek_next_after_send_mk,
    peek_next_send_mk,
    unpack,
)

ADDR_LABEL = b"sbk-address"


@dataclass
class _PlaintextBundle:
    """Lo que ciframos en AEAD y va dentro de Transaction.msg."""
    next_address: str
    body: str


def _addr_from_mk(mk: bytes) -> str:
    """Derivación de stealth address: HMAC(mk, "sbk-address") en hex."""
    return hmac.new(mk, ADDR_LABEL, hashlib.sha256).hexdigest()


def bootstrap_addresses(SK: bytes) -> tuple[str, str]:
    """Devuelve (alice_first_addr, bob_first_addr) derivables ambas de SK.

    Se usan como `bootstrap_send_addr`/`bootstrap_recv_addr` para que el
    primer mensaje en cada dirección tenga una ubicación pre-acordada en
    la cadena. Ambos peers la calculan del SK que sale de X3DH; no hace
    falta comunicarlas out-of-band.
    """
    alice = hmac.new(SK, b"sbk-bootstrap-alice", hashlib.sha256).hexdigest()
    bob = hmac.new(SK, b"sbk-bootstrap-bob", hashlib.sha256).hexdigest()
    return alice, bob


class SBKProtocol:
    """Un extremo de una conversación.

    Direcciones:
      - Primer envío: usa `bootstrap_send_addr` (derivada de SK, conocida
        por ambos).
      - Envíos posteriores: HMAC(peek_next_send_mk, "sbk-address").
      - Primer receive: escanea `bootstrap_recv_addr`.
      - Receives posteriores: escanea `_recv_addr`, valor que viene en
        `bundle.next_address` del mensaje anterior.

    El truco de la rotación diferida (ver `ratchet._dh_ratchet_step`)
    hace que el mensaje de transición tras una rotación DH viaje en la
    cadena vieja, así que el receptor lo encuentra sin saber aún la
    pubkey DH nueva — y aprende la próxima address del bundle.
    """

    def __init__(
        self,
        state: State,
        bootstrap_send_addr: str,
        bootstrap_recv_addr: str,
    ):
        self.state = state
        self._bootstrap_send_addr = bootstrap_send_addr
        self._bootstrap_recv_addr = bootstrap_recv_addr
        self._first_send_done = False
        self._first_recv_done = False
        # Se actualiza desde bundle.next_address en cada receive.
        self._recv_addr: str = bootstrap_recv_addr

    @property
    def my_send_addr(self) -> str:
        if not self._first_send_done:
            return self._bootstrap_send_addr
        mk = peek_next_send_mk(self.state)
        if mk is None:
            raise RuntimeError(
                "no sending chain yet — receive a message from peer first"
            )
        return _addr_from_mk(mk)

    @property
    def watching_addr(self) -> str:
        return self._recv_addr

    # ------------------------------------------------------------------
    # API pública — usada por client/
    # ------------------------------------------------------------------

    def send_message(self, body: str) -> Transaction:
        send_addr = self.my_send_addr

        # Dirección que anunciamos para el siguiente mensaje. Si hay una
        # rotación pendiente, sale ya de la cadena NUEVA (peek_next_after_*
        # tiene en cuenta el pending).
        next_mk = peek_next_after_send_mk(self.state)
        next_addr = _addr_from_mk(next_mk) if next_mk is not None else send_addr

        plaintext = jsonpickle.encode(
            _PlaintextBundle(next_address=next_addr, body=body)
        ).encode("utf-8")

        header, ciphertext = encrypt(
            self.state, plaintext, ad=send_addr.encode("utf-8")
        )

        self._first_send_done = True
        return Transaction(to=send_addr, msg=pack(header, ciphertext))

    def receive_message(self, tx: Transaction) -> str:
        if tx.to != self._recv_addr:
            raise ValueError(
                f"unexpected stealth address: got {tx.to!r}, "
                f"watching {self._recv_addr!r}"
            )
        header, ciphertext = unpack(tx.msg)
        plaintext = decrypt(
            self.state, header, ciphertext, ad=tx.to.encode("utf-8")
        )
        bundle: _PlaintextBundle = jsonpickle.decode(plaintext.decode("utf-8"))

        self._first_recv_done = True
        self._recv_addr = bundle.next_address
        return bundle.body
