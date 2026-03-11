#!/usr/bin/env python3
"""Generate self-signed certificates for HTTPS communication."""

import os
import sys
import argparse
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import datetime
import ipaddress

def generate_self_signed_cert(
    hostname: str = "localhost",
    ip_addresses: list = None,
    cert_file: str = "certs/server.crt",
    key_file: str = "certs/server.key",
    days_valid: int = 365
):
    """Generate a self-signed certificate for HTTPS."""
    
    if ip_addresses is None:
        ip_addresses = ["127.0.0.1", "192.168.1.0/24"]
    
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    # Create certificate subject
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "CA"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Clank Voice Assistant"),
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
    ])
    
    # Create certificate
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc)
    ).not_valid_after(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days_valid)
    ).add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName(hostname),
            x509.DNSName("localhost"),
            x509.DNSName("*.local"),
        ] + [
            x509.IPAddress(ipaddress.ip_address(ip)) 
            for ip in ["127.0.0.1", "::1"]
        ]),
        critical=False,
    ).add_extension(
        x509.KeyUsage(
            key_encipherment=True,
            digital_signature=True,
            key_agreement=False,
            key_cert_sign=False,
            crl_sign=False,
            content_commitment=False,
            data_encipherment=False,
            encipher_only=False,
            decipher_only=False,
        ),
        critical=True,
    ).add_extension(
        x509.ExtendedKeyUsage([
            x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
        ]),
        critical=True,
    ).sign(private_key, hashes.SHA256())
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(cert_file), exist_ok=True)
    os.makedirs(os.path.dirname(key_file), exist_ok=True)
    
    # Write certificate
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    # Write private key
    with open(key_file, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    # Set restrictive permissions on private key
    os.chmod(key_file, 0o600)
    
    print(f"Generated certificate: {cert_file}")
    print(f"Generated private key: {key_file}")
    print(f"Valid for {days_valid} days")
    print(f"Hostname: {hostname}")
    
    return cert_file, key_file

def main():
    parser = argparse.ArgumentParser(description="Generate self-signed certificates for Clank")
    parser.add_argument(
        "--hostname", 
        default="localhost", 
        help="Hostname for the certificate (default: localhost)"
    )
    parser.add_argument(
        "--cert-file",
        default="certs/server.crt",
        help="Certificate file path (default: certs/server.crt)"
    )
    parser.add_argument(
        "--key-file",
        default="certs/server.key", 
        help="Private key file path (default: certs/server.key)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Certificate validity in days (default: 365)"
    )
    
    args = parser.parse_args()
    
    try:
        generate_self_signed_cert(
            hostname=args.hostname,
            cert_file=args.cert_file,
            key_file=args.key_file,
            days_valid=args.days
        )
        print("\nTo use these certificates, set environment variables:")
        print(f"export CLANK_HTTPS_CERT={args.cert_file}")
        print(f"export CLANK_HTTPS_KEY={args.key_file}")
        print(f"export CLANK_ENABLE_HTTPS=true")
        
    except Exception as e:
        print(f"Error generating certificates: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()