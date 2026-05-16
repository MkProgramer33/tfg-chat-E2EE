"""
Test manual end-to-end del flujo completo:
  Alice cifra el mensaje con SBKProtocol → publica la Transaction en la
  blockchain vía /addtx (POST) → un validador la mina en un bloque →
  Bob lee el último bloque, encuentra su tx por la stealth address y
  descifra.

Prerequisito: un validador corriendo en localhost:8001 con --mine:
    cd chain
    uv run python main.py -p 8001 --mine -i validator-0

Correr desde la raíz del repo:
    uv run python client/frontendTest.py
"""

import base64
import os
import sys
import time
from pathlib import Path

import jsonpickle
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "protocol"))

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from chain.transaction import Transaction
from protocol.ratchet import init_alice, init_bob
from protocol.sbkProtocol import SBKProtocol, bootstrap_addresses

VALIDATOR = "http://localhost:8000"


def _pub_bytes(priv: X25519PrivateKey) -> bytes:
    return priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _bootstrap():
    """Mockea el X3DH y devuelve (alice, bob) listas para hablar."""
    SK = os.urandom(32)
    bob_kp = X25519PrivateKey.generate()
    bob_pub = _pub_bytes(bob_kp)

    alice_state = init_alice(SK, bob_pub)
    bob_state = init_bob(SK, bob_kp)

    alice_first, bob_first = bootstrap_addresses(SK)
    alice = SBKProtocol(
        alice_state,
        bootstrap_send_addr=alice_first,
        bootstrap_recv_addr=bob_first,
    )
    bob = SBKProtocol(
        bob_state,
        bootstrap_send_addr=bob_first,
        bootstrap_recv_addr=alice_first,
    )
    return alice, bob


def post_tx(tx: Transaction) -> None:
    """Publica una Transaction en /addtx (POST + JSON).

    `tx.msg` son bytes (header.dh || ciphertext), así que los base64-
    encodeamos para meterlos en el JSON.
    """
    body = {
        "to": tx.to,
        "msg": base64.b64encode(tx.msg).decode("ascii"),
    }
    r = requests.post(f"{VALIDATOR}/addtx", json=body, timeout=5)
    r.raise_for_status()


def fetch_last_block():
    r = requests.get(f"{VALIDATOR}/getlastblock", timeout=5)
    r.raise_for_status()
    return jsonpickle.decode(r.text)


def find_tx_in_block(block, expected_to: str) -> Transaction:
    """Busca la tx con el `to` esperado dentro del bloque y reconstruye
    la Transaction con `msg` ya base64-decodificado a bytes."""

    for tx in block["msg"]:
        print(tx)
        if tx['to'] == expected_to:
            return Transaction(to=tx['to'], msg=base64.b64decode(tx['msg']))
    raise RuntimeError(f"no tx con to={expected_to!r} en el último bloque")


if __name__ == "__main__":
    # 1. Recibo el mensaje "de la UI".
    msg = "hello world"

    # 2. Lo cifro: Alice produce la Transaction que viajará por la cadena.
    alice, bob = _bootstrap()
    tx = alice.send_message(msg)
    print(f"alice → tx.to = {tx.to[:16]}…  ({len(tx.msg)} bytes msg)")

    # 3. Publico la tx contra un validador.
    post_tx(tx)
    print("posted /addtx, esperando minado…")

    # 4. Doy tiempo al validador a sacar el bloque (mining_loop = ~1s + PoW).
    time.sleep(5)

    # 5. Pido el último bloque y busco MI tx por su stealth address.
    block = fetch_last_block()
    received_tx = find_tx_in_block(block, expected_to=tx.to)
    print(f"encontrada en bloque miner={block['miner']!r} index={block['index']}")

    # 6. Bob descifra.
    plaintext = bob.receive_message(received_tx)
    print(f"bob descifró: {plaintext!r}")
    assert plaintext == msg, f"mismatch: {plaintext!r} != {msg!r}"
    print("OK")
