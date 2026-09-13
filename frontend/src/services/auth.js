import { COGNITO_CLIENT_ID, COGNITO_ENDPOINT } from "../config";

const TOKEN_KEY = "cloudlog_id_token";
const USER_KEY = "cloudlog_user_data";

/**
 * Decode payload from a JWT token without external dependencies.
 */
function parseJwt(token) {
  try {
    const base64Url = token.split(".")[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(jsonPayload);
  } catch (err) {
    console.error("Failed to parse JWT:", err);
    return null;
  }
}

/**
 * Authenticate with AWS Cognito using USER_PASSWORD_AUTH flow.
 */
export async function login(username, password) {
  if (!COGNITO_CLIENT_ID) {
    throw new Error(
      "Cognito is not configured. Create frontend/.env.local from frontend/.env.example."
    );
  }

  const payload = {
    AuthFlow: "USER_PASSWORD_AUTH",
    ClientId: COGNITO_CLIENT_ID,
    AuthParameters: {
      USERNAME: username,
      PASSWORD: password,
    },
  };

  const response = await fetch(COGNITO_ENDPOINT, {
    method: "POST",
    headers: {
      "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
      "Content-Type": "application/x-amz-json-1.1",
    },
    body: JSON.stringify(payload),
  });

  const data = await response.json();

  if (!response.ok) {
    const errorMessage = data.__type
      ? `${data.__type}: ${data.message}`
      : data.message || "Cognito authentication failed";
    throw new Error(errorMessage);
  }

  const idToken = data.AuthenticationResult?.IdToken;
  if (!idToken) {
    throw new Error("Missing IdToken in Cognito authentication response");
  }

  const claims = parseJwt(idToken) || {};
  let role = "Viewer";

  const groups = claims["cognito:groups"] || [];
  if (Array.isArray(groups)) {
    if (groups.includes("Admin")) role = "Admin";
    else if (groups.includes("Analyst")) role = "Analyst";
  } else if (typeof groups === "string") {
    if (groups.includes("Admin")) role = "Admin";
    else if (groups.includes("Analyst")) role = "Analyst";
  }

  const userData = {
    userId: claims.sub || username,
    email: claims.email || username,
    role,
    groups: Array.isArray(groups) ? groups : [groups],
    idToken,
  };

  sessionStorage.setItem(TOKEN_KEY, idToken);
  sessionStorage.setItem(USER_KEY, JSON.stringify(userData));

  return userData;
}

/**
 * Log out and clear saved credentials.
 */
export function logout() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
}

/**
 * Get current authenticated user session if valid.
 */
export function getCurrentUser() {
  const token = sessionStorage.getItem(TOKEN_KEY);
  const rawData = sessionStorage.getItem(USER_KEY);

  if (!token || !rawData) {
    return null;
  }

  try {
    const claims = parseJwt(token);
    // Check token expiration
    if (claims && claims.exp && claims.exp * 1000 < Date.now()) {
      logout();
      return null;
    }
    return JSON.parse(rawData);
  } catch {
    logout();
    return null;
  }
}

/**
 * Retrieve active ID token for HTTP headers.
 */
export function getIdToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}
