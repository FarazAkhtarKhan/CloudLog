import { COGNITO_CLIENT_ID, COGNITO_ENDPOINT, MODE, ROLES } from "../config";

const SESSION_KEY = "cloudlog_session";

function decodeJwt(token) {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(decodeURIComponent(escape(atob(part))));
  } catch {
    return {};
  }
}

function save(session) {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    /* private mode: session lasts until reload */
  }
  return session;
}

/** Local emulator: pick a demo role. The API trusts the X-User-Role header only in emulator mode. */
export function signInLocal(role) {
  const account = ROLES.find((r) => r.role === role);
  return save({ email: account.email, role, token: null });
}

/** AWS: Cognito USER_PASSWORD_AUTH straight from the browser, no backend hop. */
export async function signInCognito(email, password) {
  if (!COGNITO_CLIENT_ID) throw new Error("VITE_COGNITO_CLIENT_ID is missing. Add it to frontend/.env.local.");
  const response = await fetch(COGNITO_ENDPOINT, {
    method: "POST",
    headers: {
      "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
      "Content-Type": "application/x-amz-json-1.1",
    },
    body: JSON.stringify({
      AuthFlow: "USER_PASSWORD_AUTH",
      ClientId: COGNITO_CLIENT_ID,
      AuthParameters: { USERNAME: email, PASSWORD: password },
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.__type === "NotAuthorizedException" ? "Wrong email or password." : data.message || "Sign-in failed.");
  }
  const token = data.AuthenticationResult.IdToken;
  const claims = decodeJwt(token);
  const groups = [].concat(claims["cognito:groups"] || []);
  const role = ["Admin", "Analyst", "Viewer"].find((r) => groups.includes(r)) || "Viewer";
  return save({ email: claims.email || email, role, token, expires: claims.exp * 1000 });
}

export function currentSession() {
  try {
    const session = JSON.parse(sessionStorage.getItem(SESSION_KEY));
    if (!session) return null;
    if (MODE === "aws" && (!session.token || session.expires < Date.now())) return null;
    return session;
  } catch {
    return null;
  }
}

export function signOut() {
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* nothing stored */
  }
}
