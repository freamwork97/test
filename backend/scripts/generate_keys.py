"""Generate RS256 key pair for JWT signing.

Usage:
    uv run python scripts/generate_keys.py
"""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    print("# Add to backend/.env")
    print(f'JWT_PRIVATE_KEY="{private_pem.strip()}"\n')
    print("# Add to frontend/.env.local (safe to expose)")
    print(f'JWT_PUBLIC_KEY="{public_pem.strip()}"')


if __name__ == "__main__":
    generate()
