import { importSPKI, jwtVerify } from "jose";
import { cookies } from "next/headers";

const JWT_ALGORITHM = "RS256";
const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "JWT Auth API";

function getPublicKeyPem(): string {
  const key = process.env.JWT_PUBLIC_KEY;
  if (!key || key.trim().length < 100) {
    throw new Error(
      "JWT_PUBLIC_KEY env var is missing or too short. Set a valid RSA public key (PEM)."
    );
  }
  return key.replace(/\\n/g, "\n");
}

async function getPublicKey() {
  return importSPKI(getPublicKeyPem(), JWT_ALGORITHM);
}

export type JWTPayload = {
  sub: string;
  ver: number;
  type: string;
  exp: number;
  iat: number;
  iss: string;
  aud: string;
};

export async function verifySession(): Promise<JWTPayload | null> {
  const cookieStore = await cookies();
  const token = cookieStore.get("access_token")?.value;
  if (!token) return null;

  try {
    const publicKey = await getPublicKey();
    const { payload } = await jwtVerify(token, publicKey, {
      algorithms: [JWT_ALGORITHM],
      issuer: APP_NAME,
      audience: APP_NAME,
    });

    // Enforce token type claim (H-7)
    if (payload["type"] !== "access") return null;

    return payload as unknown as JWTPayload;
  } catch {
    return null;
  }
}

export async function requireAuth(): Promise<JWTPayload> {
  const session = await verifySession();
  if (!session) {
    // Throw a typed error that callers can catch and redirect
    const err = new Error("Unauthorized");
    err.name = "UnauthorizedError";
    throw err;
  }
  return session;
}
