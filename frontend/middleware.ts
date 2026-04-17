import { importSPKI, jwtVerify } from "jose";
import { NextRequest, NextResponse } from "next/server";

const JWT_ALGORITHM = "RS256";
const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "JWT Auth API";

function getPublicKeyPem(): string {
  const key = process.env.JWT_PUBLIC_KEY;
  if (!key || key.trim().length < 100) {
    throw new Error("JWT_PUBLIC_KEY env var is missing or invalid.");
  }
  return key.replace(/\\n/g, "\n");
}

// Cache the imported key — importSPKI is async but result is reusable
let _cachedPublicKey: Awaited<ReturnType<typeof importSPKI>> | null = null;
async function getPublicKey() {
  if (!_cachedPublicKey) {
    _cachedPublicKey = await importSPKI(getPublicKeyPem(), JWT_ALGORITHM);
  }
  return _cachedPublicKey;
}

const PROTECTED_PATHS = ["/dashboard"];
const AUTH_PATHS = ["/login", "/register"];

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get("access_token")?.value;

  const isProtected = PROTECTED_PATHS.some((p) => pathname.startsWith(p));
  const isAuthPage = AUTH_PATHS.some((p) => pathname.startsWith(p));

  let isAuthenticated = false;

  if (token) {
    try {
      const publicKey = await getPublicKey();
      const { payload } = await jwtVerify(token, publicKey, {
        algorithms: [JWT_ALGORITHM],
        issuer: APP_NAME,
        audience: APP_NAME,
      });
      // Enforce token type (H-7)
      isAuthenticated = payload["type"] === "access";
    } catch {
      isAuthenticated = false;
    }
  }

  if (isProtected && !isAuthenticated) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (isAuthPage && isAuthenticated) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/login", "/register"],
};
