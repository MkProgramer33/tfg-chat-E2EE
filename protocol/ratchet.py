"""
Double Ratchet mínimo para el TFG.

Simplificaciones respecto al spec de Signal:
- Sin lógica de mensajes fuera de orden (sin MKSKIPPED, sin MAX_SKIP, sin
  SkipMessageKeys / TrySkippedMessageKeys). Justificación: el bulletin board
  impone orden total a los mensajes vía el orden de los bloques, así que
  esta capa no necesita tolerar reordenamientos.
- Primitivas concretas: X25519 (DH), HKDF-SHA256 (KDF de root), HMAC-SHA256
  (KDF de chain key), ChaCha20-Poly1305 (AEAD). Todas de `cryptography`.

API pública: init_alice, init_bob, encrypt, decrypt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

DH_PUB_LEN = 32  # X25519 public key length in bytes


# ----------------------------------------------------------------------------
# Primitivas envueltas (one-liners) para mantener legible el cuerpo del ratchet
# ----------------------------------------------------------------------------

def _gen_dh() -> X25519PrivateKey:
    return X25519PrivateKey.generate()


def _dh(priv: X25519PrivateKey, pub_bytes: bytes) -> bytes:
    return priv.exchange(X25519PublicKey.from_public_bytes(pub_bytes))


def _pub_bytes(priv: X25519PrivateKey) -> bytes:
    return priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int = 64) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _hmac(key: bytes, data: bytes) -> bytes:
    h = hmac.HMAC(key, hashes.SHA256())
    h.update(data)
    return h.finalize()


def _aead_encrypt(key: bytes, plaintext: bytes, ad: bytes) -> bytes:
    # Nonce constante: cada `key` se usa una sola vez (sale del chain ratchet).
    return ChaCha20Poly1305(key).encrypt(b"\x00" * 12, plaintext, ad)


def _aead_decrypt(key: bytes, ciphertext: bytes, ad: bytes) -> bytes:
    return ChaCha20Poly1305(key).decrypt(b"\x00" * 12, ciphertext, ad)


# ----------------------------------------------------------------------------
# KDFs del spec
# ----------------------------------------------------------------------------

def _kdf_rk(rk: bytes, dh_out: bytes) -> tuple[bytes, bytes]:
    """KDF de la root key: devuelve (new_rk, new_chain_key)."""
    out = _hkdf(salt=rk, ikm=dh_out, info=b"sbk-rk", length=64)
    return out[:32], out[32:]


def _kdf_ck(ck: bytes) -> tuple[bytes, bytes]:
    """KDF del chain key: devuelve (new_ck, message_key)."""
    return _hmac(ck, b"\x01"), _hmac(ck, b"\x02")


# ----------------------------------------------------------------------------
# Estado y operaciones del ratchet
# ----------------------------------------------------------------------------

@dataclass
class Header:
    dh: bytes  # clave pública DH actual del emisor (32 bytes)


@dataclass
class State:
    DHs: X25519PrivateKey       # nuestro par DH actual
    DHr: Optional[bytes]        # clave pública DH del peer (bytes), None hasta verla
    RK: bytes                   # root key
    CKs: Optional[bytes]        # chain key de envío
    CKr: Optional[bytes]        # chain key de recepción
    # Rotación diferida. Cuando recibimos un mensaje que dispara un DH step
    # (no el primero), el "segundo medio step" — nuestra DHs nueva y la CKs
    # nueva — se cachea aquí en vez de activarse al instante. El próximo
    # encrypt() emite UN mensaje en la cadena vieja (la transición) y luego
    # activa lo de pending. Así el receptor sabe pre-computar la dirección
    # de la transición con la cadena vieja, y aprende la nueva pub viendo
    # el header del mensaje SIGUIENTE.
    pending_DHs: Optional[X25519PrivateKey] = None
    pending_CKs: Optional[bytes] = None
    pending_RK: Optional[bytes] = None


def init_alice(SK: bytes, bob_dh_pub: bytes) -> State:
    """Alice arranca: trae SK del X3DH y la pubkey DH inicial de Bob."""
    dhs = _gen_dh()
    rk, cks = _kdf_rk(SK, _dh(dhs, bob_dh_pub))
    return State(DHs=dhs, DHr=bob_dh_pub, RK=rk, CKs=cks, CKr=None)


def init_bob(SK: bytes, bob_dh_keypair: X25519PrivateKey) -> State:
    """Bob arranca: trae SK del X3DH y su par DH (signed prekey). Aún sin DHr."""
    return State(DHs=bob_dh_keypair, DHr=None, RK=SK, CKs=None, CKr=None)


def encrypt(state: State, plaintext: bytes, ad: bytes) -> tuple[Header, bytes]:
    if state.CKs is None:
        raise RuntimeError("no sending chain yet — receive a message first")
    state.CKs, mk = _kdf_ck(state.CKs)
    header = Header(dh=_pub_bytes(state.DHs))
    ciphertext = _aead_encrypt(mk, plaintext, ad + header.dh)

    # Si había una rotación diferida, este mensaje fue la transición:
    # activamos ahora la cadena nueva para los próximos envíos.
    if state.pending_DHs is not None:
        state.DHs = state.pending_DHs
        state.RK = state.pending_RK
        state.CKs = state.pending_CKs
        state.pending_DHs = None
        state.pending_RK = None
        state.pending_CKs = None

    return header, ciphertext


def decrypt(state: State, header: Header, ciphertext: bytes, ad: bytes) -> bytes:
    if state.DHr != header.dh:
        _dh_ratchet_step(state, header.dh)
    state.CKr, mk = _kdf_ck(state.CKr)
    return _aead_decrypt(mk, ciphertext, ad + header.dh)


def _dh_ratchet_step(state: State, new_peer_dh_pub: bytes) -> None:
    """El peer rotó su DH.

    Primero deriva la CKr nueva (para poder descifrar el mensaje que disparó
    el step). Después prepara la mitad de envío (nuestra DHs nueva + CKs
    nueva), pero **NO la activa** si ya teníamos una cadena de envío en uso:
    se cachea en pending_* y el próximo encrypt() la activará después de
    haber emitido el mensaje de transición en la cadena vieja.

    En el primer step de una sesión (Bob al recibir el primer mensaje de
    Alice), no hay cadena vieja que preservar, así que activamos al instante.
    """
    state.DHr = new_peer_dh_pub
    state.RK, state.CKr = _kdf_rk(state.RK, _dh(state.DHs, state.DHr))

    new_dhs = _gen_dh()
    new_rk, new_cks = _kdf_rk(state.RK, _dh(new_dhs, state.DHr))

    if state.CKs is None:
        # Primer step de la sesión — no hay cadena vieja que arrastrar.
        state.DHs = new_dhs
        state.RK = new_rk
        state.CKs = new_cks
    else:
        # Step posterior — diferimos hasta el próximo encrypt().
        state.pending_DHs = new_dhs
        state.pending_RK = new_rk
        state.pending_CKs = new_cks


# ----------------------------------------------------------------------------
# Empaquetado: el SBK protocol mete (Header, ciphertext) en Transaction.msg
# como un único blob de bytes. Header.dh ocupa los primeros 32 bytes.
# ----------------------------------------------------------------------------

def pack(header: Header, ciphertext: bytes) -> bytes:
    assert len(header.dh) == DH_PUB_LEN
    return header.dh + ciphertext


def unpack(blob: bytes) -> tuple[Header, bytes]:
    return Header(dh=blob[:DH_PUB_LEN]), blob[DH_PUB_LEN:]


def current_send_pub(state: State) -> bytes:
    """Pubkey DH actual con la que mandaremos — base de la stealth address."""
    return _pub_bytes(state.DHs)


def peek_next_send_mk(state: State) -> Optional[bytes]:
    """Mk que usará el próximo encrypt(), sin avanzar CKs.

    Como `_kdf_ck` es una función pura, llamarla aquí y luego en `encrypt`
    devuelve el mismo (new_ck, mk) — no hay riesgo de descoordinación.
    """
    if state.CKs is None:
        return None
    _, mk = _kdf_ck(state.CKs)
    return mk


def peek_next_recv_mk(state: State) -> Optional[bytes]:
    """Mk que usará el próximo decrypt() sin paso de DH, sin avanzar CKr."""
    if state.CKr is None:
        return None
    _, mk = _kdf_ck(state.CKr)
    return mk


def peek_next_after_send_mk(state: State) -> Optional[bytes]:
    """Mk que usará el encrypt() POSTERIOR al próximo, sin mutar estado.

    Útil para que SBKProtocol pueda anunciar la dirección del *próximo*
    mensaje en `bundle.next_address`. Si hay una rotación pendiente, el
    siguiente encrypt() activará pending_CKs, así que el "encrypt + 1"
    saldrá de la cadena nueva.
    """
    if state.CKs is None:
        return None
    if state.pending_CKs is not None:
        next_chain_start = state.pending_CKs
    else:
        next_chain_start, _ = _kdf_ck(state.CKs)
    _, mk = _kdf_ck(next_chain_start)
    return mk
