"""A throwaway certificate authority and a server certificate for 127.0.0.1, made in Python with `cryptography`, never
the system's `openssl` command (on a Mac that is LibreSSL, which links a certificate to its authority differently).
The fake services answer over HTTPS with them, and the app is made to trust them the standard way: by pointing
`SSL_CERT_FILE` at the authority's certificate. Nothing is trusted outside the process that is given that variable.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ADDRESS = "127.0.0.1"
DAYS = 365


@dataclass(frozen=True)
class Certificates:
    authority: Path  # the certificate to trust (SSL_CERT_FILE)
    certificate: Path  # the server's certificate
    key: Path  # the server's private key


def _name(common: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])


def make(folder: Path) -> Certificates:
    """The authority and the server certificate it signs, written into `folder` (made again each time), with what a
    strict verifier (the standard library's default) expects of each."""
    folder.mkdir(parents=True, exist_ok=True)
    found = Certificates(folder / "authority.pem", folder / "server.pem", folder / "server.key")
    # Wide either side of today: a test may move its own clock days ahead while the server and its clients run on the
    # real one, and each must find the certificates valid.
    now = datetime.now(UTC) - timedelta(days=DAYS)
    until = datetime.now(UTC) + timedelta(days=DAYS)
    authority_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    authority_id = x509.SubjectKeyIdentifier.from_public_key(authority_key.public_key())
    authority = (
        x509.CertificateBuilder()
        .subject_name(_name("Journey test authority"))
        .issuer_name(_name("Journey test authority"))
        .public_key(authority_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(until)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )  # fmt: skip
        .add_extension(authority_id, critical=False)
        .sign(authority_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server = (
        x509.CertificateBuilder()
        .subject_name(_name(ADDRESS))
        .issuer_name(authority.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(until)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ADDRESS))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )  # fmt: skip
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(authority_id), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False)
        .sign(authority_key, hashes.SHA256())
    )
    found.authority.write_bytes(authority.public_bytes(serialization.Encoding.PEM))
    found.certificate.write_bytes(server.public_bytes(serialization.Encoding.PEM))
    found.key.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
        )
    )
    return found
