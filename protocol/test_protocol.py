"""
End-to-end tests del SBK Protocol con bootstrap X3DH mockeado.

En producción X3DH proporcionaría:
  - El secreto compartido SK que siembra el ratchet.
  - El signed prekey de Bob (par DH long-lived que Alice ya conoce como DHr).

Aquí los mockeamos a mano. Las direcciones iniciales se derivan de SK
con `bootstrap_addresses`, así que ambos peers las calculan igual sin
hablar fuera de banda.

Correr desde dentro de `protocol/`:
    cd protocol
    uv run python -m unittest test_protocol

Requiere: `uv add --package e2ee-chat cryptography`
"""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "protocol"))

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ratchet import init_alice, init_bob
from sbkProtocol import SBKProtocol, bootstrap_addresses


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

    # alice_first = donde Alice escribe su primer mensaje
    #             = donde Bob escanea esperando el primer mensaje de Alice.
    # bob_first   = donde Bob escribe su primera respuesta
    #             = donde Alice escanea esperando la primera respuesta de Bob.
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


class TestSBKProtocol(unittest.TestCase):

    def test_alice_to_bob_single(self):
        alice, bob = _bootstrap()
        tx = alice.send_message("hola Bob")
        self.assertEqual(bob.receive_message(tx), "hola Bob")

    def test_back_to_back_different_addresses(self):
        """Con address derivada del mk, mensajes consecutivos tienen `to` DISTINTO."""
        alice, bob = _bootstrap()
        tx1 = alice.send_message("primer")
        tx2 = alice.send_message("segundo")
        tx3 = alice.send_message("tercer")

        self.assertNotEqual(tx1.to, tx2.to)
        self.assertNotEqual(tx2.to, tx3.to)
        self.assertNotEqual(tx1.to, tx3.to)

        self.assertEqual(bob.receive_message(tx1), "primer")
        self.assertEqual(bob.receive_message(tx2), "segundo")
        self.assertEqual(bob.receive_message(tx3), "tercer")

    def test_round_trip_with_dh_rotation(self):
        """Ida y vuelta — debe funcionar sin tocar `_recv_addr` a mano.

        El primer reply de Bob entra en una cadena nueva (su DH rotó dentro
        de su step). Alice lo encuentra porque la dirección la anunció Bob
        en `bundle.next_address` del mensaje que Alice ya recibió... espera,
        Bob aún no ha mandado nada. ¿Cómo lo encuentra entonces? Por la
        bootstrap address derivada de SK: Bob escribe su primer reply ahí
        y Alice escanea ahí mismo.

        El SEGUNDO reply de Bob ya viaja en cadena nueva con address de
        mk: Alice la obtiene de bundle.next_address del primer reply.
        """
        alice, bob = _bootstrap()

        self.assertEqual(bob.receive_message(alice.send_message("hola")), "hola")
        self.assertEqual(alice.receive_message(bob.send_message("hi Alice")), "hi Alice")
        self.assertEqual(bob.receive_message(alice.send_message("qué tal")), "qué tal")
        self.assertEqual(alice.receive_message(bob.send_message("bien")), "bien")
        self.assertEqual(bob.receive_message(alice.send_message("vale")), "vale")

    def test_alice_burst_then_reply(self):
        """Alice manda 3 seguidos, Bob responde, Alice responde otra vez.

        El primer mensaje tras recibir el reply de Bob es la "transición":
        usa la cadena vieja, anuncia la siguiente address (ya de la cadena
        nueva) en el bundle. Bob debe poder seguir el hilo sin perderse.
        """
        alice, bob = _bootstrap()

        for body in ["a1", "a2", "a3"]:
            self.assertEqual(bob.receive_message(alice.send_message(body)), body)

        self.assertEqual(alice.receive_message(bob.send_message("b1")), "b1")

        for body in ["a4", "a5"]:
            self.assertEqual(bob.receive_message(alice.send_message(body)), body)

    def test_tampered_ciphertext_is_rejected(self):
        alice, bob = _bootstrap()
        tx = alice.send_message("integridad")

        # Header.dh ocupa los primeros 32 bytes; el resto es AEAD output.
        tampered = bytearray(tx.msg)
        tampered[40] ^= 0x01
        tx.msg = bytes(tampered)

        with self.assertRaises(Exception):
            bob.receive_message(tx)

    def test_wrong_recv_address_is_rejected(self):
        alice, bob = _bootstrap()
        tx = alice.send_message("hola")
        tx.to = "deadbeef" * 8

        with self.assertRaises(ValueError):
            bob.receive_message(tx)


if __name__ == "__main__":
    unittest.main()
