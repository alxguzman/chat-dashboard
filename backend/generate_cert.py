"""
generate_cert.py — Creates a self-signed SSL certificate for localhost HTTPS.

Run this ONCE before starting the server:
    cd backend
    python generate_cert.py

This creates cert.pem and key.pem in the backend/ folder.
The server uses them automatically when you run python main.py.

You'll get a browser warning ("Your connection is not private") —
click Advanced → Proceed to localhost. This is normal for self-signed certs.
You only need to do this once per browser.
"""

from pathlib import Path

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509 import SubjectAlternativeName, DNSName, IPAddress
    import ipaddress
    import datetime
except ImportError:
    print("Installing cryptography package...")
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography"])
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509 import SubjectAlternativeName, DNSName, IPAddress
    import ipaddress
    import datetime

backend_dir = Path(__file__).parent
cert_path   = backend_dir / "cert.pem"
key_path    = backend_dir / "key.pem"

# Generate private key
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

# Build certificate
subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
])

cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.utcnow())
    .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=825))
    .add_extension(
        x509.SubjectAlternativeName([
            DNSName("localhost"),
            IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]),
        critical=False,
    )
    .sign(key, hashes.SHA256())
)

# Write files
key_path.write_bytes(key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
))

cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

print(f"✓ Created {cert_path}")
print(f"✓ Created {key_path}")
print()
print("Next steps:")
print("  1. python main.py")
print("  2. Open https://localhost:8000 (note: https, not http)")
print("  3. Click 'Advanced' → 'Proceed to localhost' to accept the self-signed cert")
print("  4. Also update TWITCH_REDIRECT_URI in .env to: https://localhost:8000/auth/callback")
print("     and update it in your Twitch developer console too")